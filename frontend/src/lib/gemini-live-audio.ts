export function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
}
export function base64ToPcm(base64: string): Float32Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  const view = new DataView(bytes.buffer);
  const samples = new Float32Array(Math.floor(bytes.byteLength / 2));
  for (let index = 0; index < samples.length; index += 1) {
    samples[index] = view.getInt16(index * 2, true) / 32768;
  }
  return samples;
}

export function resampleToPcm16(input: Float32Array, sourceRate: number): ArrayBuffer {
  const targetRate = 16_000;
  const ratio = sourceRate / targetRate;
  const outputLength = Math.max(1, Math.round(input.length / ratio));
  const output = new Int16Array(outputLength);
  for (let index = 0; index < outputLength; index += 1) {
    const sourceIndex = index * ratio;
    const left = Math.floor(sourceIndex);
    const right = Math.min(left + 1, input.length - 1);
    const fraction = sourceIndex - left;
    const value = input[left] * (1 - fraction) + input[right] * fraction;
    const clamped = Math.max(-1, Math.min(1, value));
    output[index] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
  }
  return output.buffer;
}

export function resampleFloat32(
  input: Float32Array,
  sourceRate: number,
  targetRate: number,
): Float32Array {
  if (sourceRate === targetRate || input.length < 2) return input;
  const ratio = sourceRate / targetRate;
  const outputLength = Math.max(1, Math.round(input.length / ratio));
  const output = new Float32Array(outputLength);
  for (let index = 0; index < outputLength; index += 1) {
    const sourceIndex = index * ratio;
    const left = Math.floor(sourceIndex);
    const right = Math.min(left + 1, input.length - 1);
    const fraction = sourceIndex - left;
    output[index] = input[left] * (1 - fraction) + input[right] * fraction;
  }
  return output;
}

export class MicrophoneCapture {
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private processor: ScriptProcessorNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private gain: GainNode | null = null;

  constructor(
    private readonly onPcm: (pcm: ArrayBuffer) => void,
    private readonly onLevel: (level: number) => void,
  ) {}

  get active(): boolean {
    return this.stream !== null;
  }

  async start(): Promise<void> {
    if (this.stream) return;
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    this.context = new AudioContext({ latencyHint: 'interactive' });
    await this.context.resume();
    this.source = this.context.createMediaStreamSource(this.stream);
    this.processor = this.context.createScriptProcessor(1024, 1, 1);
    this.gain = this.context.createGain();
    this.gain.gain.value = 0;
    this.processor.onaudioprocess = (event) => {
      const input = event.inputBuffer.getChannelData(0);
      let squares = 0;
      for (const sample of input) squares += sample * sample;
      this.onLevel(Math.min(1, Math.sqrt(squares / input.length) * 5));
      this.onPcm(resampleToPcm16(input, this.context?.sampleRate || 48_000));
    };
    this.source.connect(this.processor);
    this.processor.connect(this.gain);
    this.gain.connect(this.context.destination);
  }

  async stop(): Promise<void> {
    this.processor?.disconnect();
    this.source?.disconnect();
    this.gain?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    this.processor = null;
    this.source = null;
    this.gain = null;
    this.stream = null;
    if (this.context) await this.context.close();
    this.context = null;
    this.onLevel(0);
  }
}

export class PcmPlayback {
  private static readonly SOURCE_SAMPLE_RATE = 24_000;
  private static readonly PREBUFFER_SECONDS = 0.18;
  private context: AudioContext | null = null;
  private worklet: AudioWorkletNode | null = null;
  private initialization: Promise<void> | null = null;
  private generation = 0;
  private cursor = 0;
  private readonly sources = new Set<AudioBufferSourceNode>();
  private metrics: PcmPlaybackMetrics = {
    state: 'buffering',
    queuedMs: 0,
    prebufferMs: 180,
    underruns: 0,
    droppedSamples: 0,
    transport: 'worklet',
  };

  constructor(
    private readonly onMetrics: (metrics: PcmPlaybackMetrics) => void = () => {},
  ) {}

  async play(base64: string): Promise<void> {
    const generation = this.generation;
    await this.ensureReady();
    const context = this.context;
    if (!context || generation !== this.generation) return;
    const decoded = base64ToPcm(base64);
    const samples = resampleFloat32(
      decoded,
      PcmPlayback.SOURCE_SAMPLE_RATE,
      context.sampleRate,
    );
    if (this.worklet) {
      this.worklet.port.postMessage(
        { type: 'push', samples },
        [samples.buffer],
      );
      return;
    }
    this.scheduleFallback(context, samples);
  }

