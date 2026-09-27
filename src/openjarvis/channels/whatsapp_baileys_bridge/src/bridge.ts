/**
 * OpenJarvis WhatsApp Baileys Bridge
 *
 * JSON-line protocol on stdio:
 *
 * Input commands (stdin):
 *   {"type":"send","jid":"<jid>","text":"<message>"}
 *   {"type":"read","keys":[{"remoteJid":"<jid>","id":"<id>"}]}
 *   {"type":"disconnect"}
 *
 * Output events (stdout):
 *   {"type":"message","jid":"<jid>","sender":"<sender>","text":"<text>","message_id":"<id>"}
 *   {"type":"status","status":"connecting"|"connected"|"disconnected"}
 *   {"type":"qr","data":"<qr-string>"}
 *   {"type":"error","scope":"connection"|"operation"|"protocol",...}
 */

import makeWASocket, {
  Browsers,
  DisconnectReason,
  fetchLatestWaWebVersion,
  WASocket,
  downloadMediaMessage,
} from "@whiskeysockets/baileys";
import { createHash, randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import * as readline from "readline";
import {
  normalizeChat,
  normalizeContact,
  normalizeHistory,
  normalizeMessage,
} from "./events.js";
import { executeCommand } from "./commands.js";
import {
  AuthStateInconsistentError,
  useResilientMultiFileAuthState,
} from "./auth-state.js";

const TRANSIENT_DISCONNECT_REASONS = new Set<number>([
  DisconnectReason.connectionClosed,
  DisconnectReason.connectionLost,
  DisconnectReason.timedOut,
  DisconnectReason.restartRequired,
  DisconnectReason.unavailableService,
]);

function terminalDisconnectReason(
  statusCode: number
): "conflict" | "failed" | "logged_out" {
  if (statusCode === DisconnectReason.loggedOut) return "logged_out";
  if (statusCode === DisconnectReason.connectionReplaced) return "conflict";
  return "failed";
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function emit(event: Record<string, unknown>): void {
  process.stdout.write(JSON.stringify(event) + "\n");
}

function parseArgs(): { authDir: string } {
  const args = process.argv.slice(2);
  let authDir = "./auth";
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--auth-dir" && i + 1 < args.length) {
      authDir = args[i + 1];
      break;
    }
  }
  return { authDir };
}

const MAX_INCOMING_MEDIA_BYTES = 12 * 1024 * 1024;
const INCOMING_MEDIA_MIME = new Set([
  "image/png",
  "image/jpeg",
  "image/webp",
  "application/pdf",
  "text/csv",
  "text/plain",
  "audio/ogg",
  "audio/mpeg",
  "audio/mp4",
  "audio/wav",
  "audio/x-wav",
  "audio/webm",
]);

function incomingMediaRoot(): string {
  return resolve(
    String(process.env.OPENJARVIS_INCOMING_MEDIA_ROOT || "F:/agente/runtime/incoming-media"),
  );
}

function safeMediaFilename(value: string, mimeType: string): string {
  const clean = value.replace(/[^A-Za-z0-9._ -]+/g, "_").trim().slice(0, 96);
  if (clean && !/[\\/]\.\.?$/.test(clean)) return clean;
  const extension: Record<string, string> = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
    "text/csv": ".csv",
    "text/plain": ".txt",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/webm": ".webm",
  };
  return `received-${Date.now()}${extension[mimeType] || ".bin"}`;
}

