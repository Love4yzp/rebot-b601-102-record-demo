import { useEffect, useMemo, useState } from "react";
import type { ActionMeta } from "../types";
import { RecordingRow } from "./RecordingRow";

type Sort = "recent" | "name" | "duration";

interface Props {
  actions: ActionMeta[];
  playDisabled: boolean;
  onClose: () => void;
  onChange: () => void;
}

export function ActionPicker({ actions, playDisabled, onClose, onChange }: Props) {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<Sort>("recent");

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const visible = useMemo(() => {
    let xs = actions.slice();
    const ql = q.trim().toLowerCase();
    if (ql) xs = xs.filter((r) => r.name.toLowerCase().includes(ql));
    xs.sort((a, b) => {
      if (sort === "name") return a.name.localeCompare(b.name);
      if (sort === "duration") return b.duration_s - a.duration_s;
      // recent — created_at is ISO string; lexical sort works for ISO 8601
      return (b.created_at || "").localeCompare(a.created_at || "");
    });
    return xs;
  }, [actions, q, sort]);

  return (
    <div
      className="picker-overlay"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="picker"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="picker__header">
          <span className="picker__title">动作库 · {actions.length}</span>
          <button
            type="button"
            className="picker__close"
            onClick={onClose}
            aria-label="关闭"
          >
            ✕
          </button>
        </div>
        <div className="picker__toolbar">
          <input
            className="picker__search"
            placeholder="搜索..."
            value={q}
            onChange={(e) => setQ(e.target.value)}
            autoFocus
          />
          <div className="picker__sort">
            {(["recent", "name", "duration"] as Sort[]).map((s) => (
              <button
                key={s}
                type="button"
                className={`picker__sort-btn${sort === s ? " is-active" : ""}`}
                onClick={() => setSort(s)}
              >
                {s === "recent" ? "最近" : s === "name" ? "名称" : "时长"}
              </button>
            ))}
          </div>
        </div>
        <div className="picker__list">
          {visible.length === 0 ? (
            <div className="picker__empty">
              {q.trim() ? `没有匹配「${q}」的动作` : "动作库为空"}
            </div>
          ) : (
            visible.map((a) => (
              <RecordingRow
                key={a.id}
                action={a}
                variant="picker"
                playDisabled={playDisabled}
                showDelete
                onChange={onChange}
                onPlayed={onClose}
              />
            ))
          )}
        </div>
      </div>
    </div>
  );
}
