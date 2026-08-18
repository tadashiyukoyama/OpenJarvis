import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";
import {
  AuthStateInconsistentError,
  persistCredentialSnapshot,
  recoverCredentialSnapshot,
} from "./auth-state.js";

async function withAuthDirectory(
  run: (directory: string) => Promise<void>
): Promise<void> {
  const directory = await mkdtemp(join(process.cwd(), ".auth-state-test-"));
  try {
    await run(directory);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

test("persists matching valid primary and backup snapshots", async () => {
  await withAuthDirectory(async (directory) => {
    await persistCredentialSnapshot(directory, {
      registrationId: 42,
      identity: Buffer.from("safe-test-value"),
    });

    const primary = await readFile(join(directory, "creds.json"), "utf8");
    const backup = await readFile(join(directory, "creds.backup.json"), "utf8");
    assert.ok(primary.length > 0);
    assert.equal(primary, backup);
  });
});

test("restores an invalid primary from the last valid backup", async () => {
  await withAuthDirectory(async (directory) => {
    await persistCredentialSnapshot(directory, { registrationId: 77 });
    const expected = await readFile(join(directory, "creds.backup.json"), "utf8");
    await writeFile(join(directory, "creds.json"), "", "utf8");

    assert.equal(await recoverCredentialSnapshot(directory), true);
    assert.equal(
      await readFile(join(directory, "creds.json"), "utf8"),
      expected
    );
  });
});

test("accepts a completely empty directory as a fresh authentication generation", async () => {
  await withAuthDirectory(async (directory) => {
    assert.equal(await recoverCredentialSnapshot(directory), false);
  });
});

test("fails closed when credential artifacts exist without a valid snapshot", async () => {
  await withAuthDirectory(async (directory) => {
    await writeFile(join(directory, "creds.json"), "", "utf8");
    await writeFile(join(directory, "app-state-sync-key-test.json"), "{}", "utf8");

    await assert.rejects(
      recoverCredentialSnapshot(directory),
      AuthStateInconsistentError
    );
    assert.equal(await readFile(join(directory, "creds.json"), "utf8"), "");
    assert.equal(
      await readFile(join(directory, "app-state-sync-key-test.json"), "utf8"),
      "{}"
    );
  });
});
