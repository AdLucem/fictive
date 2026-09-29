import { useEffect, useMemo, useRef } from "react";
import type { MessageNode, Session, TranscriptNode, ViewMode } from "../types";
import { FlowBar, Step } from "./FlowBar";
import { ReaderMessage } from "./ReaderMessage";

function Message({ node, mainActor }: { node: MessageNode; mainActor: string }) {
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

/**
 * What live mode draws: the reader's turns and every reply marked `shown`.
 * The backend puts shown replies at the top level, but a flow's children are
 * searched too so nothing the flow chose to show can be lost inside a bar.
 */
function liveTurns(nodes: TranscriptNode[]): MessageNode[] {
  const out: MessageNode[] = [];
  for (const node of nodes) {
    if (node.kind === "message") {
      if (node.role === "user" || node.shown) out.push(node);
    } else if (node.kind === "flow") {
      out.push(...liveTurns(node.children));
    }
  }
  return out;
}

interface Props {
  session: Session;
  mode: ViewMode;
  busy: boolean;
  onRewrite: (messageSeq: number, text: string) => void;
  onFork: (messageSeq: number, text: string) => void;
}

export function Transcript({ session, mode, busy, onRewrite, onFork }: Props) {
  const endRef = useRef<HTMLDivElement>(null);

  const turns = useMemo(
    () => (mode === "live" ? liveTurns(session.turns) : session.turns),
    [mode, session.turns],
  );

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length, busy]);

  const branchable = useMemo(() => new Set(session.branch_points), [session.branch_points]);

  // How many reader messages come after each one: what a rewrite there would
  // discard, and so which of rewrite and fork the reader actually wants.
  const laterMessages = useMemo(() => {
    const counts = new Map<number, number>();
    const readerSeqs = session.turns
      .filter((node): node is MessageNode => node.kind === "message" && node.role === "user")
      .map((node) => node.seq);
    readerSeqs.forEach((seq, index) => counts.set(seq, readerSeqs.length - 1 - index));
    return counts;
  }, [session.turns]);

  return (
    <div className="transcript">
      <div className="transcript__inner">
        {turns.map((node) =>
          node.kind === "message" ? (
            node.role === "user" ? (
              <ReaderMessage
                key={node.seq}
                node={node}
                branchable={branchable.has(node.seq)}
                laterMessages={laterMessages.get(node.seq) ?? 0}
                busy={busy}
                onRewrite={onRewrite}
                onFork={onFork}
              />
            ) : (
              <Message key={node.seq} node={node} mainActor={session.main_actor} />
            )
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