async function persistIncomingMedia(message: any, event: Record<string, unknown>): Promise<Record<string, unknown>> {
  const mimeType = String(event.media_mime_type || "").split(";", 1)[0].trim().toLowerCase();
  if (!INCOMING_MEDIA_MIME.has(mimeType)) {
    return { media_error: "MEDIA_MIME_NOT_ALLOWED" };
  }
  const content = await downloadMediaMessage(message, "buffer", {} as any);
  if (!Buffer.isBuffer(content) || content.length > MAX_INCOMING_MEDIA_BYTES) {
    return { media_error: "MEDIA_TOO_LARGE" };
  }
  const root = incomingMediaRoot();
  await mkdir(root, { recursive: true });
  const artifactId = `incoming-${randomUUID()}`;
  const filename = safeMediaFilename(String(event.media_filename || ""), mimeType);
  const target = resolve(root, `${artifactId}-${filename}`);
  const digest = createHash("sha256").update(content).digest("hex");
  await writeFile(target, content, { flag: "wx" });
  return {
    media_path: target,
    media_size: content.length,
    media_sha256: digest,
    media_filename: filename,
    media_mime_type: mimeType,
  };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  const { authDir } = parseArgs();

  const { state, saveCreds } = await useResilientMultiFileAuthState(authDir);
  const { version: waVersion } = await fetchLatestWaWebVersion();

  let sock: WASocket | null = null;
  let socketGeneration = 0;
  let terminalExitScheduled = false;

  function startSocket(): void {
    const generation = ++socketGeneration;
    const activeSocket = makeWASocket({
      auth: state,
      browser: Browsers.windows("OpenJarvis"),
      version: waVersion,
      printQRInTerminal: false,
    });
    sock = activeSocket;

    activeSocket.ev.on("creds.update", () => {
      void saveCreds().catch(() => {
        if (generation !== socketGeneration || terminalExitScheduled) return;
        terminalExitScheduled = true;
        emit({
          type: "error",
          scope: "connection",
          reason: "failed",
          message: "Authentication state could not be persisted safely",
        });
        activeSocket.end(undefined);
        setTimeout(() => process.exit(3), 25);
      });
    });

    activeSocket.ev.on("contacts.upsert", (contacts) => {
      for (const contact of contacts) {
        const event = normalizeContact(contact);
        if (event) emit(event);
      }
    });
    activeSocket.ev.on("contacts.update", (contacts) => {
      for (const contact of contacts) {
        const event = normalizeContact(contact);
        if (event) emit(event);
      }
    });
    activeSocket.ev.on("chats.upsert", (chats) => {
      for (const chat of chats) {
        const event = normalizeChat(chat);
        if (event) emit(event);
      }
    });
    activeSocket.ev.on("chats.update", (chats) => {
      for (const chat of chats) {
        const event = normalizeChat(chat);
        if (event) emit(event);
      }
    });
    activeSocket.ev.on("chats.delete", (jids) => {
      for (const jid of jids) emit({ type: "chat_deleted", jid: String(jid) });
    });
    activeSocket.ev.on("messaging-history.set", (history) => {
      for (const contact of history.contacts || []) {
        const event = normalizeContact(contact);
        if (event) emit(event);
      }
      for (const chat of history.chats || []) {
        const event = normalizeChat(chat);
        if (event) emit(event);
      }
      for (const message of history.messages || []) {
        const event = normalizeMessage(message);
        if (event) emit(event);
      }
      emit(normalizeHistory(history));
    });

    activeSocket.ev.on("connection.update", (update) => {
      if (generation !== socketGeneration || terminalExitScheduled) return;

      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        // The QR is an authentication credential. Keep it on the structured
        // stdout channel consumed by the protected API; never copy it to logs.
        emit({ type: "qr", data: qr });
      }

      if (connection === "close") {
        const rawStatusCode =
          (lastDisconnect?.error as any)?.output?.statusCode ??
          DisconnectReason.connectionClosed;
        const statusCode = Number(rawStatusCode);
        const disconnectError = lastDisconnect?.error as
          | { message?: string }
          | undefined;
        const disconnectMessage =
          disconnectError?.message || "sem detalhe fornecido pelo Baileys";

        sock = null;
        if (TRANSIENT_DISCONNECT_REASONS.has(statusCode)) {
          emit({
            type: "status",
            status: "connecting",
            reason: "reconnecting",
          });
          startSocket();
          return;
        }

        const reason = terminalDisconnectReason(statusCode);
        emit({
          type: "error",
          scope: "connection",
          code: String(statusCode),
          reason,
          message: `Conexão WhatsApp encerrada (${statusCode}): ${disconnectMessage}`,
        });
        terminalExitScheduled = true;
        // Terminal authentication/session failures require explicit user
        // action. Exit after flushing the structured event so the parent
        // cannot mistake a stale process for a reconnecting bridge.
        setTimeout(() => process.exit(2), 25);
      } else if (connection === "open") {
        emit({ type: "status", status: "connected" });
      }
    });

    activeSocket.ev.on("messages.upsert", (m) => {
      for (const msg of m.messages) {
        if (msg.message) {
          void (async () => {
            const event = normalizeMessage(msg);
            if (!event) return;
            if (event.media_type && !msg.key.fromMe) {
              try {
                Object.assign(event, await persistIncomingMedia(msg, event));
              } catch {
                event.media_error = "MEDIA_DOWNLOAD_FAILED";
              }
            }
            emit(event);
          })();
        }
      }
    });
  }

  startSocket();

  // -----------------------------------------------------------------------
  // Stdin command processing
  // -----------------------------------------------------------------------

  const rl = readline.createInterface({ input: process.stdin });

  rl.on("line", async (line: string) => {
    let cmd: Record<string, unknown>;
    try {
      cmd = JSON.parse(line);
    } catch {
      emit({ type: "error", scope: "protocol", message: "Invalid JSON on stdin" });
      return;
    }

    if (
      sock &&
      [
        "send",
        "read",
        "chat_modify",
        "group_metadata",
        "group_create",
        "group_subject",
        "privacy",
        "profile_status",
      ].includes(String(cmd.type))
    ) {
      try {
        const handled = await executeCommand(sock, cmd, emit);
        if (!handled) {
          emit({
            type: "error",
            scope: "operation",
            operation: String(cmd.type || "unknown"),
            command_id: String(cmd.commandId || ""),
            message: "Unsupported command",
          });
        }
        if (handled && cmd.type === "send" && String(cmd.text || "")) {
          const jid = String(cmd.jid || "");
          const event = normalizeMessage({
            key: { remoteJid: jid, fromMe: true, id: "" },
            message: { conversation: String(cmd.text || "") },
            messageTimestamp: Math.floor(Date.now() / 1000),
          });
          if (event) emit(event);
        }
      } catch (err: any) {
        emit({
          type: "error",
          scope: "operation",
          operation: String(cmd.type || "unknown"),
          command_id: String(cmd.commandId || ""),
          message: `Command failed: ${err.message}`,
        });
      }
    } else if (cmd.type === "history" && sock) {
      try {
        const oldest = (cmd.oldest || {}) as Record<string, unknown>;
        await sock.fetchMessageHistory(
          Math.min(50, Math.max(1, Number(cmd.limit || 50))),
          {
            remoteJid: String(cmd.jid || ""),
            id: String(oldest.message_id || ""),
            fromMe: Boolean(oldest.from_me),
          },
          Math.floor(Number(oldest.message_at || 0) / 1000)
        );
        emit({ type: "history_requested", jid: String(cmd.jid || "") });
      } catch (err: any) {
        emit({
          type: "error",
          scope: "operation",
          operation: "history",
          message: `History fetch failed: ${err.message}`,
        });
      }
    } else if (cmd.type === "disconnect") {
      terminalExitScheduled = true;
      if (sock) {
        sock.end(undefined);
      }
      emit({ type: "status", status: "disconnected" });
      process.exit(0);
    }
  });

  rl.on("close", () => {
    if (sock) {
      sock.end(undefined);
    }
    process.exit(0);
  });
}

main().catch((err) => {
  const inconsistentAuth = err instanceof AuthStateInconsistentError;
  emit({
    type: "error",
    scope: "connection",
    reason: inconsistentAuth ? "auth_inconsistent" : "failed",
    message: inconsistentAuth
      ? "O estado local do WhatsApp está inconsistente e precisa ser preservado antes de gerar um novo QR."
      : `Fatal: ${err.message}`,
  });
  process.exit(1);
});
