import { describe, expect, it } from 'vitest';
import { jarvisAgentClientInternals } from './client';

describe('Jarvis Agent event transport selection', () => {
  it('uses finite event pages only for Cloudflare Quick Tunnels', () => {
    expect(jarvisAgentClientInternals.usesQuickTunnel('voice.trycloudflare.com')).toBe(true);
    expect(jarvisAgentClientInternals.usesQuickTunnel('127.0.0.1')).toBe(false);
    expect(jarvisAgentClientInternals.usesQuickTunnel('jarvis.example.com')).toBe(false);
  });
});
