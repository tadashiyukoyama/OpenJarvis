import type {
  ChatMessage,
  CodexHistoryMessage,
  CodexThreadHistory,
  CodexThreadMessageEvent,
} from '../types';

function canonicalMessageId(threadId: string, messageId: string): string {
  return `codex-${threadId}-${messageId}`;
}

function samePublicMessage(
  left: Pick<ChatMessage, 'role' | 'content'> | undefined,
  right: Pick<ChatMessage, 'role' | 'content'> | undefined,
): boolean {
  return !!left && !!right && left.role === right.role && left.content === right.content;
}

export function codexMessageSequenceEquals(
  left: ChatMessage[],
  right: ChatMessage[],
): boolean {
  return left.length === right.length && left.every((message, index) => {
    const candidate = right[index];
    return !!candidate
      && message.id === candidate.id
      && message.role === candidate.role
      && message.content === candidate.content
      && message.timestamp === candidate.timestamp;
  });
}

export function applyCodexLiveDelta(
  messages: ChatMessage[],
  threadId: string,
  turnId: string,
  delta: string,
  timestamp: number,
): ChatMessage[] {
  if (!delta) return messages;
  const id = `codex-${threadId}-live-${turnId}`;
  const index = messages.findIndex((message) => message.id === id);
  if (index < 0) {
    return [
      ...messages,
      { id, role: 'assistant', content: delta, timestamp },
    ];
  }
  const next = [...messages];
  next[index] = { ...next[index], content: next[index].content + delta };
  return next;
}

function publicMessageToChat(
  threadId: string,
  message: CodexHistoryMessage,
  fallbackTimestamp: number,
  preserved?: ChatMessage,
): ChatMessage {
  return {
    ...preserved,
    id: canonicalMessageId(threadId, message.message_id),
    role: message.role,
    content: message.content,
    timestamp: message.timestamp !== null
      ? message.timestamp * 1000
      : preserved?.timestamp ?? fallbackTimestamp,
  };
}

export function applyCodexLiveMessage(
  messages: ChatMessage[],
  event: CodexThreadMessageEvent,
  fallbackTimestamp: number,
): ChatMessage[] {
  const id = canonicalMessageId(event.thread_id, event.message.message_id);
  const exactIndex = messages.findIndex((message) => message.id === id);
  if (exactIndex >= 0) {
    const replacement = publicMessageToChat(
      event.thread_id,
      event.message,
      fallbackTimestamp,
      messages[exactIndex],
    );
    if (samePublicMessage(messages[exactIndex], replacement)) return messages;
    const next = [...messages];
    next[exactIndex] = replacement;
    return next;
  }

  const liveId = event.turn_id
    ? `codex-${event.thread_id}-live-${event.turn_id}`
    : null;
  let replaceIndex = liveId
    ? messages.findIndex((message) => message.id === liveId)
    : -1;
  if (replaceIndex < 0) {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (samePublicMessage(messages[index], event.message)) {
        replaceIndex = index;
        break;
      }
    }
  }
  const preserved = replaceIndex >= 0 ? messages[replaceIndex] : undefined;
  const canonical = publicMessageToChat(
    event.thread_id,
    event.message,
    fallbackTimestamp,
    preserved,
  );
  if (replaceIndex < 0) return [...messages, canonical];
  const next = [...messages];
  next[replaceIndex] = canonical;
  return next;
}

function remoteHistoryIsStalePrefix(
  existing: ChatMessage[],
  remote: CodexThreadHistory['messages'],
): boolean {
  if (remote.length >= existing.length || remote.length === 0) return false;
  let latestMatch = -1;
  for (let start = 0; start <= existing.length - remote.length; start += 1) {
    if (remote.every((message, index) => (
      samePublicMessage(existing[start + index], message)
    ))) {
      latestMatch = start;
    }
  }
  return latestMatch === 0;
}

