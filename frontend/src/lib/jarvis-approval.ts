export type JarvisApprovalState =
  | 'AWAITING_CONFIRMATION'
  | 'DISPATCHING'
  | 'COMPLETED'
  | 'REJECTED'
  | 'EXPIRED'
  | 'FAILED'
  | 'CANCELLED';

export interface JarvisApprovalDescriptor {
  requestId: string;
  functionCallId: string;
  destination: 'codex' | 'gmail' | 'whatsapp';
  command: string;
  risk: string;
  conversationId: string;
  conversationTitle: string;
  projectCwd: string;
  expiresAt: number;
}

export interface JarvisApprovalSnapshot extends JarvisApprovalDescriptor {
  state: JarvisApprovalState;
}

type ApprovalResult = Record<string, unknown>;

interface PendingApproval {
  descriptor: JarvisApprovalDescriptor;
  execute: () => Promise<ApprovalResult>;
  promise: Promise<ApprovalResult>;
  resolve: (result: ApprovalResult) => void;
  state: JarvisApprovalState;
}

/**
 * Owns the one-at-a-time visual approval boundary for Gemini function calls.
 *
 * The original tool promise remains pending while the button is visible. The
 * same function call therefore receives the final approved/rejected result;
 * no synthetic user message and no second model-generated call are required.
 */
export class JarvisApprovalCoordinator {
  private pending: PendingApproval | null = null;

  constructor(private readonly now: () => number = Date.now) {}

  request(
    descriptor: JarvisApprovalDescriptor,
    execute: () => Promise<ApprovalResult>,
  ): Promise<ApprovalResult> {
    this.expire();
    if (descriptor.expiresAt <= this.now()) {
      return Promise.resolve({
        status: 'expired',
        message: 'A autorização visual expirou.',
      });
    }
    if (this.pending) {
      return Promise.resolve({
        status: 'approval_busy',
        message: 'Outra ação já aguarda confirmação visual.',
      });
    }

    let resolve!: (result: ApprovalResult) => void;
    const promise = new Promise<ApprovalResult>((settle) => {
      resolve = settle;
    });
    this.pending = {
      descriptor,
      execute,
      promise,
      resolve,
      state: 'AWAITING_CONFIRMATION',
    };
    return promise;
  }

  snapshot(): JarvisApprovalSnapshot | null {
    this.expire();
    if (!this.pending) return null;
    return { ...this.pending.descriptor, state: this.pending.state };
  }

  async approve(requestId?: string): Promise<ApprovalResult> {
    this.expire();
    const pending = this.pending;
    if (!pending || (requestId && pending.descriptor.requestId !== requestId)) {
      return { status: 'no_pending_approval' };
    }
    if (pending.state === 'DISPATCHING') return pending.promise;
    if (pending.state !== 'AWAITING_CONFIRMATION') {
      return { status: 'approval_not_actionable' };
    }

    pending.state = 'DISPATCHING';
    try {
      const result = await pending.execute();
      const status = result.status === 'error' ? 'FAILED' : 'COMPLETED';
      return this.settle(pending, result, status);
    } catch (error) {
      return this.settle(
        pending,
        {
          status: 'error',
          message: error instanceof Error ? error.message : 'Falha na ação aprovada.',
        },
        'FAILED',
      );
    }
  }

  reject(requestId?: string): ApprovalResult {
    const pending = this.pending;
    if (!pending || (requestId && pending.descriptor.requestId !== requestId)) {
      return { status: 'no_pending_approval' };
    }
    if (pending.state === 'DISPATCHING') {
      return {
        status: 'already_dispatching',
        message: 'A ação já foi autorizada e está em execução.',
      };
    }
    return this.settle(
      pending,
      { status: 'rejected', message: 'César negou a autorização visual.' },
      'REJECTED',
    );
  }

  expire(): ApprovalResult | null {
    const pending = this.pending;
    if (
      !pending ||
      pending.state !== 'AWAITING_CONFIRMATION' ||
      pending.descriptor.expiresAt > this.now()
    ) {
      return null;
    }
    return this.settle(
      pending,
      { status: 'expired', message: 'A autorização visual expirou.' },
      'EXPIRED',
    );
  }

  cancelSession(): ApprovalResult | null {
    const pending = this.pending;
    if (!pending) return null;
    if (pending.state === 'DISPATCHING') {
      return this.settle(
        pending,
        {
          status: 'session_closed',
          action_status: 'dispatching',
          message:
            'A sessão foi encerrada, mas a ação já autorizada continua em execução e será registrada no histórico.',
        },
        'CANCELLED',
      );
    }
    return this.settle(
      pending,
      { status: 'session_closed', message: 'A sessão foi encerrada antes da autorização.' },
      'CANCELLED',
    );
  }

  private settle(
    pending: PendingApproval,
    result: ApprovalResult,
    state: JarvisApprovalState,
  ): ApprovalResult {
    if (this.pending !== pending) return result;
    pending.state = state;
    this.pending = null;
    pending.resolve(result);
    return result;
  }
}
