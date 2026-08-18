export interface WhatsAppSendArguments {
  jid?: unknown;
  contact_name?: unknown;
  text?: unknown;
}

export interface WhatsAppContactRecord {
  jid?: unknown;
  name?: unknown;
  notify?: unknown;
  [key: string]: unknown;
}

export type WhatsAppDestinationResult =
  | { status: 'not_found'; query: string }
  | { status: 'ambiguous'; query: string; matches: Array<{ jid: string; label: string }> }
  | { status: 'jid'; jid: string; label: string };

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function contactLabel(contact: WhatsAppContactRecord, jid: string): string {
  return stringValue(contact.name) || stringValue(contact.notify) || jid;
}

export function parseWhatsAppSendArguments(
  args: WhatsAppSendArguments,
): { jid: string; contactName: string; text: string } | { error: string } {
  const jid = stringValue(args.jid);
  const contactName = stringValue(args.contact_name);
  const text = stringValue(args.text);
  if (!text) return { error: 'A mensagem WhatsApp não pode estar vazia.' };
  if (jid && contactName) return { error: 'Informe um JID ou um nome, nunca os dois.' };
  if (!jid && !contactName) return { error: 'Informe o nome do contato ou o JID WhatsApp.' };
  return { jid, contactName, text };
}

export function resolveWhatsAppContacts(
  query: string,
  contacts: WhatsAppContactRecord[],
): WhatsAppDestinationResult {
  const unique = new Map<string, { jid: string; label: string }>();
  for (const contact of contacts) {
    const jid = stringValue(contact.jid);
    if (jid && !unique.has(jid)) unique.set(jid, { jid, label: contactLabel(contact, jid) });
  }
  const matches = [...unique.values()];
  if (matches.length === 0) return { status: 'not_found', query };
  if (matches.length > 1) return { status: 'ambiguous', query, matches };
  return { status: 'jid', jid: matches[0].jid, label: matches[0].label };
}
