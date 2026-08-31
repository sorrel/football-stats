"""On-disk cache of raw source pages, plus a manifest of what was fetched when.

The parser reads only from here. That is what makes a schema change a cheap
local re-parse instead of another crawl.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


class PageCache:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._manifest_path = self.root / "manifest.json"

    def _manifest(self) -> dict[str, str]:
        if not self._manifest_path.exists():
            return {}
        return json.loads(self._manifest_path.read_text(encoding="utf-8"))

    def _page_path(self, key: str) -> Path:
        # Hashing the key keeps arbitrary keys inside the cache root and
        # sidesteps path-length and character limits.
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / "pages" / digest[:2] / f"{digest}.html"

    def has(self, key: str) -> bool:
        return self._page_path(key).exists()

    def get(self, key: str) -> str:
        path = self._page_path(key)
        if not path.exists():
            raise KeyError(key)
        return path.read_text(encoding="utf-8")

    def put(self, key: str, text: str) -> None:
        path = self._page_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        manifest = self._manifest()
        manifest[key] = datetime.now(UTC).isoformat()
        self._manifest_path.write_text(
            json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")

    def keys(self) -> list[str]:
        return sorted(self._manifest())

    def fetched_at(self, key: str) -> str | None:
        return self._manifest().get(key)
