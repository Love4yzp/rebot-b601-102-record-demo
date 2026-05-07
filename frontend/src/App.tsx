import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import { useWs } from "./useWs";
import type { ActionMeta } from "./types";
import { ToastProvider, useToast } from "./components/Toaster";
import { StatusBanner } from "./components/StatusBanner";
import { JointPanel } from "./components/JointPanel";
import { StageMain } from "./components/StageMain";
import { StatusFoot } from "./components/StatusFoot";
import { ActionPicker } from "./components/ActionPicker";

export default function App() {
  return (
    <ToastProvider>
      <AppInner />
    </ToastProvider>
  );
}

function AppInner() {
  const toast = useToast();
  const { connected, snapshot, modeStartTs } = useWs();
  const [actions, setActions] = useState<ActionMeta[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lastModeRef = useRef<string | null>(null);

  const handlePause = useCallback(async () => {
    try {
      await api.pause();
      toast.push("info", "已紧急停止 — 从臂保持当前位姿");
    } catch (e) {
      toast.push("err", `急停失败：${e instanceof Error ? e.message : String(e)}`);
    }
  }, [toast]);

  const handleResume = useCallback(async () => {
    try {
      await api.resume();
      toast.push("ok", "已恢复跟随");
    } catch (e) {
      toast.push("err", `恢复失败：${e instanceof Error ? e.message : String(e)}`);
    }
  }, [toast]);

  const refresh = useCallback(async () => {
    try {
      setActions(await api.listActions());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Refresh action list whenever a recording finishes (mode goes record -> follow)
  // or when leaving playback so renames/deletes from elsewhere are picked up.
  useEffect(() => {
    if (!snapshot) return;
    const prev = lastModeRef.current;
    lastModeRef.current = snapshot.mode;
    if (prev && prev !== snapshot.mode && snapshot.mode === "follow") {
      refresh();
    }
  }, [snapshot, refresh]);

  const mode = snapshot?.mode ?? "follow";
  // Picker can keep playing other actions only when the controller is idle.
  const playDisabled = mode !== "follow";

  return (
    <>
      {!connected && (
        <div className="conn-overlay">
          <div className="conn-card">
            <div className="conn-card__spinner" />
            <div className="conn-card__title">正在连接到机器人服务...</div>
            <div className="conn-card__hint">如果一直无法连接，请检查后端是否在运行</div>
          </div>
        </div>
      )}

      <div className="app-shell">
        <StatusBanner
          connected={connected}
          snapshot={snapshot}
          modeStartTs={modeStartTs}
          actions={actions}
          onPause={handlePause}
          onResume={handleResume}
        />
        {error && (
          <div className="error-banner">
            <span>{error}</span>
            <button
              type="button"
              className="error-banner__close"
              onClick={() => setError(null)}
              aria-label="关闭"
            >
              ✕
            </button>
          </div>
        )}
        <JointPanel joints={snapshot?.joint_states} mode={mode} />
        <main className="main-stage">
          {snapshot ? (
            <StageMain
              snapshot={snapshot}
              modeStartTs={modeStartTs}
              actions={actions}
              playDisabled={playDisabled}
              onChange={refresh}
              onOpenPicker={() => setPickerOpen(true)}
            />
          ) : null}
        </main>
        <StatusFoot connected={connected} snapshot={snapshot} />
      </div>

      {pickerOpen && (
        <ActionPicker
          actions={actions}
          playDisabled={playDisabled}
          onClose={() => setPickerOpen(false)}
          onChange={refresh}
        />
      )}
    </>
  );
}
