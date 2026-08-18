import { describe, expect, it } from 'vitest';
import type { JarvisAgentEvent } from '../api/types';
import { edgeApprovalFromEvent, eventResolvesEdgeApproval } from './edge';

const EVENT: JarvisAgentEvent = {
  sequence: 4,
  event_id: 'event-4',
  event_type: 'edge_approval_required',
  session_id: 'session-1',
  action_id: 'action-1',
  job_id: 'job-1',
  payload: {
    approval_id: 'approval-1',
    payload_hash: 'a'.repeat(64),
    preview: { command: 'pytest -q' },
    expires_at: 100,
  },
  created_at: 1,
};

describe('Edge approval event contract', () => {
  it('extracts only a complete nested approval', () => {
    expect(edgeApprovalFromEvent(EVENT)).toEqual({
      approval_id: 'approval-1',
      action_id: 'action-1',
      job_id: 'job-1',
      payload_hash: 'a'.repeat(64),
      preview: { command: 'pytest -q' },
      expires_at: 100,
    });
    expect(edgeApprovalFromEvent({ ...EVENT, job_id: null })).toBeNull();
  });

  it('matches only the exact decision event', () => {
    const approval = edgeApprovalFromEvent(EVENT)!;
    const decided = {
      ...EVENT,
      event_type: 'edge_approval_decided',
      payload: { approval_id: 'approval-1', decision: 'approve' },
    };
    expect(eventResolvesEdgeApproval(decided, approval)).toBe(true);
    expect(eventResolvesEdgeApproval({ ...decided, payload: { approval_id: 'other' } }, approval))
      .toBe(false);
  });
});
