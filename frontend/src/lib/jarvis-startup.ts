export class JarvisStartupTimeoutError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'JarvisStartupTimeoutError';
  }
}

interface OptionalJarvisContextOptions<T> {
  load: (signal: AbortSignal) => Promise<T>;
  fallback: () => T;
  timeoutMs: number;
  label: string;
  onFallback?: (error: unknown) => void;
}

/**
 * Load context that improves a Jarvis session but must never prevent voice
 * startup. The in-flight HTTP request is aborted when its deadline expires so
 * a disconnected tablet cannot leave requests accumulating in the gateway.
 */
export async function loadOptionalJarvisContext<T>(
  options: OptionalJarvisContextOptions<T>,
): Promise<T> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => {
      controller.abort();
      reject(new JarvisStartupTimeoutError(
        `${options.label} excedeu ${options.timeoutMs} ms.`,
      ));
    }, options.timeoutMs);
  });

  try {
    return await Promise.race([options.load(controller.signal), timeout]);
  } catch (error) {
    options.onFallback?.(error);
    return options.fallback();
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}
