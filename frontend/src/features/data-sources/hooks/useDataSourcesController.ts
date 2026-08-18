import { useCallback, useEffect, useRef, useState } from 'react';
import {
  connectSource,
  disconnectSource,
  getSyncStatus,
  listConnectors,
  startServerOAuth,
  triggerSync,
} from '@/lib/connectors-api';
import { useAppStore } from '@/lib/store';
import type { CachedConnector } from '@/lib/store';
import type { ConnectRequest, ConnectorInfo, SyncStatus } from '@/types/connectors';
import { includeUploadSource, unifyLogicalSources } from '../source-model';

function cached(info: ConnectorInfo): CachedConnector {
  return {
    connector_id: info.connector_id,
    display_name: info.display_name,
    connected: info.connected,
    chunks: info.chunks || 0,
  };
}

function connectionError(error: unknown, connectorId: string): string {
  let message = error instanceof Error ? error.message : 'Connection failed';
  if (
    connectorId === 'gmail_imap'
    && /auth|credentials|login/i.test(message)
  ) {
    message = 'Invalid credentials — use a 16-character App Password, not your regular Gmail password.';
  }
  return message;
}

export function useDataSourcesController() {
  const cachedConnectors = useAppStore((state) => state.cachedConnectors);
  const setCachedConnectors = useAppStore((state) => state.setCachedConnectors);
  const connectors = cachedConnectors ?? [];
  const [syncStatuses, setSyncStatuses] = useState<Record<string, SyncStatus>>({});
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [connectingId, setConnectingId] = useState<string | null>(null);
  const [connectStage, setConnectStage] = useState('');
  const [connectError, setConnectError] = useState('');
  const [disconnectingId, setDisconnectingId] = useState<string | null>(null);
  const connectorPoll = useRef<AbortController | null>(null);
  const syncPoll = useRef<AbortController | null>(null);

  const loadConnectors = useCallback(() => {
    if (connectorPoll.current) return;
    const controller = new AbortController();
    connectorPoll.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 8_000);
    listConnectors(controller.signal)
      .then((items) => setCachedConnectors(items.map(cached)))
      .catch(() => undefined)
      .finally(() => {
        window.clearTimeout(timeout);
        if (connectorPoll.current === controller) connectorPoll.current = null;
      });
  }, [setCachedConnectors]);

  const loadSyncStatuses = useCallback(async () => {
    if (syncPoll.current) return;
    const controller = new AbortController();
    syncPoll.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 8_000);
    const statuses: Record<string, SyncStatus> = {};
    try {
      await Promise.all(
        connectors.filter((item) => item.connected).map(async (item) => {
          try {
            statuses[item.connector_id] = await getSyncStatus(
              item.connector_id,
              controller.signal,
            );
          } catch {
            // One unavailable Source must not block status from other Sources.
          }
        }),
      );
      if (!controller.signal.aborted) {
        setSyncStatuses((previous) => ({ ...previous, ...statuses }));
      }
    } finally {
      window.clearTimeout(timeout);
      if (syncPoll.current === controller) syncPoll.current = null;
    }
  }, [connectors]);

  useEffect(() => {
    loadConnectors();
    const interval = window.setInterval(loadConnectors, 10_000);
    return () => {
      window.clearInterval(interval);
      connectorPoll.current?.abort();
      connectorPoll.current = null;
    };
  }, [loadConnectors]);

  useEffect(() => {
    if (!connectors.some((item) => item.connected)) return;
    loadSyncStatuses();
    const interval = window.setInterval(loadSyncStatuses, 5_000);
    return () => {
      window.clearInterval(interval);
      syncPoll.current?.abort();
      syncPoll.current = null;
    };
  }, [connectors, loadSyncStatuses]);

  const handleDisconnect = async (connectorId: string) => {
    if (disconnectingId) return;
    setDisconnectingId(connectorId);
    try {
      await disconnectSource(connectorId);
      loadConnectors();
    } finally {
      setDisconnectingId(null);
    }
  };

  const waitForConnection = async (connectorId: string): Promise<void> => {
    for (let attempt = 0; attempt < 20; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 2_000));
      const updated = await listConnectors();
      if (updated.find((item) => item.connector_id === connectorId)?.connected) {
        setCachedConnectors(updated.map(cached));
        return;
      }
      setConnectStage(attempt < 5 ? 'Authenticating...' : 'Waiting for connection...');
    }
  };

  const handleConnect = async (connectorId: string, request: ConnectRequest) => {
    setLoading(true);
    setConnectingId(connectorId);
    setConnectStage('Connecting...');
    setConnectError('');
    try {
      const response = await connectSource(connectorId, request);
      if (response.status === 'oauth_required') {
        setConnectStage('Opening Google sign-in...');
        await startServerOAuth(connectorId, response.oauth_start);
      }
      setConnectStage('Connected! Starting sync...');
      await waitForConnection(connectorId);
      setConnectStage('Syncing data...');
      await triggerSync(connectorId).catch(() => undefined);
      await new Promise((resolve) => window.setTimeout(resolve, 1_500));
      setExpandedId(null);
      loadConnectors();
      loadSyncStatuses();
    } catch (error) {
      setConnectError(connectionError(error, connectorId));
      setConnectStage('');
    } finally {
      setLoading(false);
      setConnectingId(null);
      setConnectStage('');
    }
  };

  const logical = unifyLogicalSources(connectors);
  return {
    isFirstLoad: cachedConnectors === null,
    connected: logical.filter((item) => item.connected),
    available: includeUploadSource(logical.filter((item) => !item.connected)),
    syncStatuses,
    expandedId,
    setExpandedId,
    loading,
    connectingId,
    connectStage,
    connectError,
    disconnectingId,
    loadConnectors,
    handleConnect,
    handleDisconnect,
  };
}
