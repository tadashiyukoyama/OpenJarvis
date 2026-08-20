import { describe, expect, it, vi } from 'vitest';
import {
  buildGeminiLiveSetup,
  GeminiLiveSession,
  JARVIS_VOICE_NAME,
  jarvisLiveInternals,
} from './gemini-live';

const MANIFEST = [
  {
    name: 'codex_delegate_task',
    description: 'Delega ao Codex selecionado.',
    parameters: {
      type: 'object',
      properties: { command: { type: 'string' } },
      required: ['command'],
      additionalProperties: false,
    },
  },
  {
    name: 'whatsapp_search_contacts',
    description: 'Busca contatos.',
    parameters: { type: 'object', properties: { query: { type: 'string' } } },
  },
  {
    name: 'whatsapp_react_message',
    description: 'Reage usando uma referência opaca.',
    parameters: {
      type: 'object',
      properties: { message_ref: { type: 'string' }, reaction: { type: 'string' } },
      required: ['message_ref', 'reaction'],
    },
  },
];

describe('Gemini Live PCM conversion', () => {
  it('resamples microphone floats to 16 kHz PCM16', () => {
    const source = new Float32Array(4_800).fill(0.5);
    const pcm = jarvisLiveInternals.resampleToPcm16(source, 48_000);
    const samples = new Int16Array(pcm);

    expect(samples.length).toBe(1_600);
    expect(samples[0]).toBeGreaterThan(16_000);
    expect(samples[0]).toBeLessThan(16_500);
  });

  it('decodes little-endian PCM16 audio returned by Gemini', () => {
    const pcm = new Int16Array([0, 16_384, -16_384]);
    const base64 = jarvisLiveInternals.arrayBufferToBase64(pcm.buffer);
    const decoded = jarvisLiveInternals.base64ToPcm(base64);

    expect(decoded[0]).toBe(0);
    expect(decoded[1]).toBeCloseTo(0.5, 4);
    expect(decoded[2]).toBeCloseTo(-0.5, 4);
  });
});

