"""HMAC-seeded identity map: same (type, normalized value) -> same fake, across files and runs."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)


def load_key(key_dir: Path = Path(".piiredact")) -> bytes:
    env = os.environ.get("PIIREDACT_SECRET")
    if env:
        return hashlib.sha256(env.encode()).digest()
    path = key_dir / "key"
    if path.exists():
        return path.read_bytes()
    key_dir.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    path.write_bytes(key)
    os.chmod(path, 0o600)
    return key


class IdentityMap:
    def __init__(self, db: Path | None, key: bytes) -> None:
        self._key = key
        self._map: dict[tuple[str, str], str] = {}
        self._used: dict[tuple[str, str], str] = {}
        self._new: list[tuple[str, str, str]] = []
        self._db = db
        if db is not None and db.exists():
            con = sqlite3.connect(db)
            for etype, norm, fake in con.execute("SELECT etype, norm, fake FROM map"):
                self._map[(etype, norm)] = fake
                self._used[(etype, fake)] = norm
            con.close()

    def seed(self, label: str) -> int:
        return int.from_bytes(hmac.new(self._key, label.encode(), "sha256").digest()[:8], "big")

    def get_or_create(
        self,
        etype: str,
        norm: str,
        make: Callable[[int], str],
        accept: Callable[[str], bool] = lambda _f: True,
    ) -> str:
        """make(counter) builds a candidate; re-seed with a counter until it is new and acceptable."""
        key = (etype, norm)
        if key in self._map:
            if accept(self._map[key]):
                return self._map[key]
            # a stored fake that now contains a known original would leak: replace it
            log.warning(
                "identity map: regenerating a stored %s fake that now matches an original", etype
            )
            self._used.pop((etype, self._map.pop(key)), None)
        fake = make(0)
        for counter in range(1, 50):
            if accept(fake) and (etype, fake) not in self._used:
                break
            fake = make(counter)
        self._map[key] = fake
        self._used[(etype, fake)] = norm
        self._new.append((etype, norm, fake))
        return fake

    def items(self) -> list[tuple[str, str, str]]:
        return [(e, n, f) for (e, n), f in self._map.items()]

    def close(self) -> None:
        if self._db is None or not self._new:
            return
        self._db.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self._db)
        con.execute(
            "CREATE TABLE IF NOT EXISTS map (etype TEXT, norm TEXT, fake TEXT, PRIMARY KEY (etype, norm))"
        )
        con.executemany("INSERT OR REPLACE INTO map VALUES (?, ?, ?)", self._new)
        con.commit()
        con.close()
        self._new = []
