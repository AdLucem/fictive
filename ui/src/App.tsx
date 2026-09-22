import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { Scenario, Session, SessionsIndex } from "./types";
import { Composer } from "./components/Composer";
import { Inspector } from "./components/Inspector";
import { SessionsRail } from "./components/SessionsRail";
import { Transcript } from "./components/Transcript";
import { Save, Stack } from "./components/icons";

interface Toast {
  text: string;
  tone: "info" | "error";
}

export default function App() {
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [index, setIndex] = useState<SessionsIndex | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [busy, setBusy] = useState(false);
  const [booting, setBooting] = useState(true);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [toast, setToast] = useState<Toast | null>(null);

  const refreshIndex = useCallback(async () => {
    try {
      setIndex(await api.sessions());
    } catch (error) {
      setToast({ text: (error as Error).message, tone: "error" });
    }
  }, []);

  // The first turn of a new session runs the scenario's opening `generate`,
  // so the backend answers once the scenario is waiting for the reader.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const loaded = await api.scenario();
        if (cancelled) return;
        setScenario(loaded);
        const started = await api.createSession();
        if (cancelled) return;
        setSession(started);
        await refreshIndex();
      } catch (error) {
        if (!cancelled) setToast({ text: (error as Error).message, tone: "error" });
      } finally {
        if (!cancelled) setBooting(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshIndex]);

  const run = useCallback(
    async (work: () => Promise<Session>) => {
      setBusy(true);
      try {
        setSession(await work());
        await refreshIndex();
      } catch (error) {
        setToast({ text: (error as Error).message, tone: "error" });
      } finally {
        setBusy(false);
      }
    },
    [refreshIndex],
  );

  const onSend = (text: string) => {
    if (!session) return;
    void run(() => api.sendMessage(session.id, text));
  };

  /** Replace a reader message in place; the turns after it are discarded. */
  const onRewrite = (messageSeq: number, text: string) => {
    if (!session) return;
    void run(() => api.rewriteMessage(session.id, messageSeq, text));
  };

  /** Branch at a reader message. The response is the fork, so the view follows
   *  it -- the original stays in the rail, one click away. */
  const onFork = (messageSeq: number, text: string) => {
    if (!session) return;
    const from = session.id;
    void run(async () => {
      const fork = await api.forkSession(from, messageSeq, text);
      setToast({ text: `Forked ${from} into ${fork.id}`, tone: "info" });
      return fork;
    });
  };

  const onNew = () => void run(() => api.createSession());

  const onOpen = (id: string) => void run(() => api.session(id));

  const onResume = (savedId: string) =>
    void run(() => api.createSession({ load_session_id: savedId }));

  const onSave = async () => {
    if (!session) return;
    setBusy(true);
    try {
      const result = await api.saveSession(session.id);
      setSession(await api.session(session.id));
      setToast({ text: `Session saved to ${result.saved_path}`, tone: "info" });
      await refreshIndex();
    } catch (error) {
      setToast({ text: (error as Error).message, tone: "error" });
    } finally {
      setBusy(false);
    }
  };

  if (booting) {
    return (
      <div className="centered">
        <span className="status status--running">
          <span className="status__dot" />
          starting the scenario
        </span>
      </div>
    );
  }

  if (!session) {
    return (
      <div className="centered">
        <p>No session. Is the backend running?</p>
        <p className="note">python -m fictive.web --scenario examples/ui_demo/scenario</p>
        {toast ? <p className="note">{toast.text}</p> : null}
      </div>
    );
  }

  return (
    <div className="app">
      <SessionsRail
        scenario={scenario}
        index={index}
        currentId={session.id}
        busy={busy}
        onNew={onNew}
        onOpen={onOpen}
        onResume={onResume}
      />

      <main className="main">
        <header className="appbar">
          <h1 className="appbar__title">{session.title}</h1>
          <span className="chip-outline">
            main actor <b>{session.main_actor}</b>
          </span>
          {session.forked_from ? (
            <span className="chip-outline">
              forked from <b>{session.forked_from}</b>
            </span>
          ) : null}
          {busy ? (
            <span className="status status--running">
              <span className="status__dot" />
              running
            </span>
          ) : null}
          <span style={{ flexGrow: 1 }} />
          <button
            type="button"
            className="button-outlined state-layer"
            aria-pressed={inspectorOpen}
            onClick={() => setInspectorOpen((open) => !open)}
          >
            Store &amp; call stack
          </button>
          <button
            type="button"
            className="icon-button state-layer"
            aria-label="Save session"
            onClick={onSave}
            disabled={busy}
          >
            <Save />
          </button>
          <button type="button" className="icon-button state-layer" aria-label="Scenario actors" disabled>
            <Stack />
          </button>
        </header>

        <Transcript session={session} busy={busy} onRewrite={onRewrite} onFork={onFork} />

        {toast ? (
          <div className={`snackbar${toast.tone === "error" ? " snackbar--error" : ""}`} role="status">
            <span>{toast.text}</span>
            <button type="button" className="snackbar__action" onClick={() => setToast(null)}>
              Dismiss
            </button>
          </div>
        ) : null}

        <Composer session={session} busy={busy} onSend={onSend} />
      </main>

      {inspectorOpen ? (
        <Inspector session={session} busy={busy} onClose={() => setInspectorOpen(false)} onSave={onSave} />
      ) : null}
    </div>
  );
}
