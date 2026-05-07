import { MODE_STYLE } from "../modeStyle";
import type { ControllerMode } from "../types";

interface Props {
  joints: Record<string, number> | undefined;
  mode: ControllerMode;
}

const JOINTS: Array<{ key: string; label: string; range: [number, number] }> = [
  { key: "joint1", label: "J1", range: [-2.6, 2.6] },
  { key: "joint2", label: "J2", range: [-1.8, 1.8] },
  { key: "joint3", label: "J3", range: [-2.6, 2.6] },
  { key: "joint4", label: "J4", range: [-1.8, 1.8] },
  { key: "joint5", label: "J5", range: [-2.6, 2.6] },
  { key: "joint6", label: "J6", range: [-1.8, 1.8] },
  { key: "gripper", label: "GRIP", range: [0, 1] },
];

function normalise(v: number, [lo, hi]: [number, number]) {
  if (hi === lo) return 0;
  return Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
}

export function JointPanel({ joints, mode }: Props) {
  const accent = MODE_STYLE[mode].accent;
  const js = joints ?? {};

  return (
    <aside className="joint-panel">
      <div className="joint-panel__header">Joint Telemetry</div>
      {JOINTS.map((j) => {
        const v = js[j.key];
        const present = typeof v === "number" && isFinite(v);
        const norm = present ? normalise(v as number, j.range) : 0;
        return (
          <div className="joint-bar" key={j.key}>
            <div className="joint-bar__row">
              <span className="joint-bar__label">{j.label}</span>
              <span className="joint-bar__value">
                {present ? (v as number).toFixed(2) : "—"}
              </span>
            </div>
            <div className="joint-bar__track">
              <div
                className="joint-bar__fill"
                style={{
                  width: `${norm * 100}%`,
                  background: present ? accent : "var(--text-faint)",
                }}
              />
              {j.range[0] < 0 && j.range[1] > 0 && <div className="joint-bar__center" />}
            </div>
          </div>
        );
      })}
    </aside>
  );
}
