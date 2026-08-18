import type {
  ActionResponse,
  CatalogResponse,
  ContextResponse,
  JobResponse,
  ManifestEntryResponse,
  ProviderResponse,
  SessionResponse,
  SourceResponse,
  ToolResponse,
} from './generated-contracts';

export type JsonObject = Record<string, unknown>;

export type JarvisAgentManifestEntry = ManifestEntryResponse;
export type JarvisAgentProvider = ProviderResponse;
export type JarvisAgentSource = SourceResponse;
export type JarvisAgentTool = ToolResponse;
export type JarvisAgentCatalog = CatalogResponse;
export type JarvisAgentContext = ContextResponse;
export type JarvisAgentSession = SessionResponse;
export type JarvisAgentActionState = ActionResponse['state'];
export type JarvisAgentJob = JobResponse;
export type JarvisAgentAction = ActionResponse;

export interface JarvisAgentEvent {
  sequence: number;
  event_id: string;
  event_type: string;
  session_id: string | null;
  action_id: string | null;
  job_id: string | null;
  payload: JsonObject;
  created_at: number;
}

export interface JarvisAgentFunctionCall {
  id: string;
  name: string;
  args: JsonObject;
}

export interface JarvisEdgeApproval {
  approval_id: string;
  action_id: string | null;
  job_id: string;
  payload_hash: string;
  preview: JsonObject;
  expires_at: number;
}
