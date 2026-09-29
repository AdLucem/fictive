/** Every call the UI makes, against the paths `fictive/web/app.py` serves. */

import type { Scenario, Session, SessionsIndex } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: init?.body ? { "content-type": "application/json" } : undefined,
    ...init,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* the body was not JSON; the status line is all we have */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export const api = {
  scenario: () => request<Scenario>("/api/scenario"),

  sessions: () => request<SessionsIndex>("/api/sessions"),

  createSession: (body: { title?: string; load_session_id?: string } = {}) =>
    request<Session>("/api/sessions", { method: "POST", body: JSON.stringify(body) }),

  session: (id: string) => request<Session>(`/api/sessions/${id}`),

  sendMessage: (id: string, text: string) =>
    request<Session>(`/api/sessions/${id}/messages`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  /** The reader let a timed request run out; the flow runs on without an answer. */
  timeoutInput: (id: string) => request<Session>(`/api/sessions/${id}/timeout`, { method: "POST" }),

  /** Replace one reader message; every turn after it is discarded. */
  rewriteMessage: (id: string, messageSeq: number, text: string) =>
    request<Session>(`/api/sessions/${id}/rewrite`, {
      method: "POST",
      body: JSON.stringify({ message_seq: messageSeq, text }),
    }),

  /** Branch a new session at one reader message; the original is untouched. */
  forkSession: (id: string, messageSeq: number, text?: string) =>
    request<Session>(`/api/sessions/${id}/fork`, {
      method: "POST",
      body: JSON.stringify({ message_seq: messageSeq, text }),
    }),

  /** Forget a session: the live run, its session file on disk, or both. */
  deleteSession: (id: string) =>
    request<{ id: string; deleted_live: boolean; deleted_file: string | null }>(
      `/api/sessions/${id}`,
      { method: "DELETE" },
    ),

  saveSession: (id: string) =>
    request<{ id: string; saved_path: string }>(`/api/sessions/${id}/save`, { method: "POST" }),
};
