import { useEffect } from 'react';
import { fetchCodexThreadHistory } from './api';
import {
  MAX_FINITE_HISTORY_PAGES,
  prependCodexHistoryPage,
  usesFiniteCodexSync,
} from './codex-sync-transport';
import { useAppStore } from './store';
import { streamCodexThreadUpdates } from './sse';

const POLL_INTERVAL_MS = 3_000;

function retryDelay(milliseconds: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.resolve();
  return new Promise((resolve) => {
    const finish = () => {
      window.clearTimeout(timer);
      signal.removeEventListener('abort', finish);
      resolve();
    };
    const timer = window.setTimeout(finish, milliseconds);
    signal.addEventListener('abort', finish, { once: true });
  });
}

export function useCodexThreadSync(): void {
  const activeId = useAppStore((state) => state.activeId);
  const conversations = useAppStore((state) => state.conversations);
  const applyHistory = useAppStore((state) => state.applyCodexHistory);
  const applyDelta = useAppStore((state) => state.applyCodexDelta);
  const applyMessage = useAppStore((state) => state.applyCodexMessage);
  const setSyncState = useAppStore((state) => state.setCodexSyncState);
  const threadId = conversations.find((conversation) => conversation.id === activeId)
    ?.codexThreadId;

  useEffect(() => {
    if (!activeId || !threadId) {
      setSyncState('idle', null);
      return;
    }
    const controller = new AbortController();
    let retryMilliseconds = 1_000;
    let initialFiniteHistoryLoaded = false;

    const synchronize = async () => {
      setSyncState('connecting', null);
      if (usesFiniteCodexSync(window.location.hostname)) {
        while (!controller.signal.aborted) {
          try {
            let history = await fetchCodexThreadHistory(threadId, controller.signal);
            if (controller.signal.aborted) return;
            applyHistory(activeId, history);
            retryMilliseconds = 1_000;
            setSyncState('live', null);
            if (!initialFiniteHistoryLoaded) {
              let cursor = history.next_cursor;
              let pagesLoaded = 1;
              while (
                cursor
                && pagesLoaded < MAX_FINITE_HISTORY_PAGES
                && !controller.signal.aborted
              ) {
                const older = await fetchCodexThreadHistory(
                  threadId,
                  controller.signal,
                  cursor,
                );
                if (controller.signal.aborted) return;
                history = prependCodexHistoryPage(history, older);
                applyHistory(activeId, history);
                cursor = older.next_cursor;
                pagesLoaded += 1;
              }
              initialFiniteHistoryLoaded = true;
            }
            await retryDelay(POLL_INTERVAL_MS, controller.signal);
          } catch (error) {
            if (controller.signal.aborted) return;
            setSyncState(
              'retrying',
              error instanceof Error ? error.message : 'Codex synchronization failed',
            );
            await retryDelay(retryMilliseconds, controller.signal);
            retryMilliseconds = Math.min(retryMilliseconds * 2, 10_000);
          }
        }
        return;
      }
      while (!controller.signal.aborted) {
        try {
          for await (const update of streamCodexThreadUpdates(
            threadId,
            controller.signal,
          )) {
            if (controller.signal.aborted) return;
            if (update.type === 'snapshot') {
              applyHistory(activeId, update.history);
            } else if (update.type === 'delta') {
              if (!useAppStore.getState().streamState.isStreaming) {
                applyDelta(activeId, update.delta);
              }
            } else if (update.type === 'message') {
              applyMessage(activeId, update.message);
            } else if (update.status.state === 'degraded') {
              retryMilliseconds = 1_000;
              setSyncState(
                'degraded',
                update.status.detail ?? 'Codex history is catching up',
              );
              continue;
            }
            retryMilliseconds = 1_000;
            setSyncState('live', null);
          }
        } catch (error) {
          if (controller.signal.aborted) return;
          setSyncState(
            'retrying',
            error instanceof Error ? error.message : 'Codex synchronization failed',
          );
        }
        await retryDelay(retryMilliseconds, controller.signal);
        retryMilliseconds = Math.min(retryMilliseconds * 2, 10_000);
        if (!controller.signal.aborted) setSyncState('connecting', null);
      }
    };

    void synchronize();
    return () => controller.abort();
  }, [activeId, applyDelta, applyHistory, applyMessage, setSyncState, threadId]);
}