describe('Gemini Live Jarvis voice setup', () => {
  it('opens every new session with the configured masculine Orus voice', () => {
    const message: any = buildGeminiLiveSetup('gemini-live-model', '', '', MANIFEST);

    expect(JARVIS_VOICE_NAME).toBe('Orus');
    expect(
      message.setup.generationConfig.speechConfig.voiceConfig.prebuiltVoiceConfig.voiceName,
    ).toBe('Orus');
    const instruction = JSON.stringify(message.setup.systemInstruction)
      .replace(/\\n/g, ' ')
      .replace(/\s+/g, ' ');
    expect(instruction).toContain('catálogo de funções');
    expect(instruction).toContain('FERRAMENTAS EXECUTÁVEIS NESTA SESSÃO (3)');
    expect(instruction).toContain('codex_delegate_task');
    expect(instruction).toContain('masculina e firme');
    expect(instruction).toContain(
      'não pode ser trocada no meio de uma sessão Live',
    );
    expect(instruction).toContain('NÃO peça confirmação por voz');
    expect(instruction).toContain('Aguarde o resultado do botão');
    expect(instruction).toContain('delegation_confirmed=true');
    expect(instruction).toContain('Uma leitura como codex_get_status');
    expect(instruction).toContain('mande um comando para o Codex');
    expect(instruction).toContain('nenhuma ação foi executada');
    expect(instruction).not.toContain('chame a função novamente');

    const declarations = message.setup.tools[0].functionDeclarations;
    const declaration = declarations.find((tool: any) => tool.name === 'codex_delegate_task');
    expect(declaration.parameters.type).toBe('OBJECT');
    expect(declaration.parameters.properties.command.type).toBe('STRING');
    expect(declaration.parameters).not.toHaveProperty('additionalProperties');
    expect(declaration.parameters.properties).not.toHaveProperty('confirmed');
  });

  it('adds bounded read-only conversation context to a new session', () => {
    const message: any = buildGeminiLiveSetup(
      'gemini-live-model',
      '',
      'CONTEXTO SOMENTE PARA CONTINUIDADE\nÚltima mensagem conhecida do Codex: pronto',
      MANIFEST,
    );

    expect(message.setup.systemInstruction.parts).toHaveLength(3);
    expect(message.setup.systemInstruction.parts[1].text).toContain(
      'whatsapp_search_contacts',
    );
    expect(message.setup.systemInstruction.parts[2].text).toContain(
      'Última mensagem conhecida do Codex: pronto',
    );
    expect(
      message.setup.tools[0].functionDeclarations.map((tool: any) => tool.name),
    ).toEqual(MANIFEST.map((tool) => tool.name));
  });

  it('requires an opaque message reference for WhatsApp reactions', () => {
    const message: any = buildGeminiLiveSetup('gemini-live-model', '', '', MANIFEST);
    const declaration = message.setup.tools[0].functionDeclarations.find(
      (tool: any) => tool.name === 'whatsapp_react_message',
    );

    expect(declaration.parameters.required).toEqual(['message_ref', 'reaction']);
    expect(declaration.parameters.properties).not.toHaveProperty('jid');
    expect(declaration.parameters.properties).not.toHaveProperty('message_id');
  });

  it('reuses a completed function-call ID and sends the documented result envelope', async () => {
    vi.stubGlobal('WebSocket', { OPEN: 1 });
    const send = vi.fn();
    const onToolCall = vi.fn(async () => ({ status: 'complete', result: 'ok' }));
    const onNotice = vi.fn();
    const session = new GeminiLiveSession(
      {
        token: 'ephemeral',
        credential_slot: 'primary',
        fallback_active: false,
        model: 'gemini-live-model',
        expires_at: '2099-01-01T00:00:00Z',
        websocket_endpoint: 'wss://example.invalid',
      },
      {
        onState: vi.fn(),
        onInputTranscript: vi.fn(),
        onOutputTranscript: vi.fn(),
        onAudioLevel: vi.fn(),
        onToolCall,
        onTurnComplete: vi.fn(),
        onNotice,
        onError: vi.fn(),
      },
    );
    (session as any).socket = { readyState: 1, send };
    const call = {
      id: 'function-call-17',
      name: 'delegate_to_codex',
      args: { command: 'teste', risk: 'workspace' },
    };

    await (session as any).handleToolCalls([call]);
    await (session as any).handleToolCalls([call]);

    expect(onToolCall).toHaveBeenCalledTimes(1);
    expect(onNotice).toHaveBeenCalledWith(
      expect.stringContaining('function-call-17'),
    );
    const payload = JSON.parse(send.mock.calls[1][0]);
    expect(payload.toolResponse.functionResponses[0]).toEqual({
      id: 'function-call-17',
      name: 'delegate_to_codex',
      response: { result: { status: 'complete', result: 'ok' } },
    });
    vi.unstubAllGlobals();
  });

  it('returns a later visual-button decision to the original function-call ID', async () => {
    vi.stubGlobal('WebSocket', { OPEN: 1 });
    const send = vi.fn();
    let decide!: (result: Record<string, unknown>) => void;
    const decision = new Promise<Record<string, unknown>>((resolve) => {
      decide = resolve;
    });
    const session = new GeminiLiveSession(
      {
        token: 'ephemeral',
        credential_slot: 'primary',
        fallback_active: false,
        model: 'gemini-live-model',
        expires_at: '2099-01-01T00:00:00Z',
        websocket_endpoint: 'wss://example.invalid',
      },
      {
        onState: vi.fn(),
        onInputTranscript: vi.fn(),
        onOutputTranscript: vi.fn(),
        onAudioLevel: vi.fn(),
        onToolCall: vi.fn(() => decision),
        onTurnComplete: vi.fn(),
        onNotice: vi.fn(),
        onError: vi.fn(),
      },
    );
    (session as any).socket = { readyState: 1, send };

    const handling = (session as any).handleToolCalls([
      {
        id: 'visual-approval-1',
        name: 'delegate_to_codex',
        args: { command: 'investigue', risk: 'workspace' },
      },
    ]);
    await Promise.resolve();
    expect(send).not.toHaveBeenCalled();

    decide({ status: 'rejected', message: 'César negou a autorização visual.' });
    await handling;

    expect(JSON.parse(send.mock.calls[0][0])).toMatchObject({
      toolResponse: {
        functionResponses: [
          {
            id: 'visual-approval-1',
            response: { result: { status: 'rejected' } },
          },
        ],
      },
    });
    vi.unstubAllGlobals();
  });

  it('does not remain in connecting when setupComplete never arrives', async () => {
    vi.useFakeTimers();
    const closeSocket = vi.fn();
    class HangingSocket {
      onopen: (() => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      onerror: (() => void) | null = null;
      onclose: ((event: CloseEvent) => void) | null = null;
      send = vi.fn();
      close = closeSocket;
    }
    vi.stubGlobal('WebSocket', HangingSocket);
    const session = new GeminiLiveSession(
      {
        token: 'ephemeral',
        credential_slot: 'primary',
        fallback_active: false,
        model: 'gemini-live-model',
        expires_at: '2099-01-01T00:00:00Z',
        websocket_endpoint: 'wss://example.invalid',
      },
      {
        onState: vi.fn(),
        onInputTranscript: vi.fn(),
        onOutputTranscript: vi.fn(),
        onAudioLevel: vi.fn(),
        onToolCall: vi.fn(),
        onTurnComplete: vi.fn(),
        onNotice: vi.fn(),
        onError: vi.fn(),
      },
    );

    const connecting = session.connect();
    const expectedFailure = expect(connecting).rejects.toThrow(
      'não concluiu a inicialização',
    );
    await vi.advanceTimersByTimeAsync(15_000);
    await expectedFailure;
    expect(closeSocket).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('assembles late transcription chunks before authorizing a tool call', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('WebSocket', { OPEN: 1 });
    const send = vi.fn();
    const finalized: string[] = [];
    const onToolCall = vi.fn(async () => ({
      status: 'complete',
      utterance: finalized[finalized.length - 1],
    }));
    const session = new GeminiLiveSession(
      {
        token: 'ephemeral',
        credential_slot: 'primary',
        fallback_active: false,
        model: 'gemini-live-model',
        expires_at: '2099-01-01T00:00:00Z',
        websocket_endpoint: 'wss://example.invalid',
      },
      {
        onState: vi.fn(),
        onInputTranscript: (text, finished) => {
          if (finished) finalized.push(text);
        },
        onOutputTranscript: vi.fn(),
        onAudioLevel: vi.fn(),
        onToolCall,
        onTurnComplete: vi.fn(),
        onNotice: vi.fn(),
        onError: vi.fn(),
      },
    );
    (session as any).socket = { readyState: 1, send };

    await (session as any).handleMessage(
      JSON.stringify({
        toolCall: {
          functionCalls: [
            {
              id: 'late-transcript-call',
              name: 'delegate_to_codex',
              args: { command: 'investigue o pedido completo', risk: 'workspace' },
            },
          ],
        },
      }),
      vi.fn(),
    );
    await (session as any).handleMessage(
      JSON.stringify({ serverContent: { inputTranscription: { text: 'Mande ao Codex ', finished: true } } }),
      vi.fn(),
    );
    await (session as any).handleMessage(
      JSON.stringify({ serverContent: { inputTranscription: { text: 'investigar o pedido completo.', finished: true } } }),
      vi.fn(),
    );

    await vi.advanceTimersByTimeAsync(1_600);
    await (session as any).toolQueue;

    expect(finalized).toEqual(['Mande ao Codex investigar o pedido completo.']);
    expect(onToolCall).toHaveBeenCalledTimes(1);
    expect(JSON.parse(send.mock.calls[0][0])).toMatchObject({
      toolResponse: {
        functionResponses: [
          { response: { result: { utterance: 'Mande ao Codex investigar o pedido completo.' } } },
        ],
      },
    });
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });
});
