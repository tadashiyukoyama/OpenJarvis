import { describe, expect, it, vi } from 'vitest';
import type { JarvisAgentAction, JarvisAgentSession } from '../api/types';
import {
  JarvisAgentCoordinator,
  type JarvisAgentTransport,
} from './coordinator';

const SESSION: JarvisAgentSession = {
  session_id: 'jas-test',
  generation: 17,
  state: 'ACTIVE',
  manifest_version: 'manifest-v1',
  manifest: [],
  catalog: {
    version: 'manifest-v1',
    manifest: [],
    tools: [],
    sources: [],
    providers: [],
    availability: {},
  },
  context: { objective: '', decisions: [], pending: [], results: [], references: [] },
};

const APPROVAL: JarvisAgentAction = {
  action_id: 'act-1',
  session_id: SESSION.session_id,
  function_call_id: 'fc-1',
  tool_id: 'codex.delegate',
  payload_hash: 'a'.repeat(64),
  preview: { destination: 'Codex Desktop', command: 'investigue' },
  state: 'AWAITING_APPROVAL',
  status: 'approval_required',
  expires_at: Date.now() / 1000 + 300,
  result: null,
  summary: '',
  error_code: null,
};

function transport(overrides: Partial<JarvisAgentTransport> = {}): JarvisAgentTransport {
  return {
    createSession: vi.fn(async () => SESSION),
    commitTurn: vi.fn(async () => ({ status: 'committed' })),
    propose: vi.fn(async () => APPROVAL),
    decide: vi.fn(async (action, decision) => ({
      ...action,
      state: decision === 'approve' ? 'COMPLETED' : 'DENIED',
      status: decision === 'approve' ? 'completed' : 'denied',
      result: decision === 'approve' ? { status: 'completed', summary: 'feito' } : null,
    })),
    close: vi.fn(async () => ({ state: 'CLOSED' })),
    streamEvents: vi.fn((_after, _onEvent, signal) => new Promise<number>((resolve) => {
      signal.addEventListener('abort', () => resolve(0), { once: true });
    })),
    ...overrides,
  };
}

function callbacks() {
  return {
    onApproval: vi.fn(),
    onEvent: vi.fn(),
    onNotice: vi.fn(),
  };
}

describe('JarvisAgentCoordinator', () => {
  it('commits the final turn before proposing the function call', async () => {
    const order: string[] = [];
    const api = transport({
      commitTurn: vi.fn(async () => {
        order.push('turn');
        return {};
      }),
      propose: vi.fn(async (): Promise<JarvisAgentAction> => {
        order.push('proposal');
        return { ...APPROVAL, state: 'COMPLETED', status: 'completed' };
      }),
    });
    const coordinator = new JarvisAgentCoordinator(callbacks(), api);
    await coordinator.open('D:/dev/project', 'thread-1');

    void coordinator.commitFinalTurn('pedido completo');
    await coordinator.handleFunctionCall({ id: 'fc-read', name: 'read', args: {} });

    expect(order).toEqual(['turn', 'proposal']);
    const proposalArgs = vi.mocked(api.propose).mock.calls[0];
    expect(proposalArgs[4]).toMatch(/^turn_/);
    await coordinator.close();
  });

  it('keeps one function call suspended until the exact visual decision', async () => {
    const api = transport();
    const ui = callbacks();
    const coordinator = new JarvisAgentCoordinator(ui, api);
    await coordinator.open('D:/dev/project', 'thread-1');

    const resultPromise = coordinator.handleFunctionCall({
      id: 'fc-1',
      name: 'codex_delegate_task',
      args: { command: 'investigue' },
    });
    await vi.waitFor(() => expect(ui.onApproval).toHaveBeenCalledWith(APPROVAL));
    let settled = false;
    void resultPromise.then(() => { settled = true; });
    await Promise.resolve();
    expect(settled).toBe(false);

    const decision = await coordinator.decide('approve');
    await expect(resultPromise).resolves.toMatchObject({
      status: 'completed',
      action_id: 'act-1',
      result_trust: 'external_untrusted_data',
    });
    expect(decision).toMatchObject({
      status: 'completed',
      result_trust: 'external_untrusted_data',
    });
    expect(api.decide).toHaveBeenCalledWith(APPROVAL, 'approve');
    expect(ui.onApproval).toHaveBeenLastCalledWith(null);
    await coordinator.close();
  });

  it('does not execute a spoken confirmation without a function call', async () => {
    const api = transport();
    const coordinator = new JarvisAgentCoordinator(callbacks(), api);
    await coordinator.open('D:/dev/project', 'thread-1');

    await coordinator.commitFinalTurn('Sim, eu confirmo.');

    expect(api.commitTurn).toHaveBeenCalledTimes(1);
    expect(api.propose).not.toHaveBeenCalled();
    expect(api.decide).not.toHaveBeenCalled();
    await coordinator.close();
  });

  it('resolves a pending call as closed before closing the backend session', async () => {
    const api = transport();
    const coordinator = new JarvisAgentCoordinator(callbacks(), api);
    await coordinator.open('D:/dev/project', 'thread-1');
    const pending = coordinator.handleFunctionCall({
      id: 'fc-1',
      name: 'codex_delegate_task',
      args: { command: 'investigue' },
    });
    await vi.waitFor(() => expect(coordinator.pendingApproval).not.toBeNull());

    await coordinator.close();

    await expect(pending).resolves.toMatchObject({ status: 'session_closed' });
    expect(api.close).toHaveBeenCalledWith(SESSION);
  });
});
