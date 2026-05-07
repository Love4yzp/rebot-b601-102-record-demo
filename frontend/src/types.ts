export type PlayMode = "loop" | "once";

export type ControllerMode =
  | "follow"
  | "record"
  | "transition"
  | "playback"
  | "return_to_follow"
  | "paused";

export interface StateSnapshot {
  ts: number;
  mode: ControllerMode;
  safety_enabled: boolean;
  recovering: boolean;
  active_action_id: string | null;
  active_play_mode: PlayMode | null;
  frame_count: number;
  recording_frames: number | null;
  joint_states: Record<string, number>;
  last_error: string | null;
}

export interface ActionMeta {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  default_play_mode: PlayMode;
  duration_s: number;
  frame_count: number;
}
