import assert from "node:assert/strict";
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
