// --- SSE Event Types ---

export interface SSEEvent {
  event?: string;
  data: string;
}

export interface AgentTurnStartEvent {
  agent: string;
  input: string;
}

export interface InferenceStartEvent {
  model: string;
  engine: string;
  turn: number;
}

export interface InferenceEndEvent {
  model: string;
  engine: string;
  turn: number;
}

export interface ToolCallStartEvent {
  tool: string;
  arguments: string;
}

export interface ToolCallEndEvent {
  tool: string;
  success: boolean;
  latency: number;
}

// --- Chat Types ---

export interface ToolCallInfo {
  id: string;
  tool: string;
  arguments: string;
  status: 'running' | 'success' | 'error';
  result?: string;
  latency?: number;
}

export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

export interface MessageTelemetry {
  engine?: string;
  model_id?: string;
  tokens_per_sec?: number;
  ttft_ms?: number;
  total_ms?: number;
  complexity_score?: number;
  complexity_tier?: string;
  suggested_max_tokens?: number;
}

export interface TimeRange {
  start?: string;
  end?: string;
}

export interface ResearchSource {
  ref: number;
  title?: string;
  sender?: string;
  date?: string;
  url?: string;
}

export interface ResearchSearchTrace {
  id: string;
  query: string;
  person?: string;
  timeRange?: TimeRange | string;
  status: 'pending' | 'complete';
  numHits?: number;
  topTitles?: string[];
}

export type ResearchEvent =
  | {
      type: 'search_call';
      arguments: {
        query: string;
        person?: string;
        time_range?: TimeRange | string;
      };
    }
  | {
      type: 'search_result';
      num_hits: number;
      top_titles?: string[];
      sources?: ResearchSource[];
    }
  | { type: 'synthesis'; text: string }
  | {
      type: 'system_metrics';
      power_w: number;
      energy_j: number;
      duration_s: number;
    }
  | { type: 'done'; usage?: TokenUsage }
  | { type: 'error'; message: string };

export interface LiveEnergyMetrics {
  power_w: number;
  energy_j: number;
  duration_s: number;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  toolCalls?: ToolCallInfo[];
  researchTraces?: ResearchSearchTrace[];
  researchSources?: ResearchSource[];
  isResearch?: boolean;
  usage?: TokenUsage;
  telemetry?: MessageTelemetry;
  audio?: { url: string };
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  model: string;
  messages: ChatMessage[];
  /** Codex target selected for this OpenJarvis conversation. */
  codexThreadId?: string;
  codexProjectCwd?: string;
}

export interface CodexThread {
  thread_id: string;
  project_cwd: string;
  project_name: string;
  name: string;
  preview: string;
  status: string | null;
  updated_at: number | null;
}

export interface CodexProject {
  cwd: string;
  name: string;
  threads: CodexThread[];
}

export interface CodexCatalog {
  projects: CodexProject[];
}

export interface CodexHistoryMessage {
  message_id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number | null;
}

export interface CodexThreadHistory {
  thread_id: string;
  messages: CodexHistoryMessage[];
  revision?: string;
  complete?: boolean;
  next_cursor?: string | null;
}

export interface CodexThreadDelta {
  thread_id: string;
  turn_id: string;
  delta: string;
}

export interface CodexThreadMessageEvent {
  thread_id: string;
  turn_id: string | null;
  message: CodexHistoryMessage;
}

export interface CodexThreadSyncStatusEvent {
  thread_id: string;
  state: 'connecting' | 'connected' | 'live' | 'synchronizing' | 'synchronized' | 'degraded';
  detail?: string;
  retry_in_seconds?: number;
}

export type CodexExecutionState =
  | 'starting'
  | 'running'
  | 'working'
  | 'completed'
  | 'failed'
  | 'interrupted'
  | 'cancelled'
  | 'unknown';

export interface CodexThreadExecutionEvent {
  thread_id: string;
  turn_id: string | null;
  item_id: string | null;
  event_type: 'turn_started' | 'turn_completed' | 'item_started' | 'item_completed' | 'status_changed';
  state: CodexExecutionState;
  action_summary?: string;
  event_id?: string;
  sequence?: number;
}

export type CodexThreadSyncEvent =
  | { type: 'snapshot'; history: CodexThreadHistory }
  | { type: 'delta'; delta: CodexThreadDelta }
  | { type: 'message'; message: CodexThreadMessageEvent }
  | { type: 'execution'; execution: CodexThreadExecutionEvent }
  | { type: 'status'; status: CodexThreadSyncStatusEvent };

export type CodexSyncStatus =
  | 'idle'
  | 'connecting'
  | 'live'
  | 'degraded'
  | 'paused'
  | 'retrying';

export interface ConversationStore {
  version: 1;
  conversations: Record<string, Conversation>;
  activeId: string | null;
}

// --- Stream State ---

export interface StreamState {
  isStreaming: boolean;
  owner: 'local' | 'remote' | null;
  phase: string;
  elapsedMs: number;
  activeToolCalls: ToolCallInfo[];
  content: string;
}

// --- API Types ---

export interface ModelInfo {
  id: string;
  object: string;
  created: number;
  owned_by: string;
}

export interface ProviderSavings {
  provider: string;
  label: string;
  input_cost: number;
  output_cost: number;
  total_cost: number;
  energy_wh: number;
  energy_joules: number;
  flops: number;
}

export interface SavingsData {
  total_calls: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  local_cost: number;
  per_provider: ProviderSavings[];
  token_counting_version?: number;
}

export interface ServerInfo {
  model: string;
  agent: string | null;
  engine: string;
}

// --- Log Types ---

export interface LogEntry {
  timestamp: number;
  level: 'info' | 'warn' | 'error';
  category: 'server' | 'model' | 'chat' | 'tool';
  message: string;
}
