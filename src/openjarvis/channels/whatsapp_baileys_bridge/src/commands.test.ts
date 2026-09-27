import assert from "node:assert/strict";
import { mkdirSync, writeFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

import { executeCommand } from "./commands.js";

test("reaction uses the exact PN/LID message key and emits a correlated ack", async () => {
  const calls: unknown[][] = [];
  const emitted: Record<string, unknown>[] = [];
  const socket = {
    sendMessage: async (...args: unknown[]) => {
      calls.push(args);
      return { key: { id: "reaction-result" } };
    },
  };

  const handled = await executeCommand(
    socket as any,
    {
      type: "send",
      kind: "reaction",
      commandId: "wac-test",
      jid: "12345-67890@g.us",
      remoteJidAlt: "123456789012345@lid",
      messageId: "message-1",
      participant: "5511999999999@s.whatsapp.net",
      participantAlt: "998877665544332@lid",
      fromMe: false,
      reaction: "👍",
    },
    (event) => emitted.push(event),
  );

  assert.equal(handled, true);
  assert.deepEqual((calls[0][1] as any).react.key, {
    remoteJid: "12345-67890@g.us",
    remoteJidAlt: "123456789012345@lid",
    id: "message-1",
    fromMe: false,
    participant: "5511999999999@s.whatsapp.net",
    participantAlt: "998877665544332@lid",
  });
  assert.equal(emitted[0].type, "command_ok");
  assert.equal(emitted[0].command_id, "wac-test");
});

test("all supported command namespaces produce one correlated acknowledgement", async () => {
  const emitted: Record<string, unknown>[] = [];
  const calls: string[] = [];
  const socket = {
    sendMessage: async () => {
      calls.push("send");
      return { key: { id: "sent-1" } };
    },
    readMessages: async () => { calls.push("read"); },
    chatModify: async () => { calls.push("chat_modify"); },
    groupMetadata: async () => {
      calls.push("group_metadata");
      return { id: "group@g.us", subject: "Grupo", participants: [] };
    },
    groupCreate: async () => {
      calls.push("group_create");
      return { id: "new-group@g.us", subject: "Novo" };
    },
    groupUpdateSubject: async () => { calls.push("group_subject"); },
    fetchPrivacySettings: async () => {
      calls.push("privacy_read");
      return { last: "contacts" };
    },
    updateLastSeenPrivacy: async () => { calls.push("privacy_update"); },
    updateProfileStatus: async () => { calls.push("profile_status"); },
  };
  const commands: Record<string, unknown>[] = [
    { type: "send", kind: "text", jid: "1@s.whatsapp.net", text: "Olá" },
    { type: "read", keys: [{ remoteJid: "1@s.whatsapp.net", id: "m1" }] },
    { type: "chat_modify", operation: "archive", jid: "1@s.whatsapp.net", enabled: true },
    { type: "group_metadata", jid: "group@g.us" },
    { type: "group_create", subject: "Novo", participants: ["1@s.whatsapp.net"] },
    { type: "group_subject", jid: "group@g.us", subject: "Assunto" },
    { type: "privacy", operation: "read" },
    { type: "privacy", operation: "update", setting: "last_seen", value: "contacts" },
    { type: "profile_status", text: "Disponível" },
  ];

  for (const [index, command] of commands.entries()) {
    const commandId = `command-${index}`;
    const handled = await executeCommand(
      socket as any,
      { ...command, commandId },
      (event) => emitted.push(event),
    );
    assert.equal(handled, true);
    assert.equal(emitted[emitted.length - 1]?.command_id, commandId);
  }

  assert.deepEqual(calls, [
    "send",
    "read",
    "chat_modify",
    "group_metadata",
    "group_create",
    "group_subject",
    "privacy_read",
    "privacy_update",
    "profile_status",
  ]);
});

test("unsupported commands fail closed without acknowledgement", async () => {
  const emitted: Record<string, unknown>[] = [];
  const handled = await executeCommand(
    {} as any,
    { type: "voice_call", commandId: "unsupported" },
    (event) => emitted.push(event),
  );

  assert.equal(handled, false);
  assert.deepEqual(emitted, []);
});

test("media command accepts only a local artifact under the controlled root", async () => {
  const root = join(process.cwd(), "test-artifacts");
  const filePath = join(root, "sample.png");
  mkdirSync(root, { recursive: true });
  writeFileSync(filePath, "fixture");
  const previousRoot = process.env.OPENJARVIS_ARTIFACT_ROOT;
  process.env.OPENJARVIS_ARTIFACT_ROOT = root;
  const emitted: Record<string, unknown>[] = [];
  const calls: unknown[][] = [];
  const socket = {
    sendMessage: async (...args: unknown[]) => {
      calls.push(args);
      return { key: { id: "media-1" } };
    },
  };
  const handled = await executeCommand(
    socket as any,
    {
      type: "send",
      kind: "media",
      commandId: "media-1",
      jid: "5511999999999@s.whatsapp.net",
      mediaType: "image",
      mimetype: "image/png",
      fileName: "sample.png",
      filePath,
    },
    (event) => emitted.push(event),
  );
  assert.equal(handled, true);
  assert.equal((calls[0][1] as any).image.url, filePath);
  assert.equal(emitted[0].command_id, "media-1");
  if (previousRoot === undefined) delete process.env.OPENJARVIS_ARTIFACT_ROOT;
  else process.env.OPENJARVIS_ARTIFACT_ROOT = previousRoot;
  rmSync(root, { recursive: true, force: true });
});

test("audio media command marks Baileys content as a PTT voice note", async () => {
  const root = join(process.cwd(), "test-artifacts-audio");
  const filePath = join(root, "sample.ogg");
  mkdirSync(root, { recursive: true });
  writeFileSync(filePath, "OggS fixture");
  const previousRoot = process.env.OPENJARVIS_ARTIFACT_ROOT;
  process.env.OPENJARVIS_ARTIFACT_ROOT = root;
  const emitted: Record<string, unknown>[] = [];
  const calls: unknown[][] = [];
  const socket = {
    sendMessage: async (...args: unknown[]) => {
      calls.push(args);
      return { key: { id: "audio-1" } };
    },
  };
  const handled = await executeCommand(
    socket as any,
    {
      type: "send",
      kind: "media",
      commandId: "audio-1",
      jid: "5511999999999@s.whatsapp.net",
      mediaType: "audio",
      mimetype: "audio/ogg",
      fileName: "sample.ogg",
      filePath,
      voiceNote: true,
    },
    (event) => emitted.push(event),
  );
  assert.equal(handled, true);
  assert.equal((calls[0][1] as any).audio.url, filePath);
  assert.equal((calls[0][1] as any).ptt, true);
  assert.equal(emitted[0].command_id, "audio-1");
  if (previousRoot === undefined) delete process.env.OPENJARVIS_ARTIFACT_ROOT;
  else process.env.OPENJARVIS_ARTIFACT_ROOT = previousRoot;
  rmSync(root, { recursive: true, force: true });
});

test("media payloads preserve document MIME/filename and map to Baileys kinds", async () => {
  const root = join(process.cwd(), "test-artifacts-mime");
  mkdirSync(root, { recursive: true });
  const previousRoot = process.env.OPENJARVIS_ARTIFACT_ROOT;
  process.env.OPENJARVIS_ARTIFACT_ROOT = root;
  try {
    const cases = [
      { name: "sample.pdf", mediaType: "document", mimetype: "application/pdf", key: "document" },
      {
        name: "sample.docx",
        mediaType: "document",
        mimetype: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        key: "document",
      },
      { name: "sample.png", mediaType: "image", mimetype: "image/png", key: "image" },
      { name: "sample.jpg", mediaType: "image", mimetype: "image/jpeg", key: "image" },
      { name: "sample.ogg", mediaType: "audio", mimetype: "audio/ogg", key: "audio" },
    ] as const;
    for (const [index, item] of cases.entries()) {
      const filePath = join(root, item.name);
      writeFileSync(filePath, `${item.key} fixture`);
      const calls: unknown[][] = [];
      const socket = {
        sendMessage: async (...args: unknown[]) => {
          calls.push(args);
          return { key: { id: `mime-${index}` } };
        },
      };
      const handled = await executeCommand(
        socket as any,
        {
          type: "send",
          kind: "media",
          commandId: `mime-${index}`,
          jid: "5511999999999@s.whatsapp.net",
          mediaType: item.mediaType,
          mimetype: item.mimetype,
          fileName: item.name,
          filePath,
        },
        () => undefined,
      );
      assert.equal(handled, true);
      const payload = calls[0][1] as any;
      assert.equal(payload[item.key].url, filePath);
      if (item.key === "document") {
        assert.equal(payload.mimetype, item.mimetype);
        assert.equal(payload.fileName, item.name);
      }
      if (item.key === "audio") assert.equal(payload.ptt, false);
    }
  } finally {
    if (previousRoot === undefined) delete process.env.OPENJARVIS_ARTIFACT_ROOT;
    else process.env.OPENJARVIS_ARTIFACT_ROOT = previousRoot;
    rmSync(root, { recursive: true, force: true });
  }
});

test("unknown media payload kind fails closed without sending", async () => {
  const root = join(process.cwd(), "test-artifacts-unknown");
  mkdirSync(root, { recursive: true });
  const filePath = join(root, "sample.bin");
  writeFileSync(filePath, "unknown fixture");
  const previousRoot = process.env.OPENJARVIS_ARTIFACT_ROOT;
  process.env.OPENJARVIS_ARTIFACT_ROOT = root;
  const calls: unknown[][] = [];
  try {
    const socket = {
      sendMessage: async (...args: unknown[]) => {
        calls.push(args);
        return { key: { id: "unknown-1" } };
      },
    };
    await assert.rejects(
      executeCommand(
        socket as any,
        {
          type: "send",
          kind: "media",
          commandId: "unknown-1",
          jid: "5511999999999@s.whatsapp.net",
          mediaType: "application",
          mimetype: "application/x-unknown",
          fileName: "sample.bin",
          filePath,
        },
        () => undefined,
      ),
      /Unsupported media type/,
    );
    assert.equal(calls.length, 0);
  } finally {
    if (previousRoot === undefined) delete process.env.OPENJARVIS_ARTIFACT_ROOT;
    else process.env.OPENJARVIS_ARTIFACT_ROOT = previousRoot;
    rmSync(root, { recursive: true, force: true });
  }
});
