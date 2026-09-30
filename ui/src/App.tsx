import { useCallback, useEffect, useLayoutEffect, useState } from "react";
import { api } from "./api";
import type { Scenario, Session, SessionsIndex, Theme, ViewMode } from "./types";
import { ActorHistoryView } from "./components/ActorHistoryView";
import { ActorMenu } from "./components/ActorMenu";
import { Composer } from "./components/Composer";
import { Inspector } from "./components/Inspector";
import { SessionsRail } from "./components/SessionsRail";
import { Transcript } from "./components/Transcript";
import { WaitTimer } from "./components/WaitTimer";
import { Save } from "./components/icons";

const MODE_KEY = "fictive.viewMode";

/** A per-browser preference, so storage that throws or is empty means `dev`. */
function readMode(): ViewMode {
  try {
    return window.localStorage.getItem(MODE_KEY) === "live" ? "live" : "dev";
  } catch {
    return "dev";
  }
}

const THEME_KEY = "fictive.theme";

/** A remembered choice wins; otherwise the browser's own light/dark preference. */
function readTheme(): Theme {
  try {
    const stored = window.localStorage.getItem(THEME_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // Fall through to the system preference.
  }
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

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
  const [mode, setMode] = useState<ViewMode>(readMode);
  const [theme, setTheme] = useState<Theme>(readTheme);
  /** The actor whose history fills the chat window; `null` is the main chat. */
  const [viewActor, setViewActor] = useState<string | null>(null);

  const onModeChange = (next: ViewMode) => {
    setMode(next);
    try {
      window.localStorage.setItem(MODE_KEY, next);
    } catch {
      // Not remembered across reloads; the switch itself still works.
    }
  };

  // Set before paint, so a light-theme reload does not flash the dark scheme.
  useLayoutEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const onThemeChange = (next: Theme) => {
    setTheme(next);
    try {
      window.localStorage.setItem(THEME_KEY, next);
    } catch {
      // Not remembered across reloads; the switch itself still works.
    }
  };

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

  // A timed request (e.g. a punishment wait) is timed out by the backend
  // itself; this post, when the countdown ends, fetches what that turn said
  // (or runs it, if it is due and has not run). The slack keeps the post from
  // arriving ahead of the backend's deadline.
  useEffect(() => {
    if (!session || busy || !session.awaiting_input || session.input_timeout === null) return;
    const id = session.id;
    const timer = window.setTimeout(() => {
      void run(() => api.timeoutInput(id));
    }, session.input_timeout * 1000 + 250);
    return () => window.clearTimeout(timer);
  }, [session, busy, run]);

  // A background tab may have slept through that timer while the backend ran
  // the turn, so coming back to the tab picks up whatever happened meanwhile.
  useEffect(() => {
    if (!session || busy) return;
    const id = session.id;
    const catchUp = () => {
      if (document.visibilityState !== "visible") return;
      api
        .session(id)
        .then((latest) => setSession((current) => (current?.id === id ? latest : current)))
        .catch(() => undefined);
    };
    document.addEventListener("visibilitychange", catchUp);
    window.addEventListener("focus", catchUp);
    return () => {
      document.removeEventListener("visibilitychange", catchUp);
      window.removeEventListener("focus", catchUp);
    };
  }, [session, busy]);

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

  /**
   * Forget a session, and leave the app with something to show.
   *
   * Deleting the open session is the normal case -- it is the one in front of
   * you -- so the view has to land somewhere: the next live session if there is
   * one, and a fresh session if that was the last. Deleting any other row only
   * needs the rail redrawn, and the open session is left exactly as it is.
   */
  const onDelete = (id: string) => {
    setBusy(true);
    void (async () => {
      try {
        const result = await api.deleteSession(id);
        const next = await api.sessions();
        setIndex(next);
        setToast({
          text: result.deleted_file
            ? `Deleted ${id} and its session file`
            : `Deleted ${id}`,
          tone: "info",
        });
        if (session?.id === id) {
          const survivor = next.live.find((row) => row.id !== id);
          setSession(survivor ? await api.session(survivor.id) : await api.createSession());
          if (!survivor) await refreshIndex();
        }
      } catch (error) {
        setToast({ text: (error as Error).message, tone: "error" });
      } finally {
        setBusy(false);
      }
    })();
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

  // Another session need not have the same actor, and a history view that
  // silently showed nothing would read as an empty actor, so it falls back.
  const viewedHistory =
    viewActor === null
      ? null
      : (session.histories ?? []).find((history) => history.name === viewActor) ?? null;

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
        onDelete={onDelete}
        mode={mode}
        onModeChange={onModeChange}
        theme={theme}
        onThemeChange={onThemeChange}
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
          <WaitTimer wait={session.wait} />
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
          <ActorMenu
            histories={session.histories ?? []}
            mainActor={session.main_actor}
            current={viewedHistory ? viewedHistory.name : null}
            onPick={setViewActor}
          />
        </header>

        {viewedHistory ? (
          <ActorHistoryView history={viewedHistory} mainActor={session.main_actor} busy={busy} />
        ) : (
          <Transcript session={session} mode={mode} busy={busy} onRewrite={onRewrite} onFork={onFork} />
        )}

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
