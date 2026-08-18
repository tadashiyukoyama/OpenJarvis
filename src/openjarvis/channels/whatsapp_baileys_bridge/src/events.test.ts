import assert from "node:assert/strict";
import test from "node:test";

import { normalizeContact, normalizeMessage } from "./events.js";

test("normalizes PN and LID aliases from a Baileys contact", () => {
  const event = normalizeContact({
    id: "123456789012345@lid",
    lid: "123456789012345@lid",
    phoneNumber: "5511999999999@s.whatsapp.net",
    name: "Klaus",
  });

  assert.equal(event?.jid, "123456789012345@lid");
  assert.equal(event?.lid_jid, "123456789012345@lid");
  assert.equal(event?.phone_jid, "5511999999999@s.whatsapp.net");
});

test("preserves the complete group message key", () => {
  const event = normalizeMessage({
    key: {
      remoteJid: "12345-67890@g.us",
      remoteJidAlt: "123456789012345@lid",
      participant: "5511999999999@s.whatsapp.net",
      participantAlt: "998877665544332@lid",
      id: "message-1",
      fromMe: false,
    },
    message: { conversation: "Mensagem" },
    messageTimestamp: 10,
  });

  assert.equal(event?.sender, "5511999999999@s.whatsapp.net");
  assert.equal(event?.remote_jid_alt, "123456789012345@lid");
  assert.equal(event?.participant, "5511999999999@s.whatsapp.net");
  assert.equal(event?.participant_alt, "998877665544332@lid");
});
