import { TurnAssembler } from './jarvis-turn';

const IDLE_MS = 750;
const INITIAL_TOOL_WAIT_MS = 220;
const MAX_TOOL_WAIT_MS = 2_000;

interface TranscriptCallbacks {
  onInput: (text: string, finished: boolean) => void;
  onOutput: (text: string, finished: boolean) => void;
}

export class GeminiTranscriptCoordinator {
  private inputBuffer = '';
  private outputBuffer = '';
  private outputTimer: ReturnType<typeof setTimeout> | null = null;
  private inputUpdatedAt = 0;
  private readonly inputAssembler: TurnAssembler;

  constructor(private readonly callbacks: TranscriptCallbacks) {
    this.inputAssembler = new TurnAssembler({
      onPartial: (text) => callbacks.onInput(text, false),
      onFinal: (text) => callbacks.onInput(text, true),
    });
  }

  reset(): void {
    this.inputAssembler.reset();
    this.inputBuffer = '';
    this.inputUpdatedAt = Date.now();
  }

  appendInput(chunk: string): void {
    if (!chunk) return;
    this.inputBuffer += chunk;
    this.inputUpdatedAt = Date.now();
    // Provider fragment boundaries are not human-turn boundaries.
    this.inputAssembler.append(chunk, false);
  }

  appendOutput(chunk: string): void {
    if (!chunk) return;
    this.outputBuffer += chunk;
    this.callbacks.onOutput(this.outputBuffer, false);
    if (this.outputTimer !== null) clearTimeout(this.outputTimer);
    this.outputTimer = setTimeout(() => this.finalizeOutput(), IDLE_MS);
  }

  finalizeInput(): void {
    this.inputAssembler.commit();
    this.inputBuffer = '';
  }

  finalizeOutput(): void {
    if (this.outputTimer !== null) clearTimeout(this.outputTimer);
    this.outputTimer = null;
    const text = this.outputBuffer.trim();
    this.outputBuffer = '';
    if (text) this.callbacks.onOutput(text, true);
  }

  async waitForInputBeforeTool(): Promise<void> {
    const startedAt = Date.now();
    await new Promise((resolve) => setTimeout(resolve, INITIAL_TOOL_WAIT_MS));
    while (
      this.inputBuffer &&
      Date.now() - this.inputUpdatedAt < IDLE_MS &&
      Date.now() - startedAt < MAX_TOOL_WAIT_MS
    ) {
      await new Promise((resolve) => setTimeout(resolve, 40));
    }
    this.finalizeInput();
  }

  invalidate(): void {
    this.inputAssembler.invalidate();
    if (this.outputTimer !== null) clearTimeout(this.outputTimer);
    this.outputTimer = null;
    this.inputBuffer = '';
    this.outputBuffer = '';
  }
}
