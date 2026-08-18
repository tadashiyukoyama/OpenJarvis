import { useEffect, useMemo } from 'react';
import { FolderOpen, MessageSquare, RefreshCw } from 'lucide-react';
import { useAppStore } from '../../lib/store';

const NEW_THREAD = '__new__';

export function CodexTargetSelector() {
  const catalog = useAppStore((s) => s.codexCatalog);
  const loading = useAppStore((s) => s.codexCatalogLoading);
  const error = useAppStore((s) => s.codexCatalogError);
  const historyLoading = useAppStore((s) => s.codexHistoryLoading);
  const historyError = useAppStore((s) => s.codexHistoryError);
  const syncStatus = useAppStore((s) => s.codexSyncStatus);
  const refresh = useAppStore((s) => s.refreshCodexCatalog);
  const activeId = useAppStore((s) => s.activeId);
  const conversations = useAppStore((s) => s.conversations);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const createConversation = useAppStore((s) => s.createConversation);
  const selectCodexThread = useAppStore((s) => s.selectCodexThread);
  const refreshCodexDesktop = useAppStore((s) => s.settings.refreshCodexDesktop);
  const updateSettings = useAppStore((s) => s.updateSettings);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const activeConversation = conversations.find((conversation) => conversation.id === activeId);
  const activeThreadId = activeConversation?.codexThreadId;
  const projects = catalog?.projects || [];
  const selectedProjectCwd = activeConversation?.codexProjectCwd || projects[0]?.cwd || '';
  const selectedProject = projects.find((project) => project.cwd === selectedProjectCwd);
  const threads = useMemo(
    () => selectedProject?.threads || [],
    [selectedProject],
  );
  const syncLabel = activeThreadId && historyLoading !== activeId
    ? {
        live: 'Synced with Codex',
        degraded: 'Codex connected — history catching up',
        connecting: 'Connecting to Codex...',
        retrying: 'Reconnecting to Codex...',
        paused: 'OpenJarvis response streaming',
        idle: historyError ? 'Waiting for Codex synchronization...' : null,
      }[syncStatus]
    : null;

  if (error && !catalog) {
    return (
      <div className="mx-3 mb-2 rounded-lg px-3 py-2 text-[11px]" style={{
        color: 'var(--color-text-tertiary)',
        background: 'var(--color-bg-secondary)',
        border: '1px solid var(--color-border)',
      }}>
        Codex conversations unavailable
      </div>
    );
  }

  return (
    <div
      className="mx-3 mb-2 rounded-lg p-2"
      style={{
        background: 'var(--color-bg-secondary)',
        border: '1px solid var(--color-border)',
      }}
    >
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] uppercase tracking-wide" style={{ color: 'var(--color-text-tertiary)' }}>
          Codex target
        </span>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={loading}
          className="p-1 rounded cursor-pointer disabled:opacity-40"
          style={{ color: 'var(--color-text-tertiary)' }}
          title="Refresh Codex projects and conversations"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      <label className="flex items-center gap-1.5 mb-1.5">
        <FolderOpen size={13} style={{ color: 'var(--color-text-tertiary)' }} />
        <select
          value={selectedProjectCwd}
          onChange={(event) => {
            if (event.target.value) {
              createConversation(selectedModel, event.target.value, null);
            }
          }}
          className="min-w-0 flex-1 bg-transparent outline-none text-xs cursor-pointer"
          style={{ color: 'var(--color-text-secondary)' }}
          disabled={loading || projects.length === 0}
          aria-label="Codex project"
        >
          {projects.length === 0 && <option value="">No projects found</option>}
          {projects.map((project) => (
            <option key={project.cwd} value={project.cwd}>{project.name}</option>
          ))}
        </select>
      </label>

      <label className="flex items-center gap-1.5">
        <MessageSquare size={13} style={{ color: 'var(--color-text-tertiary)' }} />
        <select
          value={activeConversation?.codexThreadId || NEW_THREAD}
          onChange={(event) => {
            const value = event.target.value;
            if (value === NEW_THREAD) {
              createConversation(selectedModel, selectedProjectCwd || null, null);
              return;
            }
            const thread = threads.find((item) => item.thread_id === value);
            if (thread) selectCodexThread(thread);
          }}
          className="min-w-0 flex-1 bg-transparent outline-none text-xs cursor-pointer"
          style={{ color: 'var(--color-text-secondary)' }}
          disabled={loading || !selectedProjectCwd}
          aria-label="Codex conversation"
        >
          <option value={NEW_THREAD}>+ New conversation</option>
          {threads.map((thread) => (
            <option key={thread.thread_id} value={thread.thread_id}>{thread.name}</option>
          ))}
        </select>
      </label>
      {activeThreadId && historyLoading === activeId && (
        <div className="mt-1 text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
          Loading conversation history...
        </div>
      )}
      {syncLabel && (
        <div className="mt-1 text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
          {syncLabel}
        </div>
      )}
      {activeThreadId && (
        <label className="mt-2 flex items-start gap-2 text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
          <input
            type="checkbox"
            checked={refreshCodexDesktop}
            onChange={(event) => updateSettings({ refreshCodexDesktop: event.target.checked })}
            className="mt-0.5 accent-[var(--color-accent)]"
          />
          <span>Atualizar o Codex Desktop após respostas</span>
        </label>
      )}
    </div>
  );
}
