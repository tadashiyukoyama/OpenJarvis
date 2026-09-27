import { describe, expect, it } from 'vitest';
import { CODEX_BRAIN_ID, publicBrainModel } from './single-brain';

describe('public single-brain routing', () => {
  it('always resolves the web surface to Codex', () => {
    expect(publicBrainModel(false, 'ollama-qwen')).toBe(CODEX_BRAIN_ID);
    expect(publicBrainModel(false, 'gemini-3.1-pro')).toBe(CODEX_BRAIN_ID);
    expect(publicBrainModel(false, '')).toBe(CODEX_BRAIN_ID);
  });

  it('preserves the desktop model workspace', () => {
    expect(publicBrainModel(true, 'ollama-qwen')).toBe('ollama-qwen');
  });
});
