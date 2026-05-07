import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { ActionMeta, PlayMode } from "../types";
import { useToast } from "./Toaster";

interface Props {
  action: ActionMeta;
  variant?: "quick" | "picker";
  /** Disable play/loop/delete (e.g., during another playback). */
  playDisabled?: boolean;
  /** Show the delete button (with two-tap confirm). */
  showDelete?: boolean;
  /** Called after a successful rename or delete so parent can refresh list. */
  onChange?: () => void;
  /** Called after a successful play start (e.g., to close the picker). */
  onPlayed?: () => void;
}

function fmtDur(s: number): string {
  if (!isFinite(s) || s <= 0) return "0s";
  const m = Math.floor(s / 60);
  const r = (s - m * 60).toFixed(1);
  return m > 0 ? `${m}m ${r}s` : `${r}s`;
}

export function RecordingRow({
  action,
  variant = "quick",
  playDisabled = false,
  showDelete = false,
  onChange,
  onPlayed,
}: Props) {
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(action.name);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const deleteTimerRef = useRef<number | null>(null);

  // Reset local state when the underlying action changes (rename from server, etc).
  useEffect(() => {
    setEditing(false);
    setConfirmDelete(false);
    setDraft(action.name);
  }, [action.id, action.name]);

  useEffect(() => {
    if (editing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing]);

  useEffect(() => {
    return () => {
      if (deleteTimerRef.current != null) window.clearTimeout(deleteTimerRef.current);
    };
  }, []);

  async function commitName() {
    const nextName = draft.trim();
    if (!nextName || nextName === action.name) {
      setDraft(action.name);
      setEditing(false);
      return;
    }
    try {
      await api.rename(action.id, nextName);
      toast.push("ok", `已重命名为「${nextName}」`);
      onChange?.();
    } catch (e) {
      setDraft(action.name);
      toast.push("err", `重命名失败：${e instanceof Error ? e.message : String(e)}`);
    }
    setEditing(false);
  }

  async function handlePlay(mode: PlayMode) {
    if (playDisabled) return;
    try {
      await api.play(action.id, mode);
      toast.push("ok", `执行「${action.name}」${mode === "loop" ? "（循环）" : ""}`);
      onPlayed?.();
    } catch (e) {
      toast.push("err", `执行失败：${e instanceof Error ? e.message : String(e)}`);
    }
  }

  async function handleDelete() {
    if (playDisabled) return;
    if (!confirmDelete) {
      setConfirmDelete(true);
      if (deleteTimerRef.current != null) window.clearTimeout(deleteTimerRef.current);
      deleteTimerRef.current = window.setTimeout(() => {
        setConfirmDelete(false);
        deleteTimerRef.current = null;
      }, 2500);
      return;
    }
    try {
      await api.remove(action.id);
      toast.push("ok", `已删除「${action.name}」`);
      onChange?.();
    } catch (e) {
      toast.push("err", `删除失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setConfirmDelete(false);
    }
  }

  return (
    <div className={`rec-row rec-row--${variant}`}>
      <div className="rec-row__main">
        {editing ? (
          <input
            ref={inputRef}
            className="rec-row__name-input"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={() => void commitName()}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void commitName();
              } else if (e.key === "Escape") {
                e.preventDefault();
                setDraft(action.name);
                setEditing(false);
              }
            }}
            aria-label="动作名称"
          />
        ) : (
          <button
            type="button"
            className="rec-row__name"
            onClick={() => setEditing(true)}
            title="点击重命名"
          >
            {action.name}
          </button>
        )}
        <div className="rec-row__meta">
          {fmtDur(action.duration_s)} · {action.frame_count} 帧
        </div>
      </div>
      <div className="rec-row__actions">
        {showDelete && (
          <button
            type="button"
            className={`rec-row__btn rec-row__btn--ghost${confirmDelete ? " is-danger" : ""}`}
            onClick={() => void handleDelete()}
            disabled={playDisabled}
          >
            {confirmDelete ? "确认删除" : "删除"}
          </button>
        )}
        <button
          type="button"
          className="rec-row__btn rec-row__btn--loop"
          onClick={() => void handlePlay("loop")}
          disabled={playDisabled}
        >
          循环
        </button>
        <button
          type="button"
          className="rec-row__btn rec-row__btn--play"
          onClick={() => void handlePlay("once")}
          disabled={playDisabled}
        >
          执行
        </button>
      </div>
    </div>
  );
}
