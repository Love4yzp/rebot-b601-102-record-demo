import { MODE_STYLE } from "../modeStyle";
import type { ActionMeta, StateSnapshot } from "../types";

interface Props {
  connected: boolean;
  snapshot: StateSnapshot | null;
  modeStartTs: number | null;
  actions: ActionMeta[];
  onPause: () => void;
  onResume: () => void;
}

function fmtClock(s: number): string {
  if (!isFinite(s) || s < 0) s = 0;
  const m = Math.floor(s / 60);
  const r = Math.floor(s - m * 60);
  return `${m}:${String(r).padStart(2, "0")}`;
}

function EstopButton({
  paused,
  onPause,
  onResume,
  disabled,
}: {
  paused: boolean;
  onPause: () => void;
  onResume: () => void;
  disabled?: boolean;
}) {
  if (paused) {
    return (
      <button
        type="button"
        className="estop-btn estop-btn--resume"
        onClick={onResume}
        disabled={disabled}
        title="解除锁定，慢插值回到主臂当前位姿"
      >
        ▶ 解除锁定
      </button>
    );
  }
  return (
    <button
      type="button"
      className="estop-btn"
      onClick={onPause}
      disabled={disabled}
      title="紧急停止：从臂保持当前位姿，主臂活动不再被传递"
    >
      ■ 急停
    </button>
  );
}

export function StatusBanner({
  connected,
  snapshot,
  modeStartTs,
  actions,
  onPause,
  onResume,
}: Props) {
  const paused = snapshot?.mode === "paused";

  if (!snapshot) {
    return (
      <div className="status-banner--idle">
        <span className="brand">rebot 录制管理</span>
        <span className="status-banner__center">{connected ? "等待状态..." : "离线"}</span>
        <span className="status-banner__action">
          <EstopButton paused={false} onPause={onPause} onResume={onResume} disabled={!connected} />
        </span>
      </div>
    );
  }

  if (snapshot.mode === "follow") {
    return (
      <div className="status-banner--idle">
        <span className="brand">rebot 录制管理</span>
        <span className="status-banner__center">主臂 → 从臂 跟随中</span>
        <span className="status-banner__action">
          <EstopButton paused={false} onPause={onPause} onResume={onResume} />
        </span>
      </div>
    );
  }

  const style = MODE_STYLE[snapshot.mode];
  const elapsed = modeStartTs != null ? snapshot.ts - modeStartTs : 0;

  let detail = "";
  if (snapshot.mode === "record") {
    const frames = snapshot.recording_frames ?? 0;
    detail = `${fmtClock(elapsed)} · ${frames}f`;
  } else if (snapshot.mode === "playback" || snapshot.mode === "transition") {
    const action = actions.find((a) => a.id === snapshot.active_action_id);
    const name = action?.name ?? snapshot.active_action_id ?? "";
    if (snapshot.mode === "playback" && action) {
      const isLoop = snapshot.active_play_mode === "loop";
      const dur = action.duration_s;
      const e = isLoop ? elapsed % Math.max(dur, 0.001) : Math.min(elapsed, dur);
      detail = `${name} · ${e.toFixed(1)}s / ${dur.toFixed(1)}s${isLoop ? " · 循环" : ""}`;
    } else {
      detail = name;
    }
  } else if (snapshot.mode === "return_to_follow") {
    detail = `${elapsed.toFixed(1)}s`;
  } else if (snapshot.mode === "paused") {
    detail = "从臂已锁定，主臂活动不会被传递";
  }

  return (
    <div
      className="status-banner"
      style={{ background: style.accent, color: "#000" }}
    >
      <span
        className={`status-banner__dot${style.pulse ? " status-banner__dot--pulse" : ""}`}
        style={{ background: "#000" }}
      />
      <span className="status-banner__label">{style.label}</span>
      {detail ? <span className="status-banner__detail">{detail}</span> : null}
      <span className="status-banner__action">
        <EstopButton paused={paused} onPause={onPause} onResume={onResume} />
      </span>
    </div>
  );
}
