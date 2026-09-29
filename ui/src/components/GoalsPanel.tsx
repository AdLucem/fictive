import type { GoalNode, GoalsState } from "../types";

interface Props {
  goals: GoalsState;
}

const RECENT_EVENTS = 8;

function GoalRow({ goal, depth }: { goal: GoalNode; depth: number }) {
  const closed = goal.status === "done" || goal.status === "failed" || goal.status === "abandoned";
  return (
    <li className="goal" style={{ paddingLeft: depth === 0 ? 0 : 14 }}>
      <div className={`goal__card${goal.focus ? " frame--working" : ""}${closed ? " goal__card--closed" : ""}`}>
        <div className="goal__head">
          <span className={`goal__status goal__status--${goal.status}`}>{goal.status}</span>
          <span className="goal__id">{goal.id}</span>
          <span style={{ flexGrow: 1 }} />
          {goal.turn_budget ? (
            <span className="goal__meta">
              {goal.turns}/{goal.turn_budget} turns
            </span>
          ) : null}
          {goal.source === "planner" ? <span className="goal__meta">planner</span> : null}
        </div>
        <span className="goal__text">{goal.text}</span>
        {goal.criteria ? <span className="goal__criteria">Done when: {goal.criteria}</span> : null}
        {goal.notes.length > 0 ? (
          <details className="goal__notes">
            <summary>
              {goal.notes.length} note{goal.notes.length === 1 ? "" : "s"}
            </summary>
            <ul>
              {goal.notes.map((note, index) => (
                <li key={index}>
                  <span className="goal__meta">t{note.turn}</span> {note.text}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>
      {goal.children.length > 0 ? (
        <ul className="goal__children">
          {goal.children.map((child) => (
            <GoalRow key={child.id} goal={child} depth={depth + 1} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function GoalsPanel({ goals }: Props) {
  const recent = goals.events.slice(-RECENT_EVENTS).reverse();
  return (
    <section>
      <h3 className="section__title">
        Scene goals · turn {goals.turn}
        {goals.focus ? ` · focus ${goals.focus}` : " · all closed"}
      </h3>
      <ul className="goal-tree">
        <GoalRow goal={goals.root} depth={0} />
      </ul>
      {recent.length > 0 ? (
        <details className="goal-events">
          <summary>Recent goal events</summary>
          <ul>
            {recent.map((event, index) => (
              <li key={index}>
                <span className="goal__meta">
                  t{event.turn} {event.kind}
                  {event.goal ? ` ${event.goal}` : ""}
                </span>{" "}
                {event.text}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}
