"""Exception taxonomy for ZotWiki (docs/contract.md SS1.1).

All constructors take a single message argument; none define extra
required parameters.
"""


class ZotWikiError(Exception):
    """Base class for every ZotWiki error."""


class ZoteroError(ZotWikiError):
    """Zotero adapter failure (server-reported or protocol-level)."""


class ItemNotFoundError(ZoteroError):
    """No Zotero item exists for the requested key."""


class CitekeyNotFoundError(ZoteroError):
    """No Zotero item carries the requested citekey."""


class FulltextNotFoundError(ZoteroError):
    """The item has no fulltext, or the key is unknown."""


class ZoteroUnavailableError(ZoteroError):
    """Zotero could not be reached after exhausting all retry attempts."""


class CollectionNotFoundError(ZoteroError):
    """No Zotero collection exists with the requested name."""


class ArticleSchemaError(ZotWikiError):
    """Compiled-article JSON violates the contract SS5.2 schema."""


class PageParseError(ZotWikiError):
    """An on-disk page violates the contract SS6 grammar."""


class VaultError(ZotWikiError):
    """Vault-level failure (missing directory, case collision, bad refs)."""
