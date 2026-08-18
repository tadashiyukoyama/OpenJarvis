import type {
  WhatsAppBaileysStatus,
  WhatsAppBaileysStatusResponse,
} from './jarvis-sources-api';

export interface WhatsAppStatusPresentation {
  label: string;
  terminal: boolean;
  retryLabel: string;
  message: string;
}

const PRESENTATIONS: Record<WhatsAppBaileysStatus, WhatsAppStatusPresentation> = {
  disconnected: {
    label: 'Desconectado',
    terminal: false,
    retryLabel: 'Iniciar conexão via QR',
    message: '',
  },
  connecting: {
    label: 'Iniciando bridge',
    terminal: false,
    retryLabel: 'Aguardando conexão…',
    message: '',
  },
  qr_required: {
    label: 'Aguardando leitura do QR',
    terminal: false,
    retryLabel: 'QR pronto — escaneie no WhatsApp',
    message: '',
  },
  connected: {
    label: 'Conectado via Baileys',
    terminal: true,
    retryLabel: 'WhatsApp conectado',
    message: 'WhatsApp já está conectado. Nenhum QR Code é necessário nesta sessão.',
  },
  conflict: {
    label: 'Conflito de sessão',
    terminal: true,
    retryLabel: 'Tentar novamente',
    message:
      'Outra sessão do WhatsApp Web entrou em conflito. Feche a sessão concorrente e tente novamente.',
  },
  logged_out: {
    label: 'Sessão desconectada',
    terminal: true,
    retryLabel: 'Limpar sessão local e gerar novo QR',
    message:
      'O WhatsApp invalidou esta sessão. Use o botão para limpar somente a autenticação local gerenciada em D: e gerar um novo QR.',
  },
  auth_inconsistent: {
    label: 'Sessão local inconsistente',
    terminal: true,
    retryLabel: 'Preservar sessão antiga e gerar novo QR',
    message:
      'A credencial principal está inválida e existem artefatos de uma sessão anterior. Preserve essa geração e inicie uma autenticação limpa.',
  },
  failed: {
    label: 'Falha no bridge',
    terminal: true,
    retryLabel: 'Tentar novamente',
    message: 'O bridge Baileys falhou antes de estabelecer a conexão.',
  },
  error: {
    label: 'Erro na conexão',
    terminal: true,
    retryLabel: 'Tentar novamente',
    message: 'O bridge Baileys retornou um erro de compatibilidade.',
  },
};

export function describeWhatsAppStatus(
  response: Pick<WhatsAppBaileysStatusResponse, 'status' | 'last_error'>,
): WhatsAppStatusPresentation {
  const presentation = PRESENTATIONS[response.status] ?? PRESENTATIONS.failed;
  return {
    ...presentation,
    message: response.last_error || presentation.message,
  };
}

export function isWhatsAppTerminalFailure(status: WhatsAppBaileysStatus): boolean {
  return ['conflict', 'logged_out', 'auth_inconsistent', 'failed', 'error'].includes(status);
}
