"""Zotero adapter: `ZoteroStore` protocol and `HTTPZoteroStore`.

Implements docs/contract.md SS3 against the HTTP API subset of SS4 using
only the standard library (urllib.request + json).
"""
from __future__ import annotations

import json
import re
import string
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from http.client import HTTPException
from typing import Protocol, runtime_checkable

from zotwiki.errors import (
    CitekeyNotFoundError,
    CollectionNotFoundError,
    FulltextNotFoundError,
    ItemNotFoundError,
    ZoteroError,
    ZoteroUnavailableError,
)
from zotwiki.models import SourceItem

__all__ = ["ZoteroStore", "HTTPZoteroStore", "DEFAULT_BASE_URL"]

DEFAULT_BASE_URL = "http://127.0.0.1:23119/api/users/0"

# Contract SS3.1: first `extra` line matching this yields the citekey.
_CITEKEY_LINE = re.compile(r"^Citation Key:\s*(\S+)\s*$")
# Contract SS3.1: year = first 4-digit run of `data.date`.
_YEAR_RUN = re.compile(r"\d{4}")
# Contract SS3.3: characters kept in citekey tokens.
_NON_ALNUM = re.compile(r"[^a-z0-9]")
_CITEKEY_STOPWORDS = frozenset(
    {"a", "an", "the", "on", "of", "in", "and", "for", "to"}
)
_CITEKEY_SUFFIXES = ("",) + tuple(string.ascii_lowercase)


@runtime_checkable
class ZoteroStore(Protocol):
    """Read/write access to a Zotero library (contract SS3)."""

    def search(self, query: str, limit: int = 25) -> list[SourceItem]: ...

    def get(self, key: str) -> SourceItem: ...

    def fulltext(self, key: str) -> str: ...

    def resolve(self, citekey: str) -> SourceItem: ...

    def add(
        self,
        *,
        title: str,
        url: str | None = None,
        item_type: str = "webpage",
        creators: Sequence[str] = (),
        year: int | None = None,
    ) -> SourceItem: ...
    def collection_items(self, name: str) -> list[SourceItem]: ...


