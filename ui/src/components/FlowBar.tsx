import { useState } from "react";
import type { FlowNode, StepNode, TranscriptNode } from "../types";
import { Arrow, Bang, Check, Chevron, Lines } from "./icons";

/** Frames deeper than this are counted and named, not drawn. */
export const MAX_RENDER_DEPTH = 5;

const toneFor = (depth: number) => `var(--level-${Math.min(Math.max(depth, 1), 5)})`;

function hiddenBelow(node: FlowNode): { names: string[]; total: number } {
  const names: string[] = [];
  let total = 0;
  const walk = (children: TranscriptNode[], top: boolean) => {
    for (const child of children) {
      if (child.kind !== "flow") continue;
      total += 1;
      if (top) names.push(child.actor);
      walk(child.children, false);
    }
  };
  walk(node.children, true);
  return { names, total };
}

function Status({ node }: { node: FlowNode }) {
  if (node.status === "running") {
    return (
      <span className="status status--running">
        <span className="status__dot" />
        running
      </span>
    );
  }
  if (node.status === "failed") {
    return (
      <span className="status status--failed">
        <Bang />
        failed
      </span>
    );
  }
  return (
    <span className="status status--returned">
      <Check />
      <span className="status__label">
        {node.returned ? `returned ${shorten(node.returned)}` : "returned"}
      </span>
    </span>
  );
}

function shorten(value: string, limit = 14) {
  const oneLine = value.replace(/\s+/g, " ").trim();
  return oneLine.length > limit ? `${oneLine.slice(0, limit)}…` : oneLine;
}

export function Step({ node, depth }: { node: StepNode; depth: number }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div className="step">
        <span className="step__command">{node.command}</span>
        <span className="step__detail">{node.detail}</span>
      </div>
      {node.text ? (
        <div className="step__text" style={{ background: toneFor(depth + 1) }}>
          {node.text}
        </div>
      ) : null}
      {node.error ? <div className="step__error">{node.error}</div> : null}
    </div>
  );
}

function DepthStub({ node }: { node: FlowNode }) {
  const { names, total } = hiddenBelow(node);
  if (total === 0) return null;
  return (
    <div className="depth-stub">
      <Lines />
      <span>
        {total} further {total === 1 ? "flow" : "flows"} below depth {MAX_RENDER_DEPTH} — not drawn.{" "}
        <span className="depth-stub__names">{names.join(", ")}</span>
      </span>
    </div>
  );
}

/**
 * One `run-actor` frame. Depth is the frame's position on the interpreter
 * callstack, and it is carried three ways: tonal elevation, the spine, and the
 * chip — a bar can be scrolled away from its parent.
 */
export function FlowBar({ node }: { node: FlowNode }) {
  const producedProse = node.children.some((child) => child.kind === "step" && child.text);
  const [open, setOpen] = useState(node.depth === 1 && producedProse);
  const atDepthLimit = node.depth >= MAX_RENDER_DEPTH;

  const visibleChildren = node.children.filter(
    (child) => !(child.kind === "flow" && atDepthLimit),
  );

  return (
    <div
      className={`flow${open ? " flow--open" : ""}${node.depth > 1 ? " flow--nested" : ""}`}
      style={{ background: toneFor(node.depth) }}
    >
      <button
        type="button"
        className="flow__header state-layer"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <Chevron className="flow__chevron" />
        <span className="flow__command">{node.command}</span>
        <span className="flow__actor">{node.actor}</span>
        {node.store ? (
          <>
            <Arrow />
            <span className="var-chip">{node.store}</span>
          </>
        ) : null}
        <span className="flow__spacer" />
        {/* The deepest drawn frame is also the narrowest, and the stub row in
            its body already says what it holds — so the weight line comes off
            rather than pushing the status chip past the card edge. */}
        {atDepthLimit ? null : (
          <span className="flow__weight">
            {node.command_count} command{node.command_count === 1 ? "" : "s"}
            {node.nested_count > 0 ? ` · ${node.nested_count} nested` : ""}
          </span>
        )}
        <span className="flow__depth">L{node.depth}</span>
        <Status node={node} />
      </button>

      {open ? (
        <div className="flow__body">
          {visibleChildren.map((child) =>
            child.kind === "flow" ? (
              <div className="flow__spine" key={child.seq}>
                <FlowBar node={child} />
              </div>
            ) : child.kind === "step" ? (
              <Step key={child.seq} node={child} depth={node.depth} />
            ) : (
              <div className="prose" key={child.seq}>
                {child.text}
              </div>
            ),
          )}
          {atDepthLimit ? <DepthStub node={node} /> : null}
          {node.error ? <div className="step__error">{node.error}</div> : null}
        </div>
      ) : null}
    </div>
  );
}
