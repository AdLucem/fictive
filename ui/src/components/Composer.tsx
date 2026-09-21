import { useState, type KeyboardEvent } from "react";
import type { Session } from "../types";
import { Send } from "./icons";

interface Props {
  session: Session;
  busy: boolean;
  onSend: (text: string) => void;
}

export function Composer({ session, busy, onSend }: Props) {
  const [text, setText] = useState("");
  const canSend = session.awaiting_input && !busy && text.trim().length > 0;

  const submit = () => {
    if (!canSend) return;
    onSend(text.trim());
    setText("");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      submit();
    }
  };

  const waitingLabel = session.awaiting_input
    ? session.waiting_prompt
      ? session.waiting_prompt
      : "Answer as the reader…"
    : busy
      ? "Running the turn…"
      : "The scenario is not waiting for input";

  return (
    <div className="composer">
      <div className="composer__inner">
        <div className="composer__field">
          <label className="vh" htmlFor="composer">
            Message {session.main_actor}
          </label>
          <textarea
            id="composer"
            rows={2}
            placeholder={waitingLabel}
            value={text}
            disabled={!session.awaiting_input || busy}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={onKeyDown}
          />
          <button
            type="button"
            className="composer__send"
            aria-label="Send"
            disabled={!canSend}
            onClick={submit}
            style={{ color: canSend ? "var(--on-primary)" : "var(--muted)" }}
          >
            <Send />
          </button>
        </div>
        <div className="composer__hint">
          <span>⌘↵ to send</span>
          <span>
            {session.awaiting_input ? (
              <>
                {session.working_actor} waiting at <b>input-from</b>
                {session.step_pointers[session.working_actor ?? ""] !== undefined
                  ? ` · step ${session.step_pointers[session.working_actor ?? ""]}`
                  : ""}
              </>
            ) : (
              <>callstack {session.callstack.join(" › ") || "empty"}</>
            )}
          </span>
          <span style={{ marginLeft: "auto" }}>
            session {session.id}
            {session.saved_path ? " · saved" : " · unsaved"}
          </span>
        </div>
      </div>
    </div>
  );
}
