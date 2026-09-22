/** A reader message, with the two ways of changing one's mind about it.
 *
 * Rewriting runs the same conversation on from that message again, so the turns
 * after it stop existing. Forking leaves this session exactly as it is and
 * starts a second one that shares everything up to the message. Which of the
 * two the reader wants depends entirely on whether the turns after are worth
 * keeping, so the editor says how many there are rather than making them
 * disappear quietly.
 */

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { MessageNode } from "../types";
import { Branch, Pencil } from "./icons";

type Mode = "rewrite" | "fork";

interface Props {
  node: MessageNode;
  /** Whether the backend still holds a checkpoint in front of this message. */
  branchable: boolean;
  /** Reader messages after this one: what a rewrite would discard. */
  laterMessages: number;
  busy: boolean;
  onRewrite: (messageSeq: number, text: string) => void;
  onFork: (messageSeq: number, text: string) => void;
}

export function ReaderMessage({
  node,
  branchable,
  laterMessages,
  busy,
  onRewrite,
  onFork,
}: Props) {
  const [mode, setMode] = useState<Mode | null>(null);
  const [text, setText] = useState(node.text);
  const area = useRef<HTMLTextAreaElement>(null);

  // A rewrite renumbers everything after it, so this component is remounted
  // rather than updated; resetting on the text keeps an open editor honest if
  // the same node is re-rendered with new content.
  useEffect(() => setText(node.text), [node.text]);

  useEffect(() => {
    if (mode) area.current?.focus();
  }, [mode]);

  const open = (next: Mode) => {
    setText(node.text);
    setMode(next);
  };

  const cancel = () => setMode(null);

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    if (mode === "fork") onFork(node.seq, trimmed);
    else onRewrite(node.seq, trimmed);
    setMode(null);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      cancel();
    }
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      submit();
    }
  };

  if (mode) {
    const unchanged = text.trim() === node.text.trim();
    return (
      <div className="bubble-row">
        <div className="rewrite">
          <textarea
            ref={area}
            className="rewrite__field"
            rows={Math.min(10, Math.max(2, text.split("\n").length + 1))}
            value={text}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={onKeyDown}
            aria-label={mode === "fork" ? "Message for the fork" : "Rewrite this message"}
          />
          <p className="rewrite__note">
            {mode === "fork" ? (
              <>Starts a new session from here. This one is left as it is.</>
            ) : laterMessages > 0 ? (
              <>
                Discards {laterMessages} later {laterMessages === 1 ? "turn" : "turns"}. Fork
                instead to keep them.
              </>
            ) : (
              <>Generates a fresh reply to this message.</>
            )}
          </p>
          <div className="rewrite__actions">
            <button type="button" className="button-text" onClick={cancel}>
              Cancel
            </button>
            <button
              type="button"
              className="button-filled"
              onClick={submit}
              disabled={busy || text.trim().length === 0}
              title={unchanged ? "Sends the message again as it stands" : undefined}
            >
              {mode === "fork" ? "Fork" : "Rewrite"}
            </button>
          </div>
          <span className="rewrite__hint">⌘↵ to confirm · esc to cancel</span>
        </div>
      </div>
    );
  }

  return (
    <div className="bubble-row bubble-row--actionable">
      {branchable ? (
        <div className="bubble-actions">
          <button
            type="button"
            className="bubble-action"
            onClick={() => open("rewrite")}
            disabled={busy}
            title={
              laterMessages > 0
                ? `Rewrite, discarding the ${laterMessages} later ${
                    laterMessages === 1 ? "turn" : "turns"
                  }`
                : "Rewrite and generate again"
            }
          >
            <Pencil />
            Rewrite
          </button>
          <button
            type="button"
            className="bubble-action"
            onClick={() => open("fork")}
            disabled={busy}
            title="Branch a new session from this message"
          >
            <Branch />
            Fork
          </button>
        </div>
      ) : null}
      <div className="bubble">{node.text}</div>
    </div>
  );
}
