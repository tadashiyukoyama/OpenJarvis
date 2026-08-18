const DEFAULT_SAMPLE_RATE = 24_000;
const DEFAULT_PREBUFFER_MS = 180;
const MIN_PREBUFFER_MS = 120;
const MAX_PREBUFFER_MS = 480;
const PREBUFFER_STEP_MS = 40;
const CAPACITY_MS = 8_000;
const STABLE_WINDOW_MS = 20_000;

export class AdaptivePcmQueue {
  constructor(options = {}) {
    this.sampleRate = options.sampleRate || DEFAULT_SAMPLE_RATE;
    this.minimumPrebufferSamples = this._samples(
      options.minimumPrebufferMs || MIN_PREBUFFER_MS,
    );
    this.maximumPrebufferSamples = this._samples(
      options.maximumPrebufferMs || MAX_PREBUFFER_MS,
    );
    this.prebufferStepSamples = this._samples(
      options.prebufferStepMs || PREBUFFER_STEP_MS,
    );
    this.initialPrebufferSamples = this._clampPrebuffer(
      this._samples(options.prebufferMs || DEFAULT_PREBUFFER_MS),
    );
    this.targetPrebufferSamples = this.initialPrebufferSamples;
    this.stableWindowSamples = this._samples(
      options.stableWindowMs || STABLE_WINDOW_MS,
    );
    const capacitySamples = Math.max(
      this.maximumPrebufferSamples * 2,
      this._samples(options.capacityMs || CAPACITY_MS),
    );
    this.buffer = new Float32Array(capacitySamples);
    this.readIndex = 0;
    this.writeIndex = 0;
    this.length = 0;
    this.started = false;
    this.underruns = 0;
    this.droppedSamples = 0;
    this.stableSamples = 0;
  }

  push(value) {
    const samples = value instanceof Float32Array ? value : new Float32Array(value);
    if (!samples.length) return this.snapshot();

    let source = samples;
    if (source.length >= this.buffer.length) {
      this.droppedSamples += this.length + source.length - this.buffer.length;
      source = source.subarray(source.length - this.buffer.length);
      this.readIndex = 0;
      this.writeIndex = 0;
      this.length = 0;
    } else {
      const overflow = Math.max(0, this.length + source.length - this.buffer.length);
      if (overflow) {
        this._discard(overflow);
        this.droppedSamples += overflow;
      }
    }

    for (let index = 0; index < source.length; index += 1) {
      this.buffer[this.writeIndex] = source[index];
      this.writeIndex = (this.writeIndex + 1) % this.buffer.length;
    }
    this.length += source.length;
    return this.snapshot();
  }

  pull(output) {
    output.fill(0);
    if (!this.started) {
      if (this.length < this.targetPrebufferSamples) return this.snapshot();
      this.started = true;
    }

    const available = Math.min(this.length, output.length);
    for (let index = 0; index < available; index += 1) {
      output[index] = this.buffer[this.readIndex];
      this.readIndex = (this.readIndex + 1) % this.buffer.length;
    }
    this.length -= available;

    if (available < output.length) {
      this.underruns += 1;
      this.started = false;
      this.stableSamples = 0;
      this.targetPrebufferSamples = this._clampPrebuffer(
        this.targetPrebufferSamples + this.prebufferStepSamples,
      );
    } else {
      this.stableSamples += available;
      if (
        this.stableSamples >= this.stableWindowSamples
        && this.targetPrebufferSamples > this.minimumPrebufferSamples
      ) {
        this.targetPrebufferSamples = this._clampPrebuffer(
          this.targetPrebufferSamples - Math.floor(this.prebufferStepSamples / 2),
        );
        this.stableSamples = 0;
      }
    }
    return this.snapshot();
  }

  reset() {
    this.readIndex = 0;
    this.writeIndex = 0;
    this.length = 0;
    this.started = false;
    this.stableSamples = 0;
    return this.snapshot();
  }

  snapshot() {
    return {
      state: this.started ? 'playing' : 'buffering',
      queuedMs: Math.round((this.length / this.sampleRate) * 1_000),
      prebufferMs: Math.round(
        (this.targetPrebufferSamples / this.sampleRate) * 1_000,
      ),
      underruns: this.underruns,
      droppedSamples: this.droppedSamples,
    };
  }

  _discard(count) {
    const discarded = Math.min(count, this.length);
    this.readIndex = (this.readIndex + discarded) % this.buffer.length;
    this.length -= discarded;
  }

  _samples(milliseconds) {
    return Math.max(1, Math.round((milliseconds / 1_000) * this.sampleRate));
  }

  _clampPrebuffer(value) {
    return Math.max(
      this.minimumPrebufferSamples,
      Math.min(this.maximumPrebufferSamples, value),
    );
  }
}

const WorkletBase = typeof AudioWorkletProcessor === 'undefined'
  ? class {
      constructor() {
        this.port = { onmessage: null, postMessage() {} };
      }
    }
  : AudioWorkletProcessor;

class OpenJarvisPcmPlaybackProcessor extends WorkletBase {
  constructor(options) {
    super();
    const actualSampleRate = typeof sampleRate === 'number'
      ? sampleRate
      : options?.processorOptions?.sampleRate || DEFAULT_SAMPLE_RATE;
    this.queue = new AdaptivePcmQueue({
      ...options?.processorOptions,
      sampleRate: actualSampleRate,
    });
    this.lastReported = this.queue.snapshot();
    this.framesSinceReport = 0;
    this.port.onmessage = (event) => {
      if (event.data?.type === 'push') {
        this.queue.push(event.data.samples);
      } else if (event.data?.type === 'reset') {
        this._report(this.queue.reset(), true);
      } else if (event.data?.type === 'metrics') {
        this._report(this.queue.snapshot(), true);
      }
    };
  }

  process(_inputs, outputs) {
    const channel = outputs[0]?.[0];
    if (!channel) return true;
    const metrics = this.queue.pull(channel);
    this.framesSinceReport += channel.length;
    const stateChanged = metrics.state !== this.lastReported.state;
    const underrunChanged = metrics.underruns !== this.lastReported.underruns;
    const reportInterval = this.queue.sampleRate;
    if (stateChanged || underrunChanged || this.framesSinceReport >= reportInterval) {
      this._report(metrics, true);
    }
    return true;
  }

  _report(metrics, resetCounter) {
    this.lastReported = metrics;
    if (resetCounter) this.framesSinceReport = 0;
    this.port.postMessage({ type: 'metrics', ...metrics });
  }
}

if (typeof registerProcessor === 'function') {
  registerProcessor('openjarvis-pcm-playback', OpenJarvisPcmPlaybackProcessor);
}
