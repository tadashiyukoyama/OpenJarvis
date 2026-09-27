import { apiFetch } from '@/lib/api';

export interface AgentHostStatus {
  status: string;
  run_id: string | null;
  objective: string | null;
  budget: Record<string, unknown> | null;
  conversation_id: string | null;
  latest_activity: Record<string, unknown> | null;
  last_error: string | null;
  pending_approval: AgentHostApproval | null;
  principal_id: 'owner';
}

export interface AgentHostEvent {
  sequence: number;
  event_id: string;
  conversation_id: string;
  run_id: string;
  role: 'owner' | 'assistant' | string;
  event_type: string;
  content: string;
  payload: Record<string, unknown>;
  correlation_id?: string | null;
  created_at: string;
}

export interface AgentHostApproval {
  approval_id: string;
  state: string;
  preview: Record<string, unknown>;
  preview_hash: string;
  created_at: string;
  principal_id: 'owner';
  decision?: string;
}

export interface AgentHostArtifact {
  artifact_id: string;
  filename: string;
  mime_type: string;
  size: number;
  source: string;
  status: string;
  created_at: string;
  expires_at?: string | null;
}

export interface WhatsAppConversationSummary {
  conversation_id: string;
  principal_id: string | null;
  display_label: string;
  last_message: string;
  last_role: string;
  last_event_type: string;
  last_activity_at: string;
  message_count: number;
  received_count: number;
  last_run_id: string;
  source: 'whatsapp' | string;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await apiFetch(path, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      ...((init.headers as Record<string, string> | undefined) ?? {}),
    },
  });
  const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    const detail = body.detail;
    const message = typeof detail === 'string'
      ? detail
      : typeof detail === 'object' && detail !== null && 'message' in detail
        ? String((detail as Record<string, unknown>).message)
        : `Agent Host HTTP ${response.status}`;
    throw new Error(message);
  }
  return body as T;
}

export function fetchAgentHostStatus(conversationId: string): Promise<AgentHostStatus> {
  return request(`/v1/agent-host/status?conversation_id=${encodeURIComponent(conversationId)}`);
}

export function fetchAgentHostHistory(conversationId: string, after = 0): Promise<{ events: AgentHostEvent[]; next_after: number }> {
  return request(`/v1/agent-host/history?conversation_id=${encodeURIComponent(conversationId)}&after=${Math.max(0, after)}`);
}

export function fetchWhatsAppConversations(limit = 100): Promise<{ conversations: WhatsAppConversationSummary[]; privacy?: string }> {
  return request(`/v1/agent-host/whatsapp/conversations?limit=${Math.min(100, Math.max(1, limit))}`);
}

export function sendWhatsAppOperatorReply(
  conversationId: string,
  message: string,
  idempotencyKey: string,
  correlationId?: string,
): Promise<Record<string, unknown>> {
  return request('/v1/agent-host/whatsapp/reply', {
    method: 'POST',
    body: JSON.stringify({
      conversation_id: conversationId,
      message,
      idempotency_key: idempotencyKey,
      ...(correlationId ? { correlation_id: correlationId } : {}),
      confirm_send: true,
    }),
  });
}

export function fetchAgentHostArtifacts(conversationId: string): Promise<{ artifacts: AgentHostArtifact[]; conversation_id: string | null }> {
  return request(`/v1/agent-host/artifacts?conversation_id=${encodeURIComponent(conversationId)}`);
}

export function sendAgentHostMessage(conversationId: string, message: string, idempotencyKey?: string, correlationId?: string): Promise<Record<string, unknown>> {
  return request('/v1/agent-host/messages', {
    method: 'POST',
    body: JSON.stringify({ conversation_id: conversationId, message, ...(idempotencyKey ? { idempotency_key: idempotencyKey } : {}), ...(correlationId ? { correlation_id: correlationId } : {}) }),
  });
}

export function controlAgentHost(command: 'pause' | 'continue' | 'stop'): Promise<Record<string, unknown>> {
  const key = globalThis.crypto?.randomUUID?.() ?? `${command}-${Date.now().toString(36)}`;
  return request('/v1/agent-host/control', { method: 'POST', body: JSON.stringify({ command, idempotency_key: `control-${key}` }) });
}

export function requestAgentHostApproval(preview: Record<string, unknown> = { kind: 'safe_test' }): Promise<AgentHostApproval> {
  const key = globalThis.crypto?.randomUUID?.() ?? `approval-${Date.now().toString(36)}`;
  return request('/v1/agent-host/approvals/test', { method: 'POST', body: JSON.stringify({ preview, idempotency_key: `approval-${key}` }) });
}

export function decideAgentHostApproval(approvalId: string, decision: 'approve' | 'deny'): Promise<AgentHostApproval> {
  const key = globalThis.crypto?.randomUUID?.() ?? `decision-${Date.now().toString(36)}`;
  return request(`/v1/agent-host/approvals/${encodeURIComponent(approvalId)}/decision`, {
    method: 'POST',
    body: JSON.stringify({ decision, idempotency_key: `approval-decision-${key}` }),
  });
}
