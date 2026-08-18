import { describe, expect, it } from 'vitest';
import { parseWhatsAppSendArguments, resolveWhatsAppContacts } from './jarvis-whatsapp-routing';

describe('WhatsApp Jarvis routing', () => {
  it('requires exactly one destination and a non-empty message', () => {
    expect(parseWhatsAppSendArguments({ text: 'oi' })).toMatchObject({ error: expect.any(String) });
    expect(parseWhatsAppSendArguments({ jid: '1@s.whatsapp.net', contact_name: 'Klaus', text: 'oi' })).toMatchObject({ error: expect.any(String) });
    expect(parseWhatsAppSendArguments({ contact_name: 'Klaus', text: 'oi' })).toEqual({ jid: '', contactName: 'Klaus', text: 'oi' });
  });

  it('accepts one unique JID and rejects distinct ambiguous contacts', () => {
    expect(resolveWhatsAppContacts('Klaus', [{ jid: '1@s.whatsapp.net', name: 'Klaus consultor' }])).toEqual({ status: 'jid', jid: '1@s.whatsapp.net', label: 'Klaus consultor' });
    expect(resolveWhatsAppContacts('Klaus', [
      { jid: '1@s.whatsapp.net', name: 'Klaus' },
      { jid: '2@s.whatsapp.net', name: 'Klaus' },
    ])).toMatchObject({ status: 'ambiguous', query: 'Klaus' });
  });

  it('does not treat duplicate rows for one JID as ambiguity', () => {
    expect(resolveWhatsAppContacts('Klaus', [
      { jid: '1@s.whatsapp.net', name: 'Klaus' },
      { jid: '1@s.whatsapp.net', name: 'Klaus consultor' },
    ])).toMatchObject({ status: 'jid', jid: '1@s.whatsapp.net' });
  });
});
