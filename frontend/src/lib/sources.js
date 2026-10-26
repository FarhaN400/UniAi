// Sources are scoped to a specific assistant turn; never inherit older
// citations when the latest answer does not cite a notice.
export function getLatestAssistantMessage(messages = []) {
  return [...messages].reverse().find(m => m.role === 'assistant') || null;
}

export function getSourcesForMessage(messages = [], selectedId = null) {
  const selected = selectedId
    ? messages.find(m => m.role === 'assistant' && m.id === selectedId)
    : null;
  const message = selected || getLatestAssistantMessage(messages);
  return Array.isArray(message?.sources) ? message.sources : [];
}
