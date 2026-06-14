"""Shared fixtures for the ZotWiki test suite (M1: Zotero adapter).

The fake Zotero HTTP server below is written from docs/contract.md SS4 alone:

  GET  {base}/items?q=&qmode=&limit=&format=json   -> JSON array of item objects
  GET  {base}/items/{KEY}?format=json              -> one item object | 404
  GET  {base}/items/{KEY}/fulltext                 -> {"content": "..."} | 404
  POST {base}/items                                -> {"successful": {...}, "failed": {}}

It is configurable per test: items to serve, a fulltext map, raw-body
overrides (malformed JSON), and failure injection (5xx / arbitrary status,
optionally restricted to one exact path and method) for the retry tests.
Everything listens on 127.0.0.1 only.  No zotwiki import happens at module
scope; the store factory imports the adapter lazily so this infrastructure
is valid regardless of implementation presence.
"""
from __future__ import annotations

import json
import random
import re
import string
import traceback
from dataclasses import dataclass
from urllib.parse import parse_qs

import pytest
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Response

BASE_PATH = "/api/users/0"
KEY_ALPHABET = string.ascii_uppercase + string.digits


def random_key() -> str:
    """A runtime-generated Zotero item key: 8 chars of [A-Z0-9]."""
    return "".join(random.choices(KEY_ALPHABET, k=8))


def make_creator(first=None, last=None, name=None, creator_type="author"):
    """Build a contract SS4.4 creator entry; only passed fields are emitted."""
    entry = {"creatorType": creator_type}
    if first is not None:
        entry["firstName"] = first
    if last is not None:
        entry["lastName"] = last
    if name is not None:
        entry["name"] = name
    return entry


def _json_response(payload, status=200) -> Response:
    return Response(
        json.dumps(payload), status=status, content_type="application/json"
    )


@dataclass
class RecordedRequest:
    method: str
    path: str
    params: dict          # parsed query string: name -> list of values
    raw_query: str        # undecoded query string as received
    body: bytes


@dataclass
class _FailureInjection:
    times: int
    status: int
    path: str | None      # exact path match; None = any path
    method: str | None    # exact method match; None = any method


