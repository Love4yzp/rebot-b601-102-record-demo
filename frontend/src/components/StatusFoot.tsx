import { useState } from "react";
import { api } from "../api";
import type { StateSnapshot } from "../types";

interface Props {
  connected: boolean;
  snapshot: StateSnapshot | null;
}

export function StatusFoot({ connected, snapshot }: Props) {
  const [busy, setBusy] = useState(false);
  const wsClass = connected ? "foot-bar__dot--ok" : "foot-bar__dot--warn";
  const masterOk = snapshot != null && Object.keys(snapshot.joint_states ?? {}).length > 0;
  const masterClass = masterOk ? "foot-bar__dot--ok" : "foot-bar__dot--off";
  const safety = snapshot?.safety_enabled ?? true;

  const toggleSafety = async () => {
    if (busy || !snapshot) return;
    setBusy(true);
    try {
      await api.setSafety(!safety);
    } finally {
      setBusy(false);
    }
  };

  const triggerRecover = async () => {
    if (busy || !snapshot) return;
    if (!window.confirm("复位将停止从臂、重新使能所有电机，并同步软件位姿。继续？")) return;
    setBusy(true);
    try {
      await api.recover();
    } finally {
      setBusy(false);
    }
  };

  const footStyle = !safety
    ? { background: "var(--accent-rec)", color: "#fff" }
    : undefined;

  return (
    <div className="foot-bar" style={footStyle}>
      <div className="foot-bar__item">
        <span className={`foot-bar__dot ${wsClass}`} />
        <span>{connected ? "connected" : "reconnecting"}</span>
      </div>
      <div className="foot-bar__item">
        <span className={`foot-bar__dot ${masterClass}`} />
        <span>{masterOk ? "master ok" : "no joints"}</span>
      </div>
      {snapshot ? (
        <div className="foot-bar__item">{snapshot.frame_count.toLocaleString()} ticks</div>
      ) : null}
      <div className="foot-bar__spacer" />
      {snapshot?.last_error ? (
        <div className="foot-bar__item" style={{ color: safety ? "var(--accent-rec)" : "#fff" }}>
          ⚠ {snapshot.last_error}
        </div>
      ) : null}
      <button
        type="button"
        className="foot-bar__toggle"
        onClick={triggerRecover}
        disabled={busy || !snapshot || (snapshot?.recovering ?? false)}
        title="电机线被拔后重插：先慢混回零位 → 重新握手 → 同步软件位姿（误按时可在 paused 页面解除锁定中止）"
      >
        🔧 复位
      </button>
      <button
        type="button"
        className="foot-bar__toggle"
        onClick={toggleSafety}
        disabled={busy || !snapshot}
        title={safety
          ? "安全模式：限速 + 突变检测。点击关闭后将完全跟随主臂。"
          : "⚠ 安全模式已关闭：主臂任何动作都会原样传递到从臂"}
      >
        {safety ? "🛡 安全模式" : "⚠ 完全跟随 (不安全)"}
      </button>
    </div>
  );
}
