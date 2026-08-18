import { describe, expect, it, vi } from 'vitest';
import { JarvisApprovalCoordinator, type JarvisApprovalDescriptor } from './jarvis-approval';

function descriptor(expiresAt = 10_000): JarvisApprovalDescriptor {
  return {
    requestId: 'request-1',
    functionCallId: 'call-1',
    destination: 'codex',
    command: 'investigue o erro',
    risk: 'workspace',
    conversationId: 'conversation-1',
    conversationTitle: 'Conversa atual',
    projectCwd: 'D:\\dev\\workspaces\\openjarvis',
    expiresAt,
  };
}

describe('Jarvis visual approval coordinator', () => {
  it('keeps the original function call pending until the button approves it', async () => {
    const coordinator = new JarvisApprovalCoordinator(() => 1_000);
    const execute = vi.fn(async () => ({ status: 'complete', result: 'feito' }));
    const toolResult = coordinator.request(descriptor(), execute);

    expect(execute).not.toHaveBeenCalled();
    expect(coordinator.snapshot()?.state).toBe('AWAITING_CONFIRMATION');

    await expect(coordinator.approve('request-1')).resolves.toMatchObject({ result: 'feito' });
    await expect(toolResult).resolves.toMatchObject({ result: 'feito' });
    expect(execute).toHaveBeenCalledTimes(1);
    expect(coordinator.snapshot()).toBeNull();
  });

  it('returns the rejection to the same pending tool call without executing', async () => {
    const coordinator = new JarvisApprovalCoordinator(() => 1_000);
    const execute = vi.fn(async () => ({ status: 'complete' }));
    const toolResult = coordinator.request(descriptor(), execute);

    expect(coordinator.reject('request-1')).toMatchObject({ status: 'rejected' });
    await expect(toolResult).resolves.toMatchObject({ status: 'rejected' });
    expect(execute).not.toHaveBeenCalled();
  });

  it('fails closed when another approval is already pending', async () => {
    const coordinator = new JarvisApprovalCoordinator(() => 1_000);
    const first = coordinator.request(descriptor(), async () => ({ status: 'complete' }));
    const second = coordinator.request(
      { ...descriptor(), requestId: 'request-2' },
      async () => ({ status: 'complete' }),
    );

    await expect(second).resolves.toMatchObject({ status: 'approval_busy' });
    coordinator.reject('request-1');
    await first;
  });

  it('expires and cancels pending calls deterministically', async () => {
    let now = 1_000;
    const coordinator = new JarvisApprovalCoordinator(() => now);
    const expired = coordinator.request(descriptor(1_100), async () => ({ status: 'complete' }));
    now = 1_101;
    expect(coordinator.expire()).toMatchObject({ status: 'expired' });
    await expect(expired).resolves.toMatchObject({ status: 'expired' });

    const cancelled = coordinator.request(descriptor(5_000), async () => ({ status: 'complete' }));
    expect(coordinator.cancelSession()).toMatchObject({ status: 'session_closed' });
    await expect(cancelled).resolves.toMatchObject({ status: 'session_closed' });
  });

  it('does not reject or expire an action after authorization started', async () => {
    let now = 1_000;
    let release!: (result: Record<string, unknown>) => void;
    const execution = new Promise<Record<string, unknown>>((resolve) => {
      release = resolve;
    });
    const coordinator = new JarvisApprovalCoordinator(() => now);
    const toolResult = coordinator.request(descriptor(1_100), () => execution);
    const approved = coordinator.approve('request-1');

    now = 1_101;
    expect(coordinator.expire()).toBeNull();
    expect(coordinator.reject('request-1')).toMatchObject({ status: 'already_dispatching' });
    expect(coordinator.snapshot()?.state).toBe('DISPATCHING');

    release({ status: 'complete', result: 'feito' });
    await expect(approved).resolves.toMatchObject({ result: 'feito' });
    await expect(toolResult).resolves.toMatchObject({ result: 'feito' });
  });
});
