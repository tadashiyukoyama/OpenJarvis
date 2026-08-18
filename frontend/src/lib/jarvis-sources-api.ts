import { apiFetch } from './api';

export type JarvisSource = 'gmail' | 'whatsapp_baileys';
export type WhatsAppBaileysStatus =
  | 'disconnected'
  | 'connecting'
  | 'qr_required'
  | 'connected'
  | 'conflict'
  | 'logged_out'
  | 'auth_inconsistent'
  | 'failed'
  | 'error';

export interface WhatsAppBaileysStatusResponse {
  source: 'whatsapp_baileys';
  status: WhatsAppBaileysStatus;
  base_status?: 'disconnected' | 'connecting' | 'connected' | 'error';
  reason?: string | null;
  last_error?: string | null;
  last_operation_error?: string | null;
  qr_available: boolean;
  qr_generation?: number;
  qr_issued_at?: string | null;
  send_available?: boolean;
  last_transition_at?: string | null;
}

export interface WhatsAppBaileysQrResponse extends WhatsAppBaileysStatusResponse {
  qr: string;
  available: boolean;
  qr_generation: number;
  qr_issued_at: string | null;
}

async function sourceFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(`/v1/jarvis/sources${path}`, init);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(typeof body?.detail === 'string' ? body.detail : `Data Source indisponível: ${response.status}`);
  }
  return body as T;
}

export function fetchGmailStatus() {
  return sourceFetch<{ source: 'gmail'; connected: boolean }>('/gmail/status');
}

export function searchGmail(query: string, maxResults = 10) {
  return sourceFetch<{ source: 'gmail'; messages: Record<string, unknown>[] }>('/gmail/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, max_results: maxResults }),
  });
}

export function readGmail(messageId: string) {
  return sourceFetch<{ source: 'gmail'; message: Record<string, unknown> }>('/gmail/read', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message_id: messageId }),
  });
}

export function issueJarvisSourceApproval(action: string) {
  return sourceFetch<{ approval_token: string; action: string }>('/approval', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action }),
  });
}

export function sendGmail(payload: { to: string; subject: string; body: string; cc?: string }, approvalToken: string) {
  return sourceFetch<{ source: 'gmail'; status: string; message_id: string }>('/gmail/send', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(approvalToken ? { 'X-Jarvis-Approval': approvalToken } : {}) },
    body: JSON.stringify(payload),
  });
}

export function archiveGmail(messageId: string, approvalToken: string) {
  return sourceFetch<{ status: string; message_id: string }>('/gmail/archive', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(approvalToken ? { 'X-Jarvis-Approval': approvalToken } : {}) },
    body: JSON.stringify({ message_id: messageId }),
  });
}

export function trashGmail(messageId: string, approvalToken: string) {
  return sourceFetch<{ status: string; message_id: string }>('/gmail/trash', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(approvalToken ? { 'X-Jarvis-Approval': approvalToken } : {}) },
    body: JSON.stringify({ message_id: messageId }),
  });
}

export function fetchWhatsAppStatus() {
  return sourceFetch<WhatsAppBaileysStatusResponse>('/whatsapp/status', {
    cache: 'no-store',
  });
}

export function startWhatsAppQr() {
  return sourceFetch<WhatsAppBaileysStatusResponse>('/whatsapp/start', { method: 'POST' });
}

export function resetWhatsAppQr() {
  return sourceFetch<WhatsAppBaileysStatusResponse>('/whatsapp/reset', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm: true }),
  });
}

export function fetchWhatsAppQr(signal?: AbortSignal) {
  return sourceFetch<WhatsAppBaileysQrResponse>('/whatsapp/qr', {
    cache: 'no-store',
    signal,
  });
}

export function sendWhatsAppMessage(
  payload: { jid?: string; contact_name?: string; text: string },
  approvalToken: string,
) {
  return sourceFetch<{ source: 'whatsapp_baileys'; status: string; jid: string }>('/whatsapp/send', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(approvalToken ? { 'X-Jarvis-Approval': approvalToken } : {}) },
    body: JSON.stringify(payload),
  });
}

export function fetchWhatsAppContacts(query = '', limit = 20) {
  return sourceFetch<{ source: 'whatsapp_baileys'; contacts: Record<string, unknown>[] }>(
    `/whatsapp/contacts?query=${encodeURIComponent(query)}&limit=${limit}`,
  );
}

export function fetchWhatsAppChats(query = '', limit = 20) {
  return sourceFetch<{ source: 'whatsapp_baileys'; chats: Record<string, unknown>[] }>(
    `/whatsapp/chats?query=${encodeURIComponent(query)}&limit=${limit}`,
  );
}

export function fetchWhatsAppMessages(jid: string, query = '', limit = 50) {
  return sourceFetch<{ source: 'whatsapp_baileys'; jid: string; messages: Record<string, unknown>[] }>(
    `/whatsapp/messages?jid=${encodeURIComponent(jid)}&query=${encodeURIComponent(query)}&limit=${limit}`,
  );
}

export function summarizeWhatsAppConversation(jid: string, limit = 50) {
  return sourceFetch<{ source: 'whatsapp_baileys'; summary: Record<string, unknown> }>(
    `/whatsapp/summary?jid=${encodeURIComponent(jid)}&limit=${limit}`,
  );
}

export function runWhatsAppAction(payload: Record<string, unknown>, approvalToken = '') {
  return sourceFetch<{ source: 'whatsapp_baileys'; status: string; operation: string }>('/whatsapp/action', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...(approvalToken ? { 'X-Jarvis-Approval': approvalToken } : {}) },
    body: JSON.stringify(payload),
  });
}

export function reactWhatsAppMessage(
  payload: { message_ref: string; reaction: string },
  approvalToken: string,
) {
  return sourceFetch<{
    source: 'whatsapp_baileys';
    status: string;
    operation: 'reaction';
    target: Record<string, unknown>;
  }>('/whatsapp/reaction', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(approvalToken ? { 'X-Jarvis-Approval': approvalToken } : {}),
    },
    body: JSON.stringify(payload),
  });
}

export function previewWhatsAppReaction(payload: {
  message_ref: string;
  reaction: string;
}) {
  return sourceFetch<{
    source: 'whatsapp_baileys';
    operation: 'reaction';
    target: {
      message_ref: string;
      jid: string;
      reaction: string;
      message_preview: string;
      message_at: number;
    };
  }>('/whatsapp/reaction/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}