function bestPartialHistoryOffset(
  threadId: string,
  existing: ChatMessage[],
  remote: CodexThreadHistory['messages'],
): number | null {
  const existingById = new Map(
    existing.map((message, index) => [message.id, index]),
  );
  const exactOffsets = new Map<number, number>();
  remote.forEach((message, remoteIndex) => {
    const existingIndex = existingById.get(
      canonicalMessageId(threadId, message.message_id),
    );
    if (existingIndex === undefined) return;
    const offset = existingIndex - remoteIndex;
    exactOffsets.set(offset, (exactOffsets.get(offset) ?? 0) + 1);
  });
  if (exactOffsets.size > 0) {
    return [...exactOffsets.entries()].sort((left, right) => {
      if (left[1] !== right[1]) return right[1] - left[1];
      const leftTailDistance = Math.abs(left[0] + remote.length - existing.length);
      const rightTailDistance = Math.abs(right[0] + remote.length - existing.length);
      if (leftTailDistance !== rightTailDistance) return leftTailDistance - rightTailDistance;
      return right[0] - left[0];
    })[0][0];
  }

  let bestLength = 0;
  let bestExistingStart = -1;
  let bestRemoteStart = -1;
  for (let remoteStart = 0; remoteStart < remote.length; remoteStart += 1) {
    for (let existingStart = 0; existingStart < existing.length; existingStart += 1) {
      let length = 0;
      while (
        remoteStart + length < remote.length
        && existingStart + length < existing.length
        && samePublicMessage(
          existing[existingStart + length],
          remote[remoteStart + length],
        )
      ) {
        length += 1;
      }
      if (
        length > bestLength
        || (length === bestLength && existingStart > bestExistingStart)
      ) {
        bestLength = length;
        bestExistingStart = existingStart;
        bestRemoteStart = remoteStart;
      }
    }
  }
  return bestLength > 0 ? bestExistingStart - bestRemoteStart : null;
}

/**
 * Convert an authoritative Codex history snapshot into stable UI messages.
 *
 * Matching local messages keep their telemetry/tool metadata, while IDs and
 * public text come from Codex. An older prefix snapshot never removes the
 * locally completed tail of a just-finished OpenJarvis stream.
 */
export function reconcileCodexHistoryMessages(
  history: CodexThreadHistory,
  existing: ChatMessage[],
  fallbackTimestamp: number,
): ChatMessage[] {
  if (remoteHistoryIsStalePrefix(existing, history.messages)) return existing;

  const existingById = new Map(existing.map((message) => [message.id, message]));
  const partialOffset = history.complete === false
    ? bestPartialHistoryOffset(history.thread_id, existing, history.messages)
    : null;
  const preservedIndexes = new Set<number>();
  const remoteMessages = history.messages.map((message, index) => {
    const id = canonicalMessageId(history.thread_id, message.message_id);
    const exact = existingById.get(id);
    const alignedIndex = partialOffset === null ? -1 : partialOffset + index;
    const aligned = alignedIndex >= 0
      && alignedIndex < existing.length
      && samePublicMessage(existing[alignedIndex], message)
      ? existing[alignedIndex]
      : undefined;
    if (aligned) preservedIndexes.add(alignedIndex);
    let contentMatch: ChatMessage | undefined;
    if (!exact && !aligned) {
      for (let candidateIndex = existing.length - 1; candidateIndex >= 0; candidateIndex -= 1) {
        if (
          !preservedIndexes.has(candidateIndex)
          && samePublicMessage(existing[candidateIndex], message)
        ) {
          contentMatch = existing[candidateIndex];
          preservedIndexes.add(candidateIndex);
          break;
        }
      }
    }
    return publicMessageToChat(
      history.thread_id,
      message,
      fallbackTimestamp + index,
      exact ?? aligned ?? contentMatch,
    );
  });
  if (history.complete !== false) return remoteMessages;

  if (partialOffset !== null) {
    return [...existing.slice(0, Math.max(0, partialOffset)), ...remoteMessages];
  }

  const remoteIds = new Set(remoteMessages.map((message) => message.id));
  const preserved = existing.filter((message) => !remoteIds.has(message.id));
  return [...preserved, ...remoteMessages];
}
