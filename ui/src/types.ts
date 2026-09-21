/** Mirrors the JSON the backend serves from `fictive/web/chat.py`. */

export type NodeKind = "message" | "flow" | "step";

export interface MessageNode {
  kind: "message";
  seq: number;
  actor: string;
  role: "user" | "assistant";
  text: string;
  command: string;
  step: number | null;
  depth: 0;
}

export interface StepNode {
  kind: "step";
  seq: number;
  actor: string;
  command: string;
  depth: number;
  detail: string;
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
  turn_count: number;
  exit_message: string | null;
  error: string | null;
  saved_path: string | null;
  turns: TranscriptNode[];
  store: StoreRow[];
  step_pointers: Record<string, number>;
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
