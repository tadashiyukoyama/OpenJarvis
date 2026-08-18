import { ShieldAlert } from 'lucide-react';
import type { JarvisEdgeApproval } from '../api/types';

interface Props {
  approval: JarvisEdgeApproval;
  busy: boolean;
  onApprove: () => void;
  onDeny: () => void;
}

function valueText(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value);
}

export function JarvisEdgeApprovalPanel({ approval, busy, onApprove, onDeny }: Props) {
  const rows = Object.entries(approval.preview).filter(([, value]) => value != null && value !== '');
  return (
    <div className="jarvis-approval-bar" role="alertdialog" aria-label="Permissão local do Codex">
      <div>
        <ShieldAlert size={19} />
        <span>
          <strong>O Codex Desktop solicita uma permissão local</strong>
          {rows.map(([key, value]) => (
            <small key={key}>{key}: <code>{valueText(value)}</code></small>
          ))}
          <small>A decisão vale somente para este payload e expira automaticamente.</small>
        </span>
      </div>
      <div>
        <button onClick={onDeny} disabled={busy}>Negar</button>
        <button className="approve" onClick={onApprove} disabled={busy}>
          {busy ? 'Enviando decisão...' : 'Autorizar no computador'}
        </button>
      </div>
    </div>
  );
}
