import { describe, expect, it, vi } from 'vitest';
import { TurnAssembler } from './jarvis-turn';

describe('TurnAssembler', () => {
  it('emits partial fragments but one final turn', () => {
    const partials: string[] = [];
    const finals: string[] = [];
    const assembler = new TurnAssembler({
      onPartial: (text) => partials.push(text),
      onFinal: (text) => finals.push(text),
    });

    assembler.append('investigue ');
    assembler.append('o erro');
    expect(assembler.commit()).toBe('investigue o erro');
    expect(assembler.commit()).toBeNull();

    expect(partials).toEqual(['investigue ', 'investigue o erro']);
    expect(finals).toEqual(['investigue o erro']);
  });

  it('commits on the provider final marker and ignores the duplicate final', () => {
    const finals: string[] = [];
    const assembler = new TurnAssembler({
      onPartial: () => undefined,
      onFinal: (text) => finals.push(text),
    });

    assembler.append('Olá Jarvis', true);
    assembler.append('Olá Jarvis', true);

    expect(finals).toEqual(['Olá Jarvis']);
  });

  it('starts a new turn only after a committed turn receives a new fragment', () => {
    const finals: string[] = [];
    const assembler = new TurnAssembler({
      onPartial: vi.fn(),
      onFinal: (text) => finals.push(text),
    });

    assembler.append('primeira');
    assembler.commit();
    assembler.append('segunda');
    assembler.commit();

    expect(finals).toEqual(['primeira', 'segunda']);
  });

  it('ignores callbacks after session invalidation', () => {
    const callbacks = { onPartial: vi.fn(), onFinal: vi.fn() };
    const assembler = new TurnAssembler(callbacks);

    assembler.append('pedido');
    assembler.invalidate();
    expect(assembler.commit()).toBeNull();
    assembler.append('tardio');

    expect(callbacks.onFinal).not.toHaveBeenCalled();
    expect(callbacks.onPartial).toHaveBeenCalledTimes(1);
  });
});
