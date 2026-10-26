// A retry is valid only for the newest unanswered user message.
export function isPendingRetry(chat, question, messageId) {
  const last = chat?.messages?.at(-1);
  return Boolean(
    last && last.role === 'user' && last.id === messageId &&
    last.text === question && messageId
  );
}