class HTTPZoteroStore:
    """Stdlib HTTP adapter for the Zotero 7 local API subset (SS3.2/SS4)."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = 5.0,
        retries: int = 2,
        backoff: float = 0.1,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._retries = retries
        self._backoff = backoff
        self._sleep = sleep

    # ----- public protocol methods ------------------------------------

    def search(self, query: str, limit: int = 25) -> list[SourceItem]:
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError(f"limit must be an int in 1..100, got {limit!r}")
        results = self._search_raw(query, qmode="titleCreatorYear", limit=limit)
        return [self._map_item(obj) for obj in results]

    def get(self, key: str) -> SourceItem:
        obj = self._request_json(
            self._item_path(key),
            query={"format": "json"},
            not_found=ItemNotFoundError,
        )
        return self._map_item(obj)

    def fulltext(self, key: str) -> str:
        try:
            return self._fetch_fulltext(key)
        except FulltextNotFoundError:
            pass
        for child_key in self._child_keys(key):
            try:
                return self._fetch_fulltext(child_key)
            except FulltextNotFoundError:
                continue
        raise FulltextNotFoundError(f"no fulltext for {key!r} or its children")

    def resolve(self, citekey: str) -> SourceItem:
        results = self._search_raw(citekey, qmode="everything", limit=100)
        for obj in results:
            data = obj.get("data") if isinstance(obj, dict) else None
            if isinstance(data, dict) and self._extract_citekey(data) == citekey:
                return self._map_item(obj)
        raise CitekeyNotFoundError(f"no item with citekey {citekey!r}")

    def add(
        self,
        *,
        title: str,
        url: str | None = None,
        item_type: str = "webpage",
        creators: Sequence[str] = (),
        year: int | None = None,
    ) -> SourceItem:
        creator_names = list(creators)
        citekey = self._free_citekey(
            self._citekey_base(title, creator_names, year)
        )
        payload = [
            {
                "itemType": item_type,
                "title": title,
                "creators": [
                    self._encode_creator(name) for name in creator_names
                ],
                "date": str(year) if year is not None else "",
                "url": url if url is not None else "",
                "extra": f"Citation Key: {citekey}",
            }
        ]
        response = self._request_json("/items", payload=payload)
        if not isinstance(response, dict):
            raise ZoteroError("malformed create response: not a JSON object")
        if response.get("failed"):
            raise ZoteroError(
                f"server reported failure creating item: {response['failed']!r}"
            )
        successful = response.get("successful")
        if not isinstance(successful, dict) or "0" not in successful:
            raise ZoteroError(
                "malformed create response: missing successful['0']"
            )
        return self._map_item(successful["0"])

    def collection_items(self, name: str) -> list[SourceItem]:
        collections = self._request_json(
            "/collections",
            query={"format": "json"},
        )
        if not isinstance(collections, list):
            raise ZoteroError("malformed collections response: expected a JSON array")
        col_key: str | None = None
        for col in collections:
            if not isinstance(col, dict):
                raise ZoteroError("malformed collection object: not a JSON object")
            data = col.get("data") or {}
            if isinstance(data, dict) and data.get("name") == name:
                col_key = col.get("key")
                break
        if col_key is None:
            raise CollectionNotFoundError(f"collection {name!r} not found")
        items = self._request_json(
            f"/collections/{urllib.parse.quote(col_key, safe='')}/items",
            query={"format": "json", "limit": 100},
        )
        if not isinstance(items, list):
            raise ZoteroError("malformed collection items response: expected a JSON array")
        return [self._map_item(obj) for obj in items]

    # ----- citekey generation (contract SS3.3) -------------------------

    @staticmethod
    def _clean_token(token: str) -> str:
        return _NON_ALNUM.sub("", token.lower())

    def _citekey_base(
        self, title: str, creators: Sequence[str], year: int | None
    ) -> str:
        author = "anon"
        if creators:
            tokens = creators[0].split()
            if tokens:
                author = self._clean_token(tokens[-1]) or "anon"
        year_part = str(year) if year is not None else "nd"
        word = "item"
        for candidate in title.split():
            cleaned = self._clean_token(candidate)
            if cleaned and cleaned not in _CITEKEY_STOPWORDS:
                word = cleaned
                break
        return f"{author}{year_part}{word}"

    def _free_citekey(self, base: str) -> str:
        for suffix in _CITEKEY_SUFFIXES:
            candidate = base + suffix
            try:
                self.resolve(candidate)
            except CitekeyNotFoundError:
                return candidate
        raise ZoteroError(f"citekey suffixes exhausted for {base!r}")

    @staticmethod
    def _encode_creator(display: str) -> dict:
        if " " in display:
            first, _, last = display.rpartition(" ")
            return {"creatorType": "author", "firstName": first, "lastName": last}
        return {"creatorType": "author", "name": display}

    # ----- item mapping (contract SS3.1) --------------------------------

    @staticmethod
    def _extract_citekey(data: dict) -> str:
        extra = data.get("extra", "")
        if not isinstance(extra, str):
            raise ZoteroError("malformed item: 'extra' is not a string")
        for line in extra.splitlines():
            match = _CITEKEY_LINE.match(line)
            if match:
                return match.group(1)
        return ""

    @staticmethod
    def _creator_display_names(data: dict) -> tuple[str, ...]:
        creators = data.get("creators", [])
        if not isinstance(creators, list):
            raise ZoteroError("malformed item: 'creators' is not an array")
        names: list[str] = []
        for entry in creators:
            if not isinstance(entry, dict):
                raise ZoteroError("malformed item: creator entry is not an object")
            first = str(entry.get("firstName") or "").strip()
            last = str(entry.get("lastName") or "").strip()
            if first and last:
                names.append(f"{first} {last}")
            elif first or last:
                names.append(last or first)
            else:
                name = str(entry.get("name") or "").strip()
                if name:
                    names.append(name)
        return tuple(names)

    def _map_item(self, obj: object) -> SourceItem:
        if not isinstance(obj, dict):
            raise ZoteroError("malformed item object: not a JSON object")
        key = obj.get("key")
        if not isinstance(key, str) or not key:
            raise ZoteroError("malformed item object: missing 'key'")
        data = obj.get("data") or {}
        if not isinstance(data, dict):
            raise ZoteroError("malformed item object: 'data' is not an object")
        title = data.get("title", "")
        if not isinstance(title, str):
            raise ZoteroError("malformed item object: 'title' is not a string")
        date = data.get("date", "")
        match = _YEAR_RUN.search(date) if isinstance(date, str) else None
        return SourceItem(
            key=key,
            citekey=self._extract_citekey(data),
            title=title,
            creators=self._creator_display_names(data),
            year=int(match.group()) if match else None,
            url=data.get("url") or None,
            has_fulltext=self._probe_fulltext(key),
        )

    def _fetch_fulltext(self, key: str) -> str:
        """Fetch fulltext for a single key; raises FulltextNotFoundError on 404."""
        payload = self._request_json(
            self._item_path(key) + "/fulltext",
            not_found=FulltextNotFoundError,
        )
        if not isinstance(payload, dict) or not isinstance(
            payload.get("content"), str
        ):
            raise ZoteroError(
                f"malformed fulltext response for {key!r}: "
                "'content' must be a string"
            )
        return payload["content"]

    def _child_keys(self, key: str) -> list[str]:
        """SS4.9: fetch child item keys for a parent key.

        Returns a list of child key strings in server order.
        404 from the endpoint is treated as an empty list.
        Non-array response or element missing string 'key' raises ZoteroError.
        """
        try:
            payload = self._request_json(
                self._item_path(key) + "/children",
                query={"format": "json"},
                not_found=FulltextNotFoundError,
            )
        except FulltextNotFoundError:
            return []
        if not isinstance(payload, list):
            raise ZoteroError(
                f"malformed children response for {key!r}: expected a JSON array"
            )
        keys: list[str] = []
        for element in payload:
            if not isinstance(element, dict) or not isinstance(
                element.get("key"), str
            ):
                raise ZoteroError(
                    f"malformed child object in children response for {key!r}: "
                    "missing string 'key'"
                )
            keys.append(element["key"])
        return keys

    def _probe_fulltext(self, key: str) -> bool:
        """SS4.5 two-step probe: parent first, then children on 404."""
        try:
            self._fetch_fulltext(key)
            return True
        except FulltextNotFoundError:
            pass
        for child_key in self._child_keys(key):
            try:
                self._fetch_fulltext(child_key)
                return True
            except FulltextNotFoundError:
                continue
        return False

    # ----- HTTP plumbing (contract SS3.2 retry policy) -------------------

    @staticmethod
    def _item_path(key: str) -> str:
        return "/items/" + urllib.parse.quote(key, safe="")

    def _search_raw(self, query: str, *, qmode: str, limit: int) -> list:
        payload = self._request_json(
            "/items",
            query={"q": query, "qmode": qmode, "limit": limit, "format": "json"},
        )
        if not isinstance(payload, list):
            raise ZoteroError("malformed search response: expected a JSON array")
        return payload

    def _request_json(
        self,
        path: str,
        *,
        query: dict | None = None,
        payload: object = None,
        not_found: type[ZoteroError] | None = None,
    ) -> object:
        body = self._request(path, query=query, payload=payload, not_found=not_found)
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise ZoteroError(f"malformed JSON from server: {error}") from None

    def _request(
        self,
        path: str,
        *,
        query: dict | None = None,
        payload: object = None,
        not_found: type[ZoteroError] | None = None,
    ) -> bytes:
        url = self._base_url + path
        if query is not None:
            url = url + "?" + urllib.parse.urlencode(query)
        headers = {"Accept": "application/json", "Zotero-API-Version": "3"}
        data = None
        method = "GET"
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
            method = "POST"

        attempts = 1 + self._retries
        last_error = "no attempts made"
        for attempt in range(attempts):
            if attempt:  # before retry i (0-indexed): backoff * 2**i
                self._sleep(self._backoff * (2 ** (attempt - 1)))
            request = urllib.request.Request(
                url, data=data, headers=headers, method=method
            )
            try:
                with urllib.request.urlopen(
                    request, timeout=self._timeout
                ) as response:
                    return response.read()
            except urllib.error.HTTPError as error:
                status = error.code
                error.close()
                if status >= 500:  # retryable
                    last_error = f"HTTP {status}"
                    continue
                if status == 404 and not_found is not None:
                    raise not_found(f"HTTP 404 for {method} {url}") from None
                raise ZoteroError(f"HTTP {status} for {method} {url}") from None
            except (HTTPException, OSError) as error:
                # URLError, ConnectionError, and timeouts are all OSError.
                last_error = str(error) or type(error).__name__
                continue
        raise ZoteroUnavailableError(
            f"{method} {url} failed after {attempts} attempt(s): {last_error}"
        )
