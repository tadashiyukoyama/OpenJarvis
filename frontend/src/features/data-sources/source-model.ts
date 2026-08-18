import type { CachedConnector } from '@/lib/store';
import { SOURCE_CATALOG } from '@/types/connectors';

export function sourceMeta(connectorId: string) {
  return SOURCE_CATALOG.find((source) => source.connector_id === connectorId);
}

export function unifyLogicalSources(connectors: CachedConnector[]): CachedConnector[] {
  const managedByAceleraChat = new Set([
    'gmail',
    'gmail_imap',
    'whatsapp',
    'whatsapp_baileys',
  ]);
  return connectors.filter((item) => !managedByAceleraChat.has(item.connector_id));
}

export function includeUploadSource(connectors: CachedConnector[]): CachedConnector[] {
  if (connectors.some((item) => item.connector_id === 'upload')) return connectors;
  return [
    ...connectors,
    {
      connector_id: 'upload',
      display_name: 'Upload / Paste',
      connected: false,
      chunks: 0,
    },
  ];
}
