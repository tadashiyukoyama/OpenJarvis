/**
 * Public OpenJarvis deployments have one cognitive authority: the Agent Host
 * running Codex.  The desktop application keeps its local model workspace,
 * but the web surface must never let a browser choose a second brain.
 */
export const CODEX_BRAIN_ID = 'codex';
export const CODEX_BRAIN_LABEL = 'Codex · único cérebro';

export function isDesktopRuntime(): boolean {
  return typeof window !== 'undefined' && !!window.__TAURI_INTERNALS__;
}

export function publicBrainModel(isDesktop: boolean, requested = ''): string {
  return isDesktop ? requested : CODEX_BRAIN_ID;
}
