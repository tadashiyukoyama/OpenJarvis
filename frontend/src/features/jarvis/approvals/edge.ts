import type { JarvisAgentEvent, JarvisEdgeApproval, JsonObject } from '../api/types';

export function edgeApprovalFromEvent(event: JarvisAgentEvent): JarvisEdgeApproval | null {
  if (event.event_type !== 'edge_approval_required' || !event.job_id) return null;
  const approvalId = event.payload.approval_id;
  const payloadHash = event.payload.payload_hash;
  const expiresAt = event.payload.expires_at;
  if (
    typeof approvalId !== 'string'
    || typeof payloadHash !== 'string'
    || typeof expiresAt !== 'number'
    || typeof event.payload.preview !== 'object'
    || event.payload.preview === null
    || Array.isArray(event.payload.preview)
  ) return null;
  return {
    approval_id: approvalId,
    action_id: event.action_id,
    job_id: event.job_id,
    payload_hash: payloadHash,
    preview: event.payload.preview as JsonObject,
    expires_at: expiresAt,
  };
}

export function eventResolvesEdgeApproval(
  event: JarvisAgentEvent,
  approval: JarvisEdgeApproval,
): boolean {
  return event.event_type === 'edge_approval_decided'
    && event.payload.approval_id === approval.approval_id;
}
