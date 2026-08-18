import {
  BufferJSON,
  useMultiFileAuthState,
} from "@whiskeysockets/baileys";
import {
  mkdir,
  readFile,
  readdir,
  rename,
  rm,
  writeFile,
} from "fs/promises";
import { join } from "path";

const CREDENTIALS_FILE = "creds.json";
const CREDENTIALS_BACKUP_FILE = "creds.backup.json";

export class AuthStateInconsistentError extends Error {
  constructor() {
    super(
      "AUTH_STATE_INCONSISTENT: authentication artifacts exist without a valid credential snapshot"
    );
    this.name = "AuthStateInconsistentError";
  }
}

function parseCredentialSnapshot(serialized: string): object | null {
  if (!serialized.trim()) return null;
  try {
    const parsed = JSON.parse(serialized, BufferJSON.reviver);
    if (!parsed || typeof parsed !== "object" || Object.keys(parsed).length === 0) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

async function readValidSnapshot(path: string): Promise<string | null> {
  try {
    const serialized = await readFile(path, "utf8");
    return parseCredentialSnapshot(serialized) ? serialized : null;
  } catch {
    return null;
  }
}

async function atomicWrite(path: string, serialized: string): Promise<void> {
  const temporary = `${path}.${process.pid}.${Date.now()}.tmp`;
  try {
    await writeFile(temporary, serialized, { encoding: "utf8", flag: "wx" });
    await rename(temporary, path);
  } finally {
    await rm(temporary, { force: true }).catch(() => undefined);
  }
}

async function authDirectoryHasArtifacts(authDir: string): Promise<boolean> {
  try {
    return (await readdir(authDir)).length > 0;
  } catch {
    return false;
  }
}

export async function recoverCredentialSnapshot(authDir: string): Promise<boolean> {
  await mkdir(authDir, { recursive: true });
  const primaryPath = join(authDir, CREDENTIALS_FILE);
  const backupPath = join(authDir, CREDENTIALS_BACKUP_FILE);
  const primary = await readValidSnapshot(primaryPath);
  if (primary) {
    if (!(await readValidSnapshot(backupPath))) {
      await atomicWrite(backupPath, primary);
    }
    return false;
  }

  const backup = await readValidSnapshot(backupPath);
  if (!backup) {
    if (await authDirectoryHasArtifacts(authDir)) {
      throw new AuthStateInconsistentError();
    }
    return false;
  }
  await atomicWrite(primaryPath, backup);
  return true;
}

export async function persistCredentialSnapshot(
  authDir: string,
  credentials: object
): Promise<void> {
  await mkdir(authDir, { recursive: true });
  const serialized = JSON.stringify(credentials, BufferJSON.replacer);
  if (!parseCredentialSnapshot(serialized)) {
    throw new Error("Refusing to persist an invalid authentication snapshot");
  }

  await atomicWrite(join(authDir, CREDENTIALS_FILE), serialized);
  await atomicWrite(join(authDir, CREDENTIALS_BACKUP_FILE), serialized);
}

export async function useResilientMultiFileAuthState(authDir: string) {
  await recoverCredentialSnapshot(authDir);
  const { state } = await useMultiFileAuthState(authDir);
  let saveQueue: Promise<void> = Promise.resolve();

  const saveCreds = (): Promise<void> => {
    const operation = saveQueue.then(() =>
      persistCredentialSnapshot(authDir, state.creds)
    );
    saveQueue = operation.catch(() => undefined);
    return operation;
  };

  return { state, saveCreds };
}
