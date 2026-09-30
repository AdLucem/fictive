/** Mirrors the JSON the backend serves from `fictive/web/chat.py`. */

export type NodeKind = "message" | "flow" | "step";

/**
 * How the transcript is drawn. `dev` shows every command and called actor;
 * `live` shows only the reader's turns and the replies the flow chose to show
 * with `show_reply`. A view setting only: the backend runs the same either way.
 */
export type ViewMode = "dev" | "live";

/** The colour scheme: Material dark, or the woodland light scheme. */
export type Theme = "dark" | "light";

export interface MessageNode {
  kind: "message";
  seq: number;
  actor: string;
  role: "user" | "assistant";
  text: string;
  command: string;
  step: number | null;
  depth: 0;
  /** True once the flow showed this reply with `show_reply`; live mode draws only these. */
  shown: boolean;
}

export interface StepNode {
  kind: "step";
  seq: number;
  actor: string;
  command: string;
  depth: number;
  detail: string;
  /**
   * The whole text the command was handed, where naming it is not enough: a
   * `system`'s resolved prompt, or what an `input-from` put into the actor.
   * `detail` stays the one-line label the collapsed row shows.
   */
  detail_text: string | null;
  text: string | null;
  step: number | null;
  error: string | null;
}

export interface FlowNode {
  kind: "flow";
  seq: number;
  actor: string;
  command: string;
  /** Position on the interpreter callstack: L1 is a frame the main actor opened. */
  depth: number;
  store: string | null;
  status: "running" | "returned" | "failed";
  returned: string | null;
  error: string | null;
  command_count: number;
  nested_count: number;
  children: TranscriptNode[];
}

export type TranscriptNode = MessageNode | StepNode | FlowNode;

export interface StoreRow {
  name: string;
  type: string;
  value: string;
  assigned: boolean;
  waiting_on: string | null;
}

/** One message exactly as an actor's history holds it, unmerged. */
export interface HistoryMessage {
  role: string;
  content: string;
}

/** One actor's full history: what the actor holds, not what the flow logged. */
export interface ActorHistory {
  name: string;
  type: string;
  messages: HistoryMessage[];
}

export interface ScenarioActor {
  name: string;
  type: string;
  commands: number;
}

export interface Scenario {
  name: string;
  dir: string;
  main_actor: string;
  actors: ScenarioActor[];
  pipeline?: string;
  storage_dir?: string;
  conversations_dir?: string;
}

export interface WaitState {
  /** True while the runtime's `wait` is still running down. */
  active: boolean;
  /** Seconds left at the moment the backend built this response. */
  remaining: number;
  /** Seconds the `wait` command asked for. */
  total: number;
}

export type GoalStatus = "pending" | "active" | "done" | "failed" | "abandoned";

export interface GoalNote {
  turn: number;
  text: string;
}

/** One goal in the scene's goal tree (`fictive/goals.py`), children nested. */
export interface GoalNode {
  id: string;
  text: string;
  criteria: string | null;
  status: GoalStatus;
  source: "flow" | "planner";
  turns: number;
  turn_budget: number | null;
  complete_with_children: boolean;
  notes: GoalNote[];
  /** The deepest open goal: the one the scene is pursuing now. */
  focus: boolean;
  children: GoalNode[];
}

export interface GoalEvent {
  turn: number;
  goal: string | null;
  kind: string;
  text: string;
}

export interface GoalsState {
  turn: number;
  focus: string | null;
  root: GoalNode;
  /** Most recent events, oldest first. */
  events: GoalEvent[];
}

export interface Session {
  id: string;
  title: string;
  status: "new" | "running" | "awaiting_input" | "finished" | "error";
  scenario: Scenario;
  main_actor: string;
  working_actor: string | null;
  callstack: string[];
  waiting_prompt: string | null;
  awaiting_input: boolean;
  /**
   * Seconds until the flow's pending request gives up waiting for the reader,
   * or null when it waits indefinitely. The app posts to the timeout route
   * when it reaches zero.
   */
  input_timeout: number | null;
  turn_count: number;
  exit_message: string | null;
  error: string | null;
  saved_path: string | null;
  resumed_from: string | null;
  forked_from: string | null;
  forked_at: number | null;
  /**
   * The `seq` of every reader message that can be rewritten or forked from.
   * Session-level rather than a flag per node: it reflects the checkpoints the
   * backend still holds, so a resumed session's messages are real messages with
   * nothing to branch at.
   */
  branch_points: number[];
  turns: TranscriptNode[];
  /** Every actor's history, main actor first; what the actor picker shows. */
  histories: ActorHistory[];
  store: StoreRow[];
  /** The scene's goal tree, or null when the flow sets no goals. */
  goals: GoalsState | null;
  step_pointers: Record<string, number>;
  /**
   * Wait mode. The backend sends seconds remaining rather than a deadline, so
   * the browser counts down from that reading and no clock skew can shift it.
   */
  wait: WaitState;
}

export interface LiveSessionRow {
  id: string;
  title: string;
  status: string;
  turn_count: number;
  main_actor: string;
  saved_path: string | null;
  live: true;
}

export interface SavedSessionRow {
  id: string;
  path: string;
  saved_at: number;
  actors: string[];
  callstack?: string[];
  live: boolean;
  unreadable?: boolean;
}

export interface SessionsIndex {
  live: LiveSessionRow[];
  saved: SavedSessionRow[];
}
