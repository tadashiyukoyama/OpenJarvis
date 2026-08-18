import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const apiMocks = vi.hoisted(() => ({
  fetchCodexCatalog: vi.fn(),
  fetchCodexThreadHistory: vi.fn(),
}));

vi.mock('./api', () => apiMocks);

function installLocalStorage(): Storage {
  const values = new Map<string, string>();
  const storage: Storage = {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, String(value)),
  };
  vi.stubGlobal('localStorage', storage);
  return storage;
}

describe('Codex store synchronization', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    installLocalStorage();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('does not start a competing history request when selecting a conversation', async () => {
    localStorage.setItem('openjarvis-conversations', JSON.stringify({
      version: 1,
      activeId: null,
      conversations: {
        conversation: {
          id: 'conversation',
          title: 'Existing Codex task',
          createdAt: 1,
          updatedAt: 1,
          model: 'codex',
          messages: [],
          codexThreadId: 'thread-1',
          codexProjectCwd: 'D:/dev/workspaces/openjarvis',
        },
      },
    }));
    const { useAppStore } = await import('./store');

    useAppStore.getState().selectConversation('conversation');

    expect(apiMocks.fetchCodexThreadHistory).not.toHaveBeenCalled();
  });

  it('clears a stale one-shot history error when the stream is connected', async () => {
    const { useAppStore } = await import('./store');
    useAppStore.setState({
      codexHistoryError: 'Codex history unavailable',
      codexHistoryLoading: 'conversation',
    });

    useAppStore.getState().setCodexSyncState(
      'degraded',
      'Codex history is catching up',
    );

    expect(useAppStore.getState()).toMatchObject({
      codexSyncStatus: 'degraded',
      codexHistoryError: null,
      codexHistoryLoading: null,
    });
  });
});