class FakeZotero:
    """Stateful fake of the contract SS4 Zotero HTTP API subset."""

    creator = staticmethod(make_creator)

    def __init__(self, server: HTTPServer) -> None:
        self.server = server
        self.items_path = BASE_PATH + "/items"
        self.collections_path = BASE_PATH + "/collections"
        self.reset()
        server.expect_request(re.compile(r".*")).respond_with_handler(self._handle)

    # ----- per-test configuration ------------------------------------

    def reset(self) -> None:
        self.items: dict[str, dict] = {}                   # key -> SS4.4 item object
        self.fulltext: dict[str, str] = {}                 # key -> fulltext content
        self.collections: dict[str, dict] = {}             # key -> collection object
        self.collection_members: dict[str, list[str]] = {} # collection key -> [item keys]
        self.requests: list[RecordedRequest] = []
        self.post_bodies: list = []            # parsed JSON bodies of POSTs
        self.created_keys: list[str] = []      # keys assigned by POST /items
        self.post_response = None              # override for the POST reply
        self.handler_errors: list[str] = []    # bugs in this fake itself
        self._raw: dict[tuple, tuple] = {}     # (method, path) -> (status, body, ctype)
        self._fail: _FailureInjection | None = None

    def add_item(
        self,
        key: str | None = None,
        *,
        title: str | None = None,
        creators: list | None = None,
        date: str | None = None,
        url: str | None = None,
        extra: str | None = None,
        citekey: str | None = None,
        item_type: str = "journalArticle",
        fulltext: str | None = None,
    ) -> str:
        """Register an item; None fields are omitted from `data` entirely."""
        key = key or self._unique_key()
        data = {"key": key, "itemType": item_type}
        if title is not None:
            data["title"] = title
        if creators is not None:
            data["creators"] = list(creators)
        if date is not None:
            data["date"] = date
        if url is not None:
            data["url"] = url
        if citekey is not None and extra is None:
            extra = f"Citation Key: {citekey}"
        if extra is not None:
            data["extra"] = extra
        return self.put_raw_item(key, data, fulltext=fulltext)

    def put_raw_item(self, key: str, data: dict, *, fulltext: str | None = None) -> str:
        self.items[key] = {"key": key, "version": 1, "data": data}
        if fulltext is not None:
            self.fulltext[key] = fulltext
        return key

    def add_collection(self, name: str, key: str | None = None) -> str:
        """Register a named collection; returns its key."""
        key = key or "C" + self._unique_key()[:7]
        self.collections[key] = {
            "key": key, "version": 1,
            "data": {"key": key, "name": name, "parentCollection": False},
        }
        self.collection_members[key] = []
        return key

    def add_item_to_collection(self, collection_key: str, item_key: str) -> None:
        """Link an already-registered item to a collection."""
        self.collection_members.setdefault(collection_key, []).append(item_key)

    def fail(self, times: int, *, status: int = 500,
             path: str | None = None, method: str | None = None) -> None:
        """Respond `status` to the next `times` requests matching path/method."""
        self._fail = _FailureInjection(
            times=times, status=status, path=path,
            method=method.upper() if method else None,
        )

    def set_raw(self, method: str, path: str, status: int, body: bytes,
                content_type: str = "application/json") -> None:
        """Serve a verbatim body for (method, path) — e.g. malformed JSON."""
        self._raw[(method.upper(), path)] = (status, body, content_type)

    # ----- addressing helpers ----------------------------------------

    @property
    def base_url(self) -> str:
        return f"http://{self.server.host}:{self.server.port}{BASE_PATH}"

    def item_path(self, key: str) -> str:
        return f"{self.items_path}/{key}"

    def fulltext_path(self, key: str) -> str:
        return f"{self.items_path}/{key}/fulltext"

    # ----- recorded-traffic helpers ----------------------------------

    def requests_for(self, path: str, method: str | None = None) -> list[RecordedRequest]:
        return [
            r for r in self.requests
            if r.path == path and (method is None or r.method == method.upper())
        ]

    def search_requests(self) -> list[RecordedRequest]:
        return self.requests_for(self.items_path, "GET")

    def post_requests(self) -> list[RecordedRequest]:
        return self.requests_for(self.items_path, "POST")

    def item_requests(self, key: str) -> list[RecordedRequest]:
        return self.requests_for(self.item_path(key), "GET")

    def probe_requests(self, key: str) -> list[RecordedRequest]:
        return self.requests_for(self.fulltext_path(key), "GET")

    # ----- request handling ------------------------------------------

    def _unique_key(self) -> str:
        while True:
            key = random_key()
            if key not in self.items:
                return key

    def _handle(self, request) -> Response:
        try:
            return self._dispatch(request)
        except Exception:
            self.handler_errors.append(traceback.format_exc())
            return Response("fake zotero server bug", status=599,
                            content_type="text/plain")

    def _dispatch(self, request) -> Response:
        raw_query = request.query_string.decode("utf-8")
        rec = RecordedRequest(
            method=request.method,
            path=request.path,
            params=parse_qs(raw_query, keep_blank_values=True),
            raw_query=raw_query,
            body=request.get_data(),
        )
        self.requests.append(rec)

        override = self._raw.get((rec.method, rec.path))
        if override is not None:
            status, body, ctype = override
            return Response(body, status=status, content_type=ctype)

        f = self._fail
        if (
            f is not None
            and f.times > 0
            and (f.path is None or f.path == rec.path)
            and (f.method is None or f.method == rec.method)
        ):
            f.times -= 1
            return Response("injected failure", status=f.status,
                            content_type="text/plain")

        if rec.path == self.items_path and rec.method == "GET":
            return self._search(rec)
        if rec.path == self.items_path and rec.method == "POST":
            return self._create(rec)
        m = re.fullmatch(re.escape(self.items_path) + r"/([^/]+)/fulltext", rec.path)
        if m and rec.method == "GET":
            return self._serve_fulltext(m.group(1))
        m = re.fullmatch(re.escape(self.items_path) + r"/([^/]+)", rec.path)
        if m and rec.method == "GET":
            return self._serve_item(m.group(1))
        if rec.path == self.collections_path and rec.method == "GET":
            return _json_response(list(self.collections.values()))
        m = re.fullmatch(re.escape(self.collections_path) + r"/([^/]+)/items", rec.path)
        if m and rec.method == "GET":
            return self._serve_collection_items(m.group(1))
        return Response("not found", status=404, content_type="text/plain")

    def _search(self, rec: RecordedRequest) -> Response:
        q = rec.params.get("q", [""])[0]
        qmode = rec.params.get("qmode", ["titleCreatorYear"])[0]
        try:
            limit = int(rec.params.get("limit", ["25"])[0])
        except ValueError:
            return Response("bad limit", status=400, content_type="text/plain")
        needle = q.lower()
        out = []
        for obj in self.items.values():
            if len(out) >= limit:
                break
            if self._matches(obj, needle, qmode):
                out.append(obj)
        return _json_response(out)

    @staticmethod
    def _matches(obj: dict, needle: str, qmode: str) -> bool:
        d = obj.get("data", {})
        fields = [str(d.get("title", "")), str(d.get("date", ""))]
        for c in d.get("creators", []):
            fields.extend(str(c.get(k, "")) for k in ("firstName", "lastName", "name"))
        if qmode == "everything":
            fields.append(str(d.get("extra", "")))
            fields.append(str(d.get("url", "")))
        return any(needle in f.lower() for f in fields)

    def _serve_item(self, key: str) -> Response:
        obj = self.items.get(key)
        if obj is None:
            return Response("no such item", status=404, content_type="text/plain")
        return _json_response(obj)

    def _serve_fulltext(self, key: str) -> Response:
        if key not in self.fulltext:
            return Response("no fulltext", status=404, content_type="text/plain")
        return _json_response({"content": self.fulltext[key]})

    def _serve_collection_items(self, collection_key: str) -> Response:
        keys = self.collection_members.get(collection_key, [])
        return _json_response([self.items[k] for k in keys if k in self.items])

    def _create(self, rec: RecordedRequest) -> Response:
        try:
            posted = json.loads(rec.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return Response("bad json body", status=400, content_type="text/plain")
        self.post_bodies.append(posted)
        if self.post_response is not None:
            return _json_response(self.post_response)
        if (
            not isinstance(posted, list)
            or len(posted) != 1
            or not isinstance(posted[0], dict)
        ):
            return Response("body must be a one-element JSON array",
                            status=400, content_type="text/plain")
        data = dict(posted[0])
        key = self._unique_key()
        data["key"] = key
        obj = {"key": key, "version": 1, "data": data}
        self.items[key] = obj
        self.created_keys.append(key)
        return _json_response({"successful": {"0": obj}, "failed": {}})


# ----- fixtures --------------------------------------------------------


@pytest.fixture(scope="session")
def _zotero_http_server():
    server = HTTPServer(host="127.0.0.1", port=0)
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="session")
def _fake_zotero_singleton(_zotero_http_server):
    return FakeZotero(_zotero_http_server)


@pytest.fixture
def fake_zotero(_fake_zotero_singleton):
    fake = _fake_zotero_singleton
    fake.reset()
    yield fake
    errors = list(fake.handler_errors)
    fake.reset()
    if errors:
        pytest.fail(
            "fake Zotero server handler raised (test-infrastructure bug):\n"
            + "\n".join(errors),
            pytrace=False,
        )


@pytest.fixture
def zstore(fake_zotero):
    """Factory: (HTTPZoteroStore against the fake, recorded sleep calls).

    The sleep seam of contract SS3.2 is always injected so no test ever
    really sleeps; pass retries=/backoff=/timeout=/base_url= per test.
    """

    def make(base_url: str | None = None, **kwargs):
        from zotwiki.zotero import HTTPZoteroStore  # deferred: M1 surface

        sleeps: list[float] = []
        kwargs.setdefault("sleep", sleeps.append)
        store = HTTPZoteroStore(
            base_url if base_url is not None else fake_zotero.base_url,
            **kwargs,
        )
        return store, sleeps

    return make
