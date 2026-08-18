import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  JarvisStartupTimeoutError,
  loadOptionalJarvisContext,
} from './jarvis-startup';

describe('Jarvis optional startup context', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('returns canonical context when it is available', async () => {
    const value = await loadOptionalJarvisContext({
      load: async () => 'canonical',
      fallback: () => 'local',
      timeoutMs: 100,
      label: 'history',
    });

    expect(value).toBe('canonical');
  });

  it('aborts a stalled request and falls back without blocking startup', async () => {
    vi.useFakeTimers();
    let signal: AbortSignal | undefined;
    const onFallback = vi.fn();
    const result = loadOptionalJarvisContext({
      load: async (requestSignal) => {
        signal = requestSignal;
        return new Promise<string>(() => undefined);
      },
      fallback: () => 'local',
      timeoutMs: 2_000,
      label: 'history',
      onFallback,
    });

    await vi.advanceTimersByTimeAsync(2_000);

    await expect(result).resolves.toBe('local');
    expect(signal?.aborted).toBe(true);
    expect(onFallback).toHaveBeenCalledWith(expect.any(JarvisStartupTimeoutError));
  });

  it('uses the fallback for an immediate transport error', async () => {
    const failure = new Error('offline');
    const onFallback = vi.fn();
    const value = await loadOptionalJarvisContext({
      load: async () => { throw failure; },
      fallback: () => 'local',
      timeoutMs: 100,
      label: 'events',
      onFallback,
    });

    expect(value).toBe('local');
    expect(onFallback).toHaveBeenCalledWith(failure);
  });
});
