import type { WASocket } from "@whiskeysockets/baileys";
import { lstatSync } from "node:fs";
import { isAbsolute, relative, resolve } from "node:path";

type Command = Record<string, unknown>;
type Emit = (event: Record<string, unknown>) => void;

const MAX_TEXT = 4_000;
const MAX_PARTICIPANTS = 100;

function stringValue(value: unknown, limit = 256): string {
  return String(value || "").trim().slice(0, limit);
}

function hasSymlinkComponent(value: string): boolean {
  let current = resolve(value);
  while (true) {
    try {
      if (lstatSync(current).isSymbolicLink()) return true;
    } catch {
      // The regular-file check below reports a missing component uniformly.
    }
    const parent = resolve(current, "..");
    if (parent === current) return false;
    current = parent;
  }
}

function messageKey(command: Command): Record<string, unknown> {
  return {
    remoteJid: stringValue(command.jid, 160),
    ...(stringValue(command.remoteJidAlt, 160)
      ? { remoteJidAlt: stringValue(command.remoteJidAlt, 160) }
      : {}),
    id: stringValue(command.messageId, 256),
    fromMe: Boolean(command.fromMe),
    ...(stringValue(command.participant, 160)
      ? { participant: stringValue(command.participant, 160) }
      : {}),
    ...(stringValue(command.participantAlt, 160)
      ? { participantAlt: stringValue(command.participantAlt, 160) }
      : {}),
  };
}

function quotedMessage(command: Command): Record<string, unknown> {
  return {
    key: messageKey(command),
    message: { conversation: stringValue(command.quotedText, MAX_TEXT) },
  };
}

function mediaContent(command: Command): Record<string, unknown> {
  const kind = stringValue(command.mediaType, 16);
  if (!["image", "video", "audio", "document"].includes(kind)) {
    throw new Error("Unsupported media type");
  }
  const filePath = stringValue(command.filePath, 4_096);
  const url = stringValue(command.url, 2_000);
  let media: Record<string, unknown>;
  if (filePath) {
    if (hasSymlinkComponent(filePath)) {
      throw new Error("Media file cannot contain a symlink");
    }
    const root = resolve(
      String(process.env.OPENJARVIS_ARTIFACT_ROOT || "F:/agente/artifacts/registry"),
    );
    const candidate = resolve(filePath);
    const escaped = relative(root, candidate);
    if (!isAbsolute(candidate) || escaped === ".." || escaped.startsWith("../") || escaped.startsWith("..\\")) {
      throw new Error("Media file is outside the controlled artifact root");
    }
    try {
      if (!lstatSync(candidate).isFile()) throw new Error("Media file is not a regular file");
    } catch {
      throw new Error("Media file is unavailable");
    }
    media = { url: candidate };
  } else {
    if (!url.startsWith("https://")) {
      throw new Error("Media URL must use HTTPS");
    }
    media = { url };
  }
  const content: Record<string, unknown> = { [kind]: media };
  const caption = stringValue(command.caption, MAX_TEXT);
  if (caption && kind !== "audio") content.caption = caption;
  if (kind === "audio") content.ptt = Boolean(command.voiceNote);
  if (kind === "document") {
    content.mimetype = stringValue(command.mimetype, 120) || "application/octet-stream";
    content.fileName = stringValue(command.fileName, 240) || "arquivo";
  }
  return content;
}

function sendContent(command: Command): Record<string, unknown> {
  const kind = stringValue(command.kind, 16) || "text";
  if (kind === "text" || kind === "reply") {
    const content: Record<string, unknown> = {
      text: stringValue(command.text, MAX_TEXT),
    };
    if (kind === "reply") content.__quoted = quotedMessage(command);
    return content;
  }
  if (kind === "media") return mediaContent(command);
  if (kind === "poll") {
    const values = Array.isArray(command.values)
      ? command.values.map((value) => stringValue(value, 240)).filter(Boolean).slice(0, 20)
      : [];
    if (values.length < 2) throw new Error("A poll needs at least two options");
    return {
      poll: {
        name: stringValue(command.text, 240),
        values,
        selectableCount: Math.max(1, Math.min(values.length, Number(command.selectableCount || 1))),
      },
    };
  }
  if (kind === "reaction") {
    return { react: { text: stringValue(command.reaction, 16), key: messageKey(command) } };
  }
  throw new Error("Unsupported WhatsApp send kind");
}

