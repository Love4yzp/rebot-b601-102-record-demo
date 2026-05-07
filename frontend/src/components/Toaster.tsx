import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react";
import type { CSSProperties, ReactNode } from "react";

export type ToastKind = "info" | "ok" | "warn" | "err";
interface Toast {
  id: number;
  kind: ToastKind;
  text: string;
}

interface ToastCtx {
  push: (kind: ToastKind, text: string) => void;
}

const Ctx = createContext<ToastCtx>({ push: () => {} });

export function useToast() {
  return useContext(Ctx);
}

const COLOR: Record<ToastKind, string> = {
  info: "var(--accent-return)",
  ok: "var(--accent-idle)",
  warn: "var(--accent-trans)",
  err: "var(--accent-rec)",
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const idRef = useRef(0);

  const push = useCallback((kind: ToastKind, text: string) => {
    const id = ++idRef.current;
    setToasts((prev) => [...prev, { id, kind, text }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 3000);
  }, []);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const value = useMemo(() => ({ push }), [push]);

  return (
    <Ctx.Provider value={value}>
      {children}
      <div className="toaster">
        {toasts.map((t) => (
          <button
            key={t.id}
            type="button"
            className="toast"
            onClick={() => dismiss(t.id)}
            style={{ "--toast-accent": COLOR[t.kind] } as CSSProperties}
          >
            {t.text}
          </button>
        ))}
      </div>
    </Ctx.Provider>
  );
}
