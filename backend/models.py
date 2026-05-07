"""Pydantic request/response models and the internal Action dataclass."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from pydantic import BaseModel, Field


PlayMode = Literal["loop", "once"]
ControllerMode = Literal[
    "follow", "record", "transition", "playback", "return_to_follow", "paused"
]


# ---------------------------------------------------------------------------
# Internal storage dataclass
# ---------------------------------------------------------------------------

@dataclass
class Action:
    id: str
    name: str
    created_at: str
    updated_at: str
    default_play_mode: PlayMode
    duration_s: float
    frames: list[dict] = field(default_factory=list)

    def meta_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "default_play_mode": self.default_play_mode,
            "duration_s": self.duration_s,
            "frame_count": len(self.frames),
        }

    def full_dict(self) -> dict:
        return {**self.meta_dict(), "frames": self.frames}


# ---------------------------------------------------------------------------
# REST request models
# ---------------------------------------------------------------------------

class RecordStartRequest(BaseModel):
    name: Optional[str] = None


class PlayRequest(BaseModel):
    mode: PlayMode


class SafetyRequest(BaseModel):
    enabled: bool


class ActionPatch(BaseModel):
    name: Optional[str] = None
    default_play_mode: Optional[PlayMode] = None


# ---------------------------------------------------------------------------
# REST response models
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    ok: bool
    mode: ControllerMode
    master_connected: bool
    slave_connected: bool


class StateSnapshot(BaseModel):
    ts: float
    mode: ControllerMode
    safety_enabled: bool = True
    recovering: bool = False
    active_action_id: Optional[str] = None
    active_play_mode: Optional[PlayMode] = None
    frame_count: int
    recording_frames: Optional[int] = None
    joint_states: dict = Field(default_factory=dict)
    last_error: Optional[str] = None


class ActionMeta(BaseModel):
    id: str
    name: str
    created_at: str
    updated_at: str
    default_play_mode: PlayMode
    duration_s: float
    frame_count: int
