import { useMemo, useState } from "react";
import type { Scenario, SessionsIndex } from "../types";
import { Lighthouse, Plus, Search } from "./icons";

interface Props {
  scenario: Scenario | null;
  index: SessionsIndex | null;
  currentId: string | null;
  busy: boolean;
  onNew: () => void;
  onOpen: (id: string) => void;
  onResume: (savedId: string) => void;
}

export function SessionsRail({ scenario, index, currentId, busy, onNew, onOpen, onResume }: Props) {
  const [query, setQuery] = useState("");

  const live = useMemo(() => {
    const rows = index?.live ?? [];
    const needle = query.trim().toLowerCase();
    return needle ? rows.filter((row) => row.title.toLowerCase().includes(needle)) : rows;
  }, [index, query]);

  const saved = useMemo(() => {
    const liveIds = new Set((index?.live ?? []).map((row) => row.id));
    return (index?.saved ?? []).filter((row) => !liveIds.has(row.id));
  }, [index]);

  return (
    <aside className="rail">
      <div className="rail__head">
        <div className="rail__brand">
          <span style={{ color: "var(--primary)", display: "flex" }}>
            <Lighthouse />
          </span>
          fictive
        </div>

        <button type="button" className="fab state-layer" onClick={onNew} disabled={busy}>
          <Plus />
          New session
        </button>

        <div className="searchbar">
          <span style={{ color: "var(--on-surface-variant)", display: "flex" }}>
            <Search />
          </span>
          <label className="vh" htmlFor="session-search">
            Search sessions
          </label>
          <input
            id="session-search"
            type="search"
            placeholder="Search sessions"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
      </div>

      <nav className="rail__list" aria-label="Sessions">
        <h2 className="rail__group">This run</h2>
        {live.length === 0 ? (
          <p className="rail__empty">No sessions yet. Start one and the scenario opens on its first turn.</p>
        ) : (
          live.map((row) => (
            <button
              type="button"
              key={row.id}
              className={`session-item state-layer${row.id === currentId ? " session-item--active" : ""}`}
              onClick={() => onOpen(row.id)}
            >
              <span className="session-item__title">{row.title}</span>
              <span className="session-item__meta">
                {row.main_actor} · {row.turn_count} turn{row.turn_count === 1 ? "" : "s"} ·{" "}
                {row.status.replace("_", " ")}
              </span>
            </button>
          ))
        )}

        {saved.length > 0 ? (
          <>
            <h2 className="rail__group">Saved on disk</h2>
            {saved.map((row) => (
              <button
                type="button"
                key={row.id}
                className="session-item state-layer"
                onClick={() => onResume(row.id)}
                disabled={busy}
              >
                <span className="session-item__title">{row.id}</span>
                <span className="session-item__meta">
                  {row.unreadable
                    ? "unreadable session file"
                    : `${row.actors.length} actors · resumes at ${(row.callstack ?? []).join(" › ") || "—"}`}
                </span>
              </button>
            ))}
          </>
        ) : null}
      </nav>

      <div className="rail__foot">
        scenario <span style={{ color: "var(--primary)" }}>{scenario?.name ?? "…"}</span>
        <br />
        {scenario ? `${scenario.actors.length} actors · ${scenario.pipeline ?? "pipeline"}` : ""}
      </div>
    </aside>
  );
}
