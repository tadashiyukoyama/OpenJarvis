export interface AdaptivePcmQueueOptions {
  sampleRate?: number;
  prebufferMs?: number;
  minimumPrebufferMs?: number;
  maximumPrebufferMs?: number;
  prebufferStepMs?: number;
  prebufferGrowthFactor?: number;
  capacityMs?: number;
  stableWindowMs?: number;
}

export interface AdaptivePcmQueueMetrics {
  state: 'buffering' | 'playing';
  queuedMs: number;
  prebufferMs: number;
  underruns: number;
  droppedSamples: number;
}

export class AdaptivePcmQueue {
  constructor(options?: AdaptivePcmQueueOptions);
  push(samples: Float32Array | ArrayBuffer): AdaptivePcmQueueMetrics;
  pull(output: Float32Array): AdaptivePcmQueueMetrics;
  reset(): AdaptivePcmQueueMetrics;
  snapshot(): AdaptivePcmQueueMetrics;
}
