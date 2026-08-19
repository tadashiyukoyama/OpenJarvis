import { afterEach, describe, expect, it, vi } from 'vitest';
import { PcmPlayback } from './gemini-live-audio';
import { AdaptivePcmQueue } from './worklets/gemini-live-playback-worklet.js';

describe('Adaptive Gemini PCM queue', () => {
  it('prebuffers before playback and adapts after an underrun', () => {
    const queue = new AdaptivePcmQueue({
      sampleRate: 1_000,
      prebufferMs: 180,
      minimumPrebufferMs: 120,
      maximumPrebufferMs: 3_000,
      prebufferStepMs: 40,
      prebufferGrowthFactor: 2,
    });
    const output = new Float32Array(100);

    queue.push(new Float32Array(150).fill(0.5));
    expect(queue.pull(output).state).toBe('buffering');
    expect(output.every((sample) => sample === 0)).toBe(true);

    queue.push(new Float32Array(150).fill(0.5));
    expect(queue.pull(output).state).toBe('playing');
    expect(output[0]).toBe(0.5);

    const underrun = queue.pull(new Float32Array(250));
    expect(underrun.state).toBe('buffering');
    expect(underrun.underruns).toBe(1);
    expect(underrun.prebufferMs).toBe(360);
  });

  it('grows exponentially to cover measured multi-second delivery gaps', () => {
    const queue = new AdaptivePcmQueue({
      sampleRate: 1_000,
      prebufferMs: 900,
      minimumPrebufferMs: 120,
      maximumPrebufferMs: 3_000,
      prebufferStepMs: 250,
      prebufferGrowthFactor: 2,
    });

    const forceUnderrun = () => {
      const target = queue.snapshot().prebufferMs;
      queue.push(new Float32Array(target));
      queue.pull(new Float32Array(target + 1));
      return queue.snapshot();
    };

    expect(forceUnderrun().prebufferMs).toBe(1_800);
    expect(forceUnderrun().prebufferMs).toBe(3_000);
    expect(forceUnderrun().prebufferMs).toBe(3_000);
  });

  it('bounds memory and keeps the newest audio when the producer overruns', () => {
    const queue = new AdaptivePcmQueue({
      sampleRate: 1_000,
      maximumPrebufferMs: 480,
      capacityMs: 500,
    });
    queue.push(new Float32Array(9_000).fill(0.25));

    const metrics = queue.snapshot();
    expect(metrics.queuedMs).toBe(960);
    expect(metrics.droppedSamples).toBe(8_040);
  });

  it('preserves a long Live response that arrives faster than playback', () => {
    const queue = new AdaptivePcmQueue({ sampleRate: 1_000 });
    queue.push(new Float32Array(60_000).fill(0.25));

    const metrics = queue.snapshot();
    expect(metrics.queuedMs).toBe(60_000);
    expect(metrics.droppedSamples).toBe(0);
  });
});

describe('PcmPlayback AudioWorklet transport', () => {
  const addModule = vi.fn(async () => {});
  const postMessage = vi.fn();
  const disconnect = vi.fn();

  class FakeAudioContext {
    state = 'running';
    sampleRate = 24_000;
    currentTime = 0;
    destination = {} as AudioDestinationNode;
    audioWorklet = { addModule } as unknown as AudioWorklet;
    resume = vi.fn(async () => {});
    close = vi.fn(async () => {});
    createBuffer = vi.fn();
    createBufferSource = vi.fn();
  }

  class FakeAudioWorkletNode {
    port = { postMessage, onmessage: null };
    connect = vi.fn();
    disconnect = disconnect;
  }

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('loads one worklet and transfers PCM chunks into its continuous queue', async () => {
    vi.stubGlobal('AudioContext', FakeAudioContext);
    vi.stubGlobal('AudioWorkletNode', FakeAudioWorkletNode);
    const pcm = new Int16Array([0, 16_384, -16_384]);
    const base64 = btoa(String.fromCharCode(...new Uint8Array(pcm.buffer)));
    const playback = new PcmPlayback();

    await playback.play(base64);
    await playback.play(base64);

    expect(addModule).toHaveBeenCalledTimes(1);
    expect(postMessage).toHaveBeenCalledTimes(2);
    expect(postMessage.mock.calls[0][0]).toMatchObject({ type: 'push' });
    expect(postMessage.mock.calls[0][0].samples).toBeInstanceOf(Float32Array);
    expect(playback.snapshot()).toMatchObject({
      transport: 'worklet',
      transportReason: 'audio-worklet-active',
      audioContextState: 'running',
      audioContextSampleRate: 24_000,
    });

    playback.interrupt();
    expect(postMessage).toHaveBeenLastCalledWith({ type: 'reset' });
    await playback.close();
    expect(disconnect).toHaveBeenCalledTimes(1);
  });
});
