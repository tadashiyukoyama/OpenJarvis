import { describe, expect, it } from 'vitest';
import type { CachedConnector } from '@/lib/store';
import { unifyLogicalSources } from './source-model';

function connector(connectorId: string): CachedConnector {
  return {
    connector_id: connectorId,
    display_name: connectorId,
    connected: true,
    chunks: 1,
  };
}

describe('AceleraChat-managed sources', () => {
  it('hides direct Gmail and WhatsApp providers but preserves unrelated sources', () => {
    const result = unifyLogicalSources([
      connector('gmail'),
      connector('gmail_imap'),
      connector('whatsapp'),
      connector('whatsapp_baileys'),
      connector('hackernews'),
      connector('upload'),
    ]);

    expect(result.map((item) => item.connector_id)).toEqual([
      'hackernews',
      'upload',
    ]);
  });
});
