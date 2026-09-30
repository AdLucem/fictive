import { useMemo, useState } from "react";
import type { Scenario, SessionsIndex, Theme, ViewMode } from "../types";
import { Lighthouse, Plus, Search, Trash } from "./icons";

interface Props {
  scenario: Scenario | null;
  index: SessionsIndex | null;
  currentId: string | null;
  busy: boolean;
  onNew: () => void;
  onOpen: (id: string) => void;
  onResume: (savedId: string) => void;
  onDelete: (id: string) => void;
  mode: ViewMode;
  onModeChange: (mode: ViewMode) => void;
  theme: Theme;
  onThemeChange: (theme: Theme) => void;
}

const MODES: { value: ViewMode; label: string; hint: string }[] = [
  { value: "dev", label: "Dev", hint: "Every command and called actor, inline." },
  { value: "live", label: "Live", hint: "Only your turns and the replies the flow shows." },
];

const THEMES: { value: Theme; label: string }[] = [
  { value: "dark", label: "Dark" },
  { value: "light", label: "Light" },
];

interface RowProps {
  title: string;
  meta: string;
  active: boolean;
  busy: boolean;
  /** Opening a saved session runs the scenario, so that one waits on a turn. */
  selectDisabled: boolean;
  /** Whether the row is a confirmation away from being deleted. */
  confirming: boolean;
  /** What deleting this row actually removes, said plainly before it happens. */
  confirmNote: string;
  onSelect: () => void;
  onAskDelete: () => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
}

/**
 * One session in the rail, live or saved.
 *
 * A row is a button, so the delete affordance cannot be nested inside it: the
 * two sit side by side in a group, and the trash icon only appears on hover or
 * keyboard focus, the same way the rewrite and fork actions do on a message.
 *
 * Deleting takes a second click, in the row itself rather than in a modal. The
 * call removes a file from disk and cannot be undone, and the row is small and
 * sits right beside the one being read, so a stray click is exactly the mistake
 * worth making impossible.
 */
function SessionRow({
  title,
  meta,
  active,
  busy,
  selectDisabled,
  confirming,
  confirmNote,
  onSelect,
  onAskDelete,
  onCancelDelete,
  onConfirmDelete,
}: RowProps) {
  if (confirming) {
    return (
      <div className="session-row session-row--confirming">
        <div className="session-confirm">
          <span className="session-confirm__question">Delete this session?</span>
          <span className="session-confirm__note">{confirmNote}</span>
          <div className="session-confirm__actions">
            <button type="button" className="button-text" onClick={onCancelDelete}>
              Cancel
            </button>
            <button
              type="button"
              className="session-confirm__delete"
              onClick={onConfirmDelete}
              disabled={busy}
            >
              Delete
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="session-row">
      <button
        type="button"
        className={`session-item state-layer${active ? " session-item--active" : ""}`}
        onClick={onSelect}
        disabled={selectDisabled}
      >
        <span className="session-item__title">{title}</span>
        <span className="session-item__meta">{meta}</span>
      </button>
      <button
        type="button"
        className="session-delete"
        aria-label={`Delete session ${title}`}
        title="Delete this session"
        onClick={onAskDelete}
        disabled={busy}
      >
        <Trash />
      </button>
    </div>
  );
}

export function SessionsRail({
  scenario,
  index,
  currentId,
  busy,
  onNew,
  onOpen,
  onResume,
  onDelete,
  mode,
  onModeChange,
  theme,
  onThemeChange,
}: Props) {
  const [query, setQuery] = useState("");
  // At most one row is ever asking to be confirmed, so this is the id rather
  // than a set: opening a second confirmation closes the first, which is also
  // the behaviour that keeps the rail from filling up with open questions.
  const [confirming, setConfirming] = useState<string | null>(null);

  const live = useMemo(() => {
    const rows = index?.live ?? [];
    const needle = query.trim().toLowerCase();
    return needle ? rows.filter((row) => row.title.toLowerCase().includes(needle)) : rows;
  }, [index, query]);

  const saved = useMemo(() => {
    const liveIds = new Set((index?.live ?? []).map((row) => row.id));
    return (index?.saved ?? []).filter((row) => !liveIds.has(row.id));
  }, [index]);

  const confirmDelete = (id: string) => {
    setConfirming(null);
    onDelete(id);
  };

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
            <SessionRow
              key={row.id}
              title={row.title}
              meta={`${row.main_actor} · ${row.turn_count} turn${
                row.turn_count === 1 ? "" : "s"
              } · ${row.status.replace("_", " ")}`}
              active={row.id === currentId}
              busy={busy}
              selectDisabled={false}
              confirming={confirming === row.id}
              confirmNote={
                row.saved_path
                  ? "The run and the session file it was saved to both go, for good."
                  : "This run goes, for good. It was never saved to disk."
              }
              onSelect={() => onOpen(row.id)}
              onAskDelete={() => setConfirming(row.id)}
              onCancelDelete={() => setConfirming(null)}
              onConfirmDelete={() => confirmDelete(row.id)}
            />
          ))
        )}

        {saved.length > 0 ? (
          <>
            <h2 className="rail__group">Saved on disk</h2>
            {saved.map((row) => (
              <SessionRow
                key={row.id}
                title={row.id}
                meta={
                  row.unreadable
                    ? "unreadable session file"
                    : `${row.actors.length} actors · resumes at ${
                        (row.callstack ?? []).join(" › ") || "—"
                      }`
                }
                active={false}
                busy={busy}
                selectDisabled={busy}
                confirming={confirming === row.id}
                confirmNote="The session file is removed from disk, for good."
                onSelect={() => onResume(row.id)}
                onAskDelete={() => setConfirming(row.id)}
                onCancelDelete={() => setConfirming(null)}
                onConfirmDelete={() => confirmDelete(row.id)}
              />
            ))}
          </>
        ) : null}
      </nav>

      <section className="settings" aria-labelledby="settings-title">
        <h2 id="settings-title" className="rail__group settings__title">
          Settings
        </h2>
        <div className="segmented" role="radiogroup" aria-label="View mode">
          {MODES.map((option) => (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={mode === option.value}
              className="segmented__option state-layer"
              onClick={() => onModeChange(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <p className="settings__hint">{MODES.find((option) => option.value === mode)?.hint}</p>
        <div className="segmented settings__theme" role="radiogroup" aria-label="Theme">
          {THEMES.map((option) => (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={theme === option.value}
              className="segmented__option state-layer"
              onClick={() => onThemeChange(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </section>

      <div className="rail__foot">
        scenario <span style={{ color: "var(--primary)" }}>{scenario?.name ?? "…"}</span>
        <br />
        {scenario ? `${scenario.actors.length} actors · ${scenario.pipeline ?? "pipeline"}` : ""}
      </div>
    </aside>
  );
}
