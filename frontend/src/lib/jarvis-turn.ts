export interface TurnAssemblerCallbacks {
  onPartial: (text: string) => void;
  onFinal: (text: string) => void;
}

/**
 * Collects one Gemini input-transcription turn.
 *
 * Gemini may deliver several transcription fragments for the same utterance.
 * A fragment is never an authorization boundary. The owner explicitly calls
 * commit when Gemini reports a turn boundary or immediately before handling a
 * function call. Once committed, duplicate final events are ignored until the
 * next fragment starts a new turn.
 */
export class TurnAssembler {
  private buffer = '';
  private committed = false;
  private invalidated = false;
  private lastCommittedText = '';

  constructor(private readonly callbacks: TurnAssemblerCallbacks) {}

  append(chunk: string, finished = false): void {
    if (this.invalidated || !chunk) return;
    if (this.committed) {
      if (normalizeTurnText(chunk) === normalizeTurnText(this.lastCommittedText)) return;
      this.buffer = '';
      this.committed = false;
    }
    this.buffer += chunk;
    this.callbacks.onPartial(this.buffer);
    if (finished) this.commit();
  }

  commit(): string | null {
    if (this.invalidated || this.committed) return null;
    const text = this.buffer.trim();
    this.committed = true;
    this.buffer = '';
    if (!text) return null;
    this.lastCommittedText = text;
    this.callbacks.onFinal(text);
    return text;
  }

  invalidate(): void {
    this.invalidated = true;
    this.buffer = '';
    this.committed = true;
    this.lastCommittedText = '';
  }

  reset(): void {
    this.invalidated = false;
    this.buffer = '';
    this.committed = false;
    this.lastCommittedText = '';
  }
}

function normalizeTurnText(text: string): string {
  return text.trim().replace(/\s+/g, ' ').toLocaleLowerCase();
}

export const jarvisTurnInternals = { TurnAssembler };
