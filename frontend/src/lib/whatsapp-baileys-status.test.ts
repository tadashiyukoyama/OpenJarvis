import { describe, expect, it } from 'vitest';
import {
  describeWhatsAppStatus,
  isWhatsAppTerminalFailure,
} from './whatsapp-baileys-status';

describe('WhatsApp Baileys status contract', () => {
  it('treats backend logout as a terminal state with an explicit reset action', () => {
    const presentation = describeWhatsAppStatus({
      status: 'logged_out',
      last_error: null,
    });

    expect(presentation.terminal).toBe(true);
    expect(presentation.retryLabel).toContain('novo QR');
    expect(presentation.message).toContain('D:');
  });

  it('keeps QR-required polling active and labels it truthfully', () => {
    const presentation = describeWhatsAppStatus({
      status: 'qr_required',
      last_error: null,
    });

    expect(presentation.terminal).toBe(false);
    expect(presentation.label).toContain('QR');
    expect(presentation.retryLabel).toBe('QR pronto — escaneie no WhatsApp');
  });

  it('explains that an authenticated session does not expose a QR code', () => {
    const presentation = describeWhatsAppStatus({
      status: 'connected',
      last_error: null,
    });

    expect(presentation.retryLabel).toBe('WhatsApp conectado');
    expect(presentation.message).toContain('Nenhum QR Code');
  });

  it('stops polling for all public failure states', () => {
    for (const status of ['conflict', 'logged_out', 'auth_inconsistent', 'failed', 'error'] as const) {
      expect(isWhatsAppTerminalFailure(status)).toBe(true);
    }
    expect(isWhatsAppTerminalFailure('connecting')).toBe(false);
    expect(isWhatsAppTerminalFailure('qr_required')).toBe(false);
  });

  it('requires explicit preservation before replacing inconsistent local auth', () => {
    const presentation = describeWhatsAppStatus({
      status: 'auth_inconsistent',
      last_error: null,
    });

    expect(presentation.terminal).toBe(true);
    expect(presentation.retryLabel).toContain('Preservar');
    expect(presentation.message).toContain('sessão anterior');
  });

  it('prefers the bounded backend error when present', () => {
    const presentation = describeWhatsAppStatus({
      status: 'failed',
      last_error: 'Falha controlada do bridge.',
    });

    expect(presentation.message).toBe('Falha controlada do bridge.');
  });
});
