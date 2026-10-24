"""Record/replay for every nondeterministic external call (Claude, persona prose, Moss, Bitdeer).

Mode "live": serve a recorded response if one exists, otherwise call out and record the response.
Mode "replay": never call out; a missing recording raises ReplayMiss, and the caller takes its deterministic offline
path and marks the decision as such. Together with the seeded simulation this makes a replayed run reproduce the
same audit chain head, byte for byte.

Storage is an append-only JSONL log (one {"kind","key","value"} per line, last write wins), so recording is O(1)
per call regardless of how much has been recorded, and several worlds (live + eval) can share one file safely.
"""

import hashlib
import json
import logging
import threading
from pathlib import Path

from settle.db import dumps

log = logging.getLogger("settle.recorder")
_FILE_LOCK = threading.Lock()  # in-process writers (live world, eval worlds, agent threads) share one file


class ReplayMiss(LookupError):
    pass


class Recorder:
    def __init__(self, path: Path | None, replay: bool = False):
        self.path = path
        self.replay = replay
        self.data: dict[str, dict] = {}
        self.hits = 0
        self.misses = 0
        self.skipped_lines = 0
        if path and path.exists():
            with _FILE_LOCK:
                _terminate_last_line(path)  # so the next append never fuses with a line torn by a crash
                self.data, self.skipped_lines = _load(path)

    @staticmethod
    def key(payload) -> str:
        return hashlib.sha256(dumps(payload).encode("utf-8")).hexdigest()

    def lookup(self, kind: str, payload) -> tuple[str, object | None]:
        """Returns (key, recorded value or None). In replay mode a miss raises ReplayMiss."""
        k = self.key(payload)
        entries = self.data.get(kind, {})
        if k in entries:
            self.hits += 1
            return k, entries[k]
        self.misses += 1
        if self.replay:
            log.warning("replay miss for %s %s", kind, k[:12])
            raise ReplayMiss(f"{kind}:{k[:12]}")
        return k, None

    def put(self, kind: str, key: str, value) -> None:
        line = json.dumps({"kind": kind, "key": key, "value": value}, sort_keys=True)
        with _FILE_LOCK:
            self.data.setdefault(kind, {})[key] = value
            if self.path is None:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")


def _terminate_last_line(path: Path) -> None:
    with open(path, "rb+") as f:
        f.seek(0, 2)
        if f.tell() == 0:
            return
        f.seek(-1, 2)
        if f.read(1) != b"\n":
            f.write(b"\n")


def _load(path: Path) -> tuple[dict, int]:
    """Read the log. A malformed line (e.g. torn by a crash mid-write) is skipped and reported, never fatal."""
    data: dict[str, dict] = {}
    skipped = 0
    with open(path, encoding="utf-8") as f:
        for n, raw in enumerate(f, 1):
            if not raw.strip():
                continue
            try:
                rec = json.loads(raw)
                data.setdefault(rec["kind"], {})[rec["key"]] = rec["value"]
            except (json.JSONDecodeError, KeyError, TypeError):
                skipped += 1
                log.error("recordings %s line %d is malformed; skipped", path, n)
    return data, skipped
