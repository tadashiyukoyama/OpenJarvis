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
  private context: AudioContext | null = null;
  private cursor = 0;
  private readonly sources = new Set<AudioBufferSourceNode>();

  async play(base64: string): Promise<void> {
    this.context ??= new AudioContext({ sampleRate: 24_000 });
    if (this.context.state === 'suspended') await this.context.resume();
    const samples = base64ToPcm(base64);
    const buffer = this.context.createBuffer(1, samples.length, 24_000);
    buffer.copyToChannel(samples, 0);
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.context.destination);
    const start = Math.max(this.context.currentTime + 0.01, this.cursor);
    source.start(start);
    this.cursor = start + buffer.duration;
    this.sources.add(source);
    source.onended = () => this.sources.delete(source);
  }

  interrupt(): void {
    for (const source of this.sources) {
      try { source.stop(); } catch { /* already stopped */ }
    }
    this.sources.clear();
    this.cursor = this.context?.currentTime ?? 0;
  }

  async close(): Promise<void> {
    this.interrupt();
    if (this.context) await this.context.close();
    this.context = null;
    this.cursor = 0;
  }
}
