import {
  AudioLines,
  CircleStop,
  Mic,
  MicOff,
  Radio,
  RefreshCw,
  Send,
} from 'lucide-react';
import type { JarvisVoiceState } from '@/lib/gemini-live';

interface JarvisVoiceCoreProps {
  voiceState: JarvisVoiceState;
  stateLabel: string;
  stateHint: string;
  audioLevel: number;
  inputTranscript: string;
  outputTranscript: string;
  textInput: string;
  microphoneOn: boolean;
  busy: boolean;
  configured: boolean;
  onTextChange: (value: string) => void;
  onStart: () => void;
  onStop: () => void;
  onToggleMicrophone: () => void;
  onSendText: () => void;
}
export function JarvisVoiceCore(props: JarvisVoiceCoreProps) {
  const connected = props.voiceState !== 'offline' && props.voiceState !== 'error';
  const coreScale = 1 + props.audioLevel * 0.2;
  return (
    <main className="jarvis-core-zone">
      <div className="jarvis-orbit-shell" style={{ transform: `scale(${coreScale})` }}>
        <div className="jarvis-orbit orbit-one" />
        <div className="jarvis-orbit orbit-two" />
        <div className="jarvis-orbit orbit-three" />
        <button
          className="jarvis-core"
          onClick={connected ? props.onToggleMicrophone : props.onStart}
          disabled={props.busy}
          aria-label={connected ? 'Alternar microfone' : 'Iniciar Jarvis'}
        >
          <span className="jarvis-core-inner">
            {props.busy
              ? <RefreshCw className="jarvis-spin" />
              : props.microphoneOn ? <AudioLines /> : <Mic />}
          </span>
        </button>
        <span className="jarvis-node node-a" />
        <span className="jarvis-node node-b" />
        <span className="jarvis-node node-c" />
      </div>
      <div className="jarvis-state-copy">
        <strong>{props.stateLabel}</strong>
        <span>{props.stateHint}</span>
      </div>
      <div className="jarvis-wave" aria-hidden="true">
        {Array.from({ length: 24 }, (_, index) => (
          <span
            key={index}
            style={{
              height: `${8 + Math.max(props.audioLevel * 58, connected ? (index % 5) * 2 : 0)}px`,
              animationDelay: `${index * -45}ms`,
            }}
          />
        ))}
      </div>
      <div className="jarvis-transcript">
        <div><span>VOCÊ</span>{props.inputTranscript || '...'}</div>
        <div><span>JARVIS</span>{props.outputTranscript || '...'}</div>
      </div>
      <div className="jarvis-controls">
        {!connected ? (
          <button
            className="jarvis-primary-button"
            onClick={props.onStart}
            disabled={props.busy || !props.configured}
          >
            <Radio size={17} /> Iniciar sessão
          </button>
        ) : (
          <>
            <button className="jarvis-icon-button" onClick={props.onToggleMicrophone}>
              {props.microphoneOn ? <Mic size={18} /> : <MicOff size={18} />}
            </button>
            <button className="jarvis-danger-button" onClick={props.onStop} disabled={props.busy}>
              <CircleStop size={17} /> Encerrar
            </button>
          </>
        )}
      </div>
      <div className="jarvis-text-fallback">
        <input
          value={props.textInput}
          onChange={(event) => props.onTextChange(event.target.value)}
          onKeyDown={(event) => { if (event.key === 'Enter') props.onSendText(); }}
          placeholder={connected ? 'Digite para testar o canal Live...' : 'Inicie uma sessão para enviar texto'}
          disabled={!connected}
        />
        <button
          onClick={props.onSendText}
          disabled={!connected || !props.textInput.trim()}
          aria-label="Enviar texto"
        >
          <Send size={16} />
        </button>
      </div>
    </main>
  );
}
