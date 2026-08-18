const FALLBACK_HASH_PREFIX = 'fnv1a';
const SAFE_APPROVAL_EVENTS = new Set([
  'confirmation_accepted',
  'confirmation_expired',
  'confirmation_not_created',
  'confirmation_rejected',
  'confirmation_rejected_busy',
  'confirmation_requested',
  'confirmation_resolved',
  'confirmation_state_mismatch',
]);
const SAFE_APPROVAL_FIELDS = new Set([
  'command_length',
  'command_sha256',
  'destination',
  'function_call_id',
  'reason',
  'request_id',
  'status',
]);

export function createJarvisRequestId(prefix = 'jarvis'): string {
  const random = Math.random().toString(36).slice(2, 10);
  return `${prefix}-${Date.now()}-${random}`;
}

function fallbackFingerprint(text: string): string {
  let hash = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return `${FALLBACK_HASH_PREFIX}-${hash.toString(16).padStart(8, '0')}`;
}

export async function fingerprintOperationalText(text: string): Promise<string> {
  const encoder = globalThis.TextEncoder;
  const subtle = globalThis.crypto?.subtle;
  if (!encoder || !subtle) return fallbackFingerprint(text);
  const digest = await subtle.digest('SHA-256', new encoder().encode(text));
  return Array.from(new Uint8Array(digest))
    .map((value) => value.toString(16).padStart(2, '0'))
    .join('')
    .slice(0, 16);
}

export function operationalCorrelation(
  requestId: string,
  command: string,
  fingerprint: string,
  functionCallId = 'manual',
): string {
  const safeFunctionCallId = functionCallId.replace(/[^A-Za-z0-9._:-]/g, '_').slice(0, 128);
  return `request_id=${requestId} function_call_id=${safeFunctionCallId} command_sha256=${fingerprint} command_length=${command.length}`;
}

export function safeOperationalEventText(type: string, text: string): string {
  if (type === 'approval') {
    const [eventName = ''] = text.trim().split(/\s+/, 1);
    if (SAFE_APPROVAL_EVENTS.has(eventName)) {
      const fields = [...text.matchAll(/\b([a-z_]+)=([^\s]+)/g)]
        .filter((match) => SAFE_APPROVAL_FIELDS.has(match[1]))
        .map((match) => `${match[1]}=${match[2].replace(/[^A-Za-z0-9._:-]/g, '_').slice(0, 160)}`);
      return [eventName, ...fields].join(' ');
    }
    return `approval_payload length=${text.length}`;
  }
  if (type === 'user' || type === 'jarvis' || type === 'codex') {
    return `${type}_payload length=${text.length}`;
  }
  return text;
}

export const jarvisObservabilityInternals = {
  SAFE_APPROVAL_EVENTS,
  SAFE_APPROVAL_FIELDS,
  fallbackFingerprint,
};
