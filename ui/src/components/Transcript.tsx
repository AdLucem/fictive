import { useEffect, useRef } from "react";
import type { Session, TranscriptNode } from "../types";
import { FlowBar, Step } from "./FlowBar";

function Message({ node, mainActor }: { node: Extract<TranscriptNode, { kind: "message" }>; mainActor: string }) {
  if (node.role === "user") {
    return (
      <div className="bubble-row">
        <div className="bubble">{node.text}</div>
      </div>
    );
  }
  return (
    <div>
      <div className="speaker">
        <span className="speaker__avatar">{mainActor.slice(0, 1)}</span>
        <span className="speaker__name">{node.actor}</span>
        <span className="speaker__meta">
          {node.command}
          {node.step !== null ? ` · step ${node.step}` : ""}
        </span>
      </div>
      <div className="prose">{node.text}</div>
    </div>
  );
}

export function Transcript({ session, busy }: { session: Session; busy: boolean }) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [session.turns.length, busy]);

  return (
    <div className="transcript">
      <div className="transcript__inner">
        {session.turns.map((node) =>
          node.kind === "message" ? (
            <Message key={node.seq} node={node} mainActor={session.main_actor} />
          ) : node.kind === "flow" ? (
            <FlowBar key={node.seq} node={node} />
          ) : (
            <div key={node.seq} style={{ background: "var(--level-1)", borderRadius: 12, padding: "12px 16px" }}>
              <Step node={node} depth={1} />
            </div>
          ),
        )}

        {busy ? (
          <div className="speaker" aria-live="polite">
            <span className="status status--running">
              <span className="status__dot" />
              {session.main_actor} is running the turn
            </span>
          </div>
        ) : null}

        {session.status === "finished" ? (
          <p className="note">{session.exit_message ?? "The scenario has no further instructions."}</p>
        ) : null}

        <div ref={endRef} />
      </div>
    </div>
  );
}