export async function executeCommand(
  sock: WASocket,
  command: Command,
  emit: Emit,
): Promise<boolean> {
  const type = stringValue(command.type, 32);
  const commandId = stringValue(command.commandId, 96);
  if (type === "send") {
    const jid = stringValue(command.jid, 160);
    const content = sendContent(command);
    const quoted = (content as { __quoted?: unknown }).__quoted;
    delete content.__quoted;
    const options: Record<string, unknown> = quoted ? { quoted } : {};
    const statusJids = Array.isArray(command.statusJids)
      ? command.statusJids.map((value) => stringValue(value, 160)).slice(0, MAX_PARTICIPANTS)
      : [];
    if (jid === "status@broadcast") {
      options.broadcast = true;
      if (statusJids.length) options.statusJidList = statusJids;
    }
    const sent = await sock.sendMessage(jid, content as any, options as any);
    emit({
      type: "command_ok",
      command: type,
      command_id: commandId,
      message_id: sent?.key?.id || "",
    });
    return true;
  }
  if (type === "read") {
    const keys = Array.isArray(command.keys) ? command.keys.slice(0, 50) : [];
    await sock.readMessages(keys as any);
    emit({ type: "command_ok", command: type, command_id: commandId, count: keys.length });
    return true;
  }
  if (type === "chat_modify") {
    const jid = stringValue(command.jid, 160);
    const operation = stringValue(command.operation, 16);
    const modification =
      operation === "archive"
        ? { archive: Boolean(command.enabled), lastMessages: [] }
        : operation === "pin"
          ? { pin: Boolean(command.enabled) }
          : operation === "mute"
            ? { mute: command.enabled ? Date.now() + 86_400_000 : null }
            : null;
    if (!modification) throw new Error("Unsupported chat operation");
    await sock.chatModify(modification as any, jid);
    emit({ type: "command_ok", command: type, command_id: commandId, jid, operation });
    return true;
  }
  if (type === "group_metadata") {
    const metadata = await sock.groupMetadata(stringValue(command.jid, 160));
    emit({
      type: "command_ok",
      command: type,
      command_id: commandId,
      jid: metadata.id,
      subject: metadata.subject,
      owner: metadata.owner || "",
      participants: (metadata.participants || []).slice(0, MAX_PARTICIPANTS),
    });
    return true;
  }
  if (type === "group_create") {
    const participants = Array.isArray(command.participants)
      ? command.participants.map((value) => stringValue(value, 160)).slice(0, MAX_PARTICIPANTS)
      : [];
    const metadata = await sock.groupCreate(stringValue(command.subject, 240), participants);
    emit({
      type: "command_ok",
      command: type,
      command_id: commandId,
      jid: metadata.id,
      subject: metadata.subject,
    });
    return true;
  }
  if (type === "group_subject") {
    await sock.groupUpdateSubject(stringValue(command.jid, 160), stringValue(command.subject, 240));
    emit({
      type: "command_ok",
      command: type,
      command_id: commandId,
      jid: stringValue(command.jid, 160),
    });
    return true;
  }
  if (type === "privacy") {
    if (command.operation === "read") {
      emit({
        type: "command_ok",
        command: type,
        command_id: commandId,
        settings: await sock.fetchPrivacySettings(true),
      });
      return true;
    }
    const setting = stringValue(command.setting, 40);
    const value = stringValue(command.value, 40) as any;
    const methods: Record<string, (input: any) => Promise<void>> = {
      online: (input) => sock!.updateOnlinePrivacy(input),
      last_seen: (input) => sock!.updateLastSeenPrivacy(input),
      profile_picture: (input) => sock!.updateProfilePicturePrivacy(input),
      status: (input) => sock!.updateStatusPrivacy(input),
      read_receipts: (input) => sock!.updateReadReceiptsPrivacy(input),
      groups_add: (input) => sock!.updateGroupsAddPrivacy(input),
    };
    const update = methods[setting];
    if (!update) throw new Error("Unsupported privacy setting");
    await update(value);
    emit({ type: "command_ok", command: type, command_id: commandId, setting });
    return true;
  }
  if (type === "profile_status") {
    await sock.updateProfileStatus(stringValue(command.text, 140));
    emit({ type: "command_ok", command: type, command_id: commandId });
    return true;
  }
  return false;
}
