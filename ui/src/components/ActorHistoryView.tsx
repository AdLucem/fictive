/**
 * One actor's full history, drawn in the chat window in the transcript's own
 * shapes: incoming turns as bubbles, the actor's replies as prose under its
 * name, and a system prompt as the collapsible block a `system` step shows.
 *
 * This is what the actor holds, message for message, so it includes turns the
 * transcript never logged -- anything a flow appended by hand -- and none of
 * the commands. Read-only: rewriting and forking belong to the main chat.
 */

import { useEffect, useRef, useState } from "react";
import type { ActorHistory, HistoryMessage } from "../types";
import { Chevron } from "./icons";

function sizeLabel(text: string) {
  const trimmed = text.trim();
  const words = trimmed ? trimmed.split(/\s+/).length : 0;
  return `${words} word${words === 1 ? "" : "s"}`;
}

/** A system prompt, or any role that is neither side of the conversation. */
function Block({ message, index }: { message: HistoryMessage; index: number }) {
  const [open, setOpen] = useState(message.role !== "system");
  return (
    <div className="history-block">
      <div className="step">
        <span className="step__command">
          #{index} {message.role}
        </span>
        <button
          type="button"
          className={`step__disclosure${open ? " step__disclosure--open" : ""}`}
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          <Chevron className="step__chevron" />
          <span className="step__detail">{message.role === "system" ? "system prompt" : message.role}</span>
          <span className="step__size">{sizeLabel(message.content)}</span>
        </button>
      </div>
      {open ? (
        <div className="step__detail-text" style={{ background: "var(--level-2)" }}>
          {message.content}
        </div>
      ) : null}
    </div>
  );
}

interface Props {
  history: ActorHistory;
  mainActor: string;
  busy: boolean;
}

export function ActorHistoryView({ history, mainActor, busy }: Props) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [history.name, history.messages.length, busy]);

  return (
    <div className="transcript">
      <div className="transcript__inner">
        <div className="history-head">
          <span className="speaker__name">history of</span>
          <span className="flow__actor">{history.name}</span>
          <span className="speaker__meta">
            {history.type}
            {history.name === mainActor ? " · main actor" : ""} · {history.messages.length} message
            {history.messages.length === 1 ? "" : "s"}
          </span>
        </div>

        {history.messages.length === 0 ? (
          <p className="note">This actor's history is empty.</p>
        ) : null}

        {history.messages.map((message, index) =>
          message.role === "user" ? (
            <div className="bubble-row" key={index}>
              <div className="bubble">{message.content}</div>
            </div>
          ) : message.role === "assistant" ? (
            <div key={index}>
              <div className="speaker">
                <span className="speaker__avatar">{history.name.slice(0, 1)}</span>
                <span className="speaker__name">{history.name}</span>
                <span className="speaker__meta">#{index}</span>
              </div>
              <div className="prose">{message.content}</div>
            </div>
          ) : (
            <Block key={index} message={message} index={index} />
          ),
        )}

        {busy ? (
          <div className="speaker" aria-live="polite">
            <span className="status status--running">
              <span className="status__dot" />
              {mainActor} is running the turn
            </span>
          </div>
        ) : null}

        <div ref={endRef} />
      </div>
    </div>
  );
}
