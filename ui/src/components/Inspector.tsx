import type { Session } from "../types";
import { Close } from "./icons";
import { GoalsPanel } from "./GoalsPanel";

interface Props {
  session: Session;
  busy: boolean;
  onClose: () => void;
  onSave: () => void;
}

export function Inspector({ session, busy, onClose, onSave }: Props) {
  return (
    <aside className="inspector">
      <div className="inspector__head">
        <h2>{session.goals ? "Goals, store & call stack" : "Store & call stack"}</h2>
        <span style={{ flexGrow: 1 }} />
        <button type="button" className="icon-button state-layer" aria-label="Close inspector" onClick={onClose}>
          <Close />
        </button>
      </div>

      <div className="inspector__body">
        {session.goals ? <GoalsPanel goals={session.goals} /> : null}

        <section>
          <h3 className="section__title">
            Call stack · {session.callstack.length} frame{session.callstack.length === 1 ? "" : "s"}
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {session.callstack.map((actor, index) => (
              <div
                key={`${actor}-${index}`}
                style={{
                  paddingLeft: index === 0 ? 0 : 16,
                  borderLeft: index === 0 ? "none" : "1px solid var(--outline-variant)",
                }}
              >
                <div
                  className={`frame${index === session.callstack.length - 1 ? " frame--working" : ""}`}
                  style={{ background: `var(--level-${Math.min(index + 1, 5)})` }}
                >
                  <span className="frame__depth">L{index}</span>
                  <span className="frame__name">{actor}</span>
                  <span className="frame__meta">step {session.step_pointers[actor] ?? "?"}</span>
                </div>
              </div>
            ))}
          </div>
          <p className="note">The deepest frame is the actor that currently holds control.</p>
        </section>

        <section>
          <h3 className="section__title">Store · {session.store.filter((row) => row.assigned).length} assigned</h3>
          <div className="store-table">
            {session.store.length === 0 ? (
              <div className="store-row">
                <span className="store-row__value">Nothing assigned yet.</span>
              </div>
            ) : (
              session.store.map((row) => (
                <div className="store-row" key={row.name}>
                  <div className="store-row__head">
                    <span className="store-row__name">{row.name}</span>
                    <span className="store-row__type">{row.type}</span>
                    <span style={{ flexGrow: 1 }} />
                    {row.assigned ? null : <span className="store-row__pending">waiting on {row.waiting_on}</span>}
                  </div>
                  {row.assigned ? <span className="store-row__value">{row.value}</span> : null}
                </div>
              ))
            )}
          </div>
        </section>

        <section>
          <h3 className="section__title">Session file</h3>
          <div className="file-card">
            <div className="file-card__row">
              <span className="file-card__label">id</span>
              <span className="file-card__value">{session.id}</span>
            </div>
            <div className="file-card__row">
              <span className="file-card__label">path</span>
              <span className="file-card__value">{session.saved_path ?? "not saved yet"}</span>
            </div>
            <div className="file-card__row">
              <span className="file-card__label">scenario</span>
              <span className="file-card__value">{session.scenario.name}</span>
            </div>
            <div style={{ display: "flex", gap: 10, marginTop: 4 }}>
              <button type="button" className="button-filled state-layer" onClick={onSave} disabled={busy}>
                Save now
              </button>
            </div>
          </div>
          <p className="note">
            A session file holds every actor's history, the store and the callstack — not this flow tree, which is
            recorded as the steps run.
          </p>
        </section>
      </div>
    </aside>
  );
}
