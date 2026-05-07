"""Action library: variable-count recordings persisted as JSON.

Layout:
    recordings/
        actions/
            <id>.json    # one file per action, name lives inside JSON
        slot_*.json      # legacy 5-slot files (preserved, optionally imported)
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .models import Action, PlayMode

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class ActionLibrary:
    """Thread-safe action library, file-backed, atomic writes."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.actions_dir = self.root / "actions"
        self.actions_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Disk I/O
    # ------------------------------------------------------------------
    def _path(self, action_id: str) -> Path:
        return self.actions_dir / f"{action_id}.json"

    def _atomic_write(self, path: Path, payload: dict) -> None:
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(payload, f)
        tmp.replace(path)

    def _read(self, path: Path) -> Action:
        with open(path) as f:
            data = json.load(f)
        return Action(
            id=data["id"],
            name=data.get("name", data["id"]),
            created_at=data.get("created_at", _now_iso()),
            updated_at=data.get("updated_at", data.get("created_at", _now_iso())),
            default_play_mode=data.get("default_play_mode", "once"),
            duration_s=float(data.get("duration_s", 0.0)),
            frames=data.get("frames", []),
        )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def list(self) -> list[Action]:
        with self._lock:
            actions: list[Action] = []
            for path in sorted(self.actions_dir.glob("*.json")):
                if path.name.endswith(".json.tmp"):
                    continue
                try:
                    actions.append(self._read(path))
                except Exception as e:  # noqa: BLE001
                    log.warning("Failed to load %s: %s", path, e)
            actions.sort(key=lambda a: a.created_at)
            return actions

    def get(self, action_id: str) -> Action:
        with self._lock:
            return self._read(self._path(action_id))

    def exists(self, action_id: str) -> bool:
        return self._path(action_id).exists()

    def create(
        self,
        frames: list[dict],
        name: str | None = None,
        default_play_mode: PlayMode = "once",
    ) -> Action:
        with self._lock:
            action_id = uuid.uuid4().hex
            now = _now_iso()
            duration = float(frames[-1]["t"]) if frames else 0.0
            action = Action(
                id=action_id,
                name=name or f"Action {len(self.list()) + 1}",
                created_at=now,
                updated_at=now,
                default_play_mode=default_play_mode,
                duration_s=duration,
                frames=frames,
            )
            self._atomic_write(self._path(action_id), action.full_dict())
            log.info("Created action %s (%s, %d frames, %.2fs)",
                     action.id, action.name, len(frames), duration)
            return action

    def update(
        self,
        action_id: str,
        name: str | None = None,
        default_play_mode: PlayMode | None = None,
    ) -> Action:
        with self._lock:
            action = self._read(self._path(action_id))
            if name is not None:
                action.name = name
            if default_play_mode is not None:
                action.default_play_mode = default_play_mode
            action.updated_at = _now_iso()
            self._atomic_write(self._path(action_id), action.full_dict())
            return action

    def delete(self, action_id: str) -> None:
        with self._lock:
            path = self._path(action_id)
            if path.exists():
                path.unlink()
                log.info("Deleted action %s", action_id)

    # ------------------------------------------------------------------
    # Legacy migration
    # ------------------------------------------------------------------
    def migrate_legacy_slots(self) -> int:
        """If actions/ is empty and slot_<N>.json files exist, import them.

        Old slot files are NOT deleted — operator can clean up manually.
        Returns number of imported actions. Idempotent.
        """
        with self._lock:
            if any(self.actions_dir.glob("*.json")):
                return 0
            legacy = sorted(self.root.glob("slot_*.json"))
            if not legacy:
                return 0
            imported = 0
            for path in legacy:
                try:
                    with open(path) as f:
                        data = json.load(f)
                    frames = data.get("frames", [])
                    if not frames:
                        continue
                    slot_n = path.stem.replace("slot_", "")
                    self.create(
                        frames=frames,
                        name=f"slot_{slot_n} (imported)",
                        default_play_mode="loop",
                    )
                    imported += 1
                except Exception as e:  # noqa: BLE001
                    log.warning("Failed to import %s: %s", path, e)
            log.info("Imported %d legacy slot file(s) to action library", imported)
            return imported
