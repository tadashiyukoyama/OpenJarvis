import { AlertTriangle, RefreshCw } from 'lucide-react';
import type { JarvisAgentAction } from '../api/types';

interface JarvisApprovalPanelProps {
  action: JarvisAgentAction;
  onApprove: () => void;
  onDeny: () => void;
}
function previewLine(value: unknown): string {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return JSON.stringify(value);
}

export function JarvisApprovalPanel({
  action,
  onApprove,
  onDeny,
}: JarvisApprovalPanelProps) {
  const dispatching = action.state === 'DISPATCHING';
  const rows = Object.entries(action.preview).filter(([, value]) => value !== '' && value != null);
  return (
    <div
      className="jarvis-approval-bar"
      role="alertdialog"
      aria-label="Autorização operacional"
      aria-busy={dispatching}
    >
      <div>
        {dispatching ? (
          <RefreshCw className="jarvis-spin" size={19} />
        ) : (
          <AlertTriangle size={19} />
        )}
        <span>
          <strong>{dispatching ? 'Ação autorizada em execução' : 'Ação aguardando decisão visual'}</strong>
          <small>Ferramenta: {action.tool_id}</small>
          {rows.map(([key, value]) => (
            <small key={key}>
              {key}: <code>{previewLine(value)}</code>
            </small>
          ))}
          {!dispatching && (
            <small>Somente os botões decidem; “sim” ou “confirmo” por voz não autorizam.</small>
          )}
        </span>
      </div>
      <div>
        <button onClick={onDeny} disabled={dispatching}>Negar</button>
        <button className="approve" onClick={onApprove} disabled={dispatching}>
          {dispatching ? 'Executando...' : 'Autorizar e executar'}
        </button>
      </div>
    </div>
  );
}
