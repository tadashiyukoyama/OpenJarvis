/** Normalize Baileys events into the small JSON contract used by OpenJarvis. */

function timestampMs(value: unknown): number {
  const numeric = Number(value || 0);
  if (!Number.isFinite(numeric) || numeric <= 0) return 0;
  return Math.trunc(numeric < 10_000_000_000 ? numeric * 1000 : numeric);
}

function unwrapMessage(message: any): any {
  return (
    message?.ephemeralMessage?.message ||
    message?.viewOnceMessage?.message ||
    message?.viewOnceMessageV2?.message ||
    message?.documentWithCaptionMessage?.message ||
    message ||
    {}
  );
}

function extractMessage(message: any): { text: string; type: string } {
  const content = unwrapMessage(message);
  if (content.conversation) return { text: String(content.conversation), type: "text" };
  if (content.extendedTextMessage?.text) {
    return { text: String(content.extendedTextMessage.text), type: "text" };
  }
  for (const type of ["imageMessage", "videoMessage", "documentMessage"]) {
    const caption = content[type]?.caption;
    if (caption) return { text: String(caption), type };
  }
  if (content.audioMessage) return { text: "", type: "audio" };
  if (content.stickerMessage) return { text: "", type: "sticker" };
  if (content.locationMessage) return { text: "", type: "location" };
  if (content.contactMessage || content.contactsArrayMessage) {
    return { text: "", type: "contact" };
  }
  if (content.reactionMessage) {
    return { text: String(content.reactionMessage.text || ""), type: "reaction" };
  }
  if (content.pollCreationMessage || content.pollCreationMessageV3) {
    return { text: "", type: "poll" };
  }
  return { text: "", type: "unknown" };
}

export function normalizeContact(contact: any): Record<string, unknown> | null {
  const jid = String(contact?.id || contact?.jid || "");
  if (!jid) return null;
  return {
    type: "contact",
    jid,
    name: String(contact?.name || ""),
    notify_name: String(contact?.notify || contact?.notifyName || ""),
    verified_name: String(contact?.verifiedName || ""),
    phone_jid: String(contact?.phoneNumber || ""),
    lid_jid: String(contact?.lid || ""),
    updated_at: Date.now(),
  };
}

export function normalizeChat(chat: any): Record<string, unknown> | null {
  const jid = String(chat?.id || chat?.jid || "");
  if (!jid) return null;
  return {
    type: "chat",
    jid,
    name: String(chat?.name || ""),
    is_group: jid.endsWith("@g.us"),
    unread_count: Number(chat?.unreadCount || 0),
    archived: Boolean(chat?.archived),
    pinned: Number(chat?.pin || chat?.pinned || 0),
    muted_until: timestampMs(chat?.muteEndTime),
    last_message_id: String(chat?.lastMessage?.key?.id || ""),
    last_message_at: timestampMs(chat?.conversationTimestamp),
    updated_at: Date.now(),
  };
}

export function normalizeMessage(message: any): Record<string, unknown> | null {
  const jid = String(message?.key?.remoteJid || message?.jid || "");
  const messageId = String(message?.key?.id || message?.message_id || "");
  if (!jid || !messageId) return null;
  const extracted = extractMessage(message?.message || message);
  const participant = String(message?.key?.participant || "");
  const participantAlt = String(message?.key?.participantAlt || "");
  return {
    type: "message",
    jid,
    remote_jid_alt: String(message?.key?.remoteJidAlt || ""),
    participant,
    participant_alt: participantAlt,
    sender: participant || participantAlt || jid,
    text: extracted.text,
    message_type: extracted.type,
    message_id: messageId,
    from_me: Boolean(message?.key?.fromMe),
    message_at: timestampMs(message?.messageTimestamp),
    quoted_message_id: String(
      unwrapMessage(message?.message)?.extendedTextMessage?.contextInfo?.stanzaId || ""
    ),
    updated_at: Date.now(),
  };
}

export function normalizeHistory(history: any): Record<string, unknown> {
  return {
    type: "history",
    is_latest: Boolean(history?.isLatest),
    progress: Number(history?.progress || 0),
    message_count: (history?.messages || []).length,
  };
}
