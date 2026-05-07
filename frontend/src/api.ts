import type { ActionMeta, PlayMode } from "./types";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${text ? ": " + text : ""}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  listActions: () => req<ActionMeta[]>("/api/actions"),
  startRecord: (name?: string) =>
    req("/api/actions/record/start", {
      method: "POST",
      body: JSON.stringify({ name: name ?? null }),
    }),
  stopRecord: () => req<ActionMeta>("/api/actions/record/stop", { method: "POST" }),
  play: (id: string, mode: PlayMode) =>
    req(`/api/actions/${id}/play`, {
      method: "POST",
      body: JSON.stringify({ mode }),
    }),
  stopPlay: () => req("/api/actions/stop", { method: "POST" }),
  follow: () => req("/api/follow", { method: "POST" }),
  pause: () => req("/api/pause", { method: "POST" }),
  resume: () => req("/api/resume", { method: "POST" }),
  setSafety: (enabled: boolean) =>
    req("/api/safety", {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }),
  recover: () => req("/api/recover", { method: "POST" }),
  rename: (id: string, name: string) =>
    req<ActionMeta>(`/api/actions/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),
  setDefaultMode: (id: string, mode: PlayMode) =>
    req<ActionMeta>(`/api/actions/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ default_play_mode: mode }),
    }),
  remove: (id: string) =>
    req(`/api/actions/${id}`, { method: "DELETE" }),
};