  snapshot(): PcmPlaybackMetrics {
    return { ...this.metrics };
  }

  private async ensureReady(): Promise<void> {
    if (!this.initialization) this.initialization = this.initialize();
    await this.initialization;
  }

  private async initialize(): Promise<void> {
    const context = new AudioContext({
      sampleRate: PcmPlayback.SOURCE_SAMPLE_RATE,
      latencyHint: 'interactive',
    });
    this.context = context;
    if (context.state === 'suspended') await context.resume();
    if (!context.audioWorklet || typeof AudioWorkletNode === 'undefined') {
      this.updateMetrics({ transport: 'scheduled-buffer' });
      return;
    }
    try {
      const moduleUrl = new URL(
        './worklets/gemini-live-playback-worklet.js',
        import.meta.url,
      );
      await context.audioWorklet.addModule(moduleUrl);
      if (context !== this.context) return;
      const worklet = new AudioWorkletNode(context, 'openjarvis-pcm-playback', {
        numberOfInputs: 0,
        numberOfOutputs: 1,
        outputChannelCount: [1],
        processorOptions: {
          sampleRate: context.sampleRate,
          prebufferMs: 180,
          minimumPrebufferMs: 120,
          maximumPrebufferMs: 480,
        },
      });
      worklet.port.onmessage = (event: MessageEvent<Partial<PcmPlaybackMetrics>>) => {
        if (!event.data?.state) return;
        this.updateMetrics({
          state: event.data.state,
          ...(typeof event.data.queuedMs === 'number'
            ? { queuedMs: event.data.queuedMs }
            : {}),
          ...(typeof event.data.prebufferMs === 'number'
            ? { prebufferMs: event.data.prebufferMs }
            : {}),
          ...(typeof event.data.underruns === 'number'
            ? { underruns: event.data.underruns }
            : {}),
          ...(typeof event.data.droppedSamples === 'number'
            ? { droppedSamples: event.data.droppedSamples }
            : {}),
        });
      };
      worklet.connect(context.destination);
      this.worklet = worklet;
      this.updateMetrics({ transport: 'worklet' });
    } catch {
      this.updateMetrics({ transport: 'scheduled-buffer' });
    }
  }

  private scheduleFallback(context: AudioContext, samples: Float32Array): void {
    const buffer = context.createBuffer(1, samples.length, context.sampleRate);
    buffer.copyToChannel(samples, 0);
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    const minimumStart = context.currentTime + PcmPlayback.PREBUFFER_SECONDS;
    const underrun = this.cursor > 0 && this.cursor < context.currentTime + 0.02;
    const start = Math.max(minimumStart, this.cursor);
    source.start(start);
    this.cursor = start + buffer.duration;
    this.sources.add(source);
    source.onended = () => this.sources.delete(source);
    this.updateMetrics({
      state: 'playing',
      queuedMs: Math.max(0, Math.round((this.cursor - context.currentTime) * 1_000)),
      underruns: this.metrics.underruns + (underrun ? 1 : 0),
      transport: 'scheduled-buffer',
    });
  }

  private updateMetrics(update: Partial<PcmPlaybackMetrics>): void {
    const next = { ...this.metrics, ...update };
    if (
      next.state === this.metrics.state
      && next.queuedMs === this.metrics.queuedMs
      && next.prebufferMs === this.metrics.prebufferMs
      && next.underruns === this.metrics.underruns
      && next.droppedSamples === this.metrics.droppedSamples
      && next.transport === this.metrics.transport
    ) return;
    this.metrics = next;
    this.onMetrics(this.snapshot());
  }

  interrupt(): void {
    this.generation += 1;
    this.worklet?.port.postMessage({ type: 'reset' });
    for (const source of this.sources) {
      try { source.stop(); } catch { /* already stopped */ }
    }
    this.sources.clear();
    this.cursor = this.context?.currentTime ?? 0;
    this.updateMetrics({ state: 'buffering', queuedMs: 0 });
  }

  async close(): Promise<void> {
    this.interrupt();
    const initialization = this.initialization;
    if (initialization) {
      try { await initialization; } catch { /* fallback/close still proceeds */ }
    }
    this.worklet?.disconnect();
    this.worklet = null;
    if (this.context) await this.context.close();
    this.context = null;
    this.initialization = null;
    this.cursor = 0;
  }
}

export interface PcmPlaybackMetrics {
  state: 'buffering' | 'playing';
  queuedMs: number;
  prebufferMs: number;
  underruns: number;
  droppedSamples: number;
  transport: 'worklet' | 'scheduled-buffer';
}
