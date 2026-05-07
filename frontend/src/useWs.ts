import { useEffect, useRef, useState } from "react";
import type { ControllerMode, StateSnapshot } from "./types";

export interface ModeTimers {
  /** First snapshot.ts seen for the current mode (server wall-clock seconds). */
  modeStartTs: number;
  /** Mode that started at modeStartTs (mirrors snapshot.mode). */
  mode: ControllerMode;
}

export interface WsState {
  connected: boolean;
  snapshot: StateSnapshot | null;
  /** Server ts when the current mode was first observed; null until first snapshot. */
  modeStartTs: number | null;
}

export function useWs(): WsState {
  const [connected, setConnected] = useState(false);
  const [snapshot, setSnapshot] = useState<StateSnapshot | null>(null);
  const [modeStartTs, setModeStartTs] = useState<number | null>(null);
  const lastModeRef = useRef<ControllerMode | null>(null);
  const retryRef = useRef(0);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    const connect = () => {
      if (cancelled) return;
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${proto}://${window.location.host}/ws`);
      socket.onopen = () => {
        retryRef.current = 0;
        setConnected(true);
      };
      socket.onmessage = (ev) => {
        try {
          const snap = JSON.parse(ev.data) as StateSnapshot;
          setSnapshot(snap);
          if (lastModeRef.current !== snap.mode) {
            lastModeRef.current = snap.mode;
            setModeStartTs(snap.ts);
          }
        } catch {
          /* ignore */
        }
      };
      socket.onclose = () => {
        setConnected(false);
        if (cancelled) return;
        const delay = Math.min(8000, 500 * 2 ** retryRef.current);
        retryRef.current += 1;
        timer = setTimeout(connect, delay);
      };
      socket.onerror = () => {
        socket?.close();
      };
    };

    connect();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      socket?.close();
    };
  }, []);

  return { connected, snapshot, modeStartTs };
}
