import { normalizeUrl } from '../components/FormattedMessage';

const BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');
export const demoMode = !BASE;

const sampleSources = [
  {
    title: 'MAKAUT Official Notice Board',
    url: 'https://makautwb.ac.in/page.php?id=340',
    date: 'Current Session'
  }
];

export async function askUniAI(question, conversationId) {
  if (!BASE) {
    await new Promise(r => setTimeout(r, 900));
    return {
      answer: `This is the UniAI frontend demo. You asked: “${question}”\n\nTo get answers from official MAKAUT notices, connect your FastAPI backend in the .env file (e.g. VITE_API_BASE_URL=http://localhost:8000). Once connected, UniAI will retrieve notices and show verified citations and clickable links here. Visit official notice board: https://makautwb.ac.in/page.php?id=340`,
      sources: sampleSources,
      demo: true
    };
  }

  // 180s timeout: Local LLMs (4B parameters) can take 45-90 seconds on consumer hardware
  const controller = new AbortController();
  const timeoutMs = 180000;
  const timeout = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${BASE}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, conversation_id: conversationId }),
      signal: controller.signal
    });

    if (!response.ok) {
      const errText = await response.text().catch(() => '');
      throw new Error(`Server returned ${response.status}${errText ? `: ${errText}` : ''}`);
    }

    const result = await response.json();
    if (typeof result.answer !== 'string') {
      throw new Error('Invalid API response: answer missing');
    }

    // Sanitize and normalize sources
    const validSources = Array.isArray(result.sources)
      ? result.sources
          .map(s => {
            if (!s || typeof s !== 'object') return null;
            const rawUrl = typeof s.url === 'string' ? s.url.trim() : '';
            if (!rawUrl) return null;
            const safeUrl = normalizeUrl(rawUrl);
            if (!/^https?:\/\//i.test(safeUrl)) return null;
            return {
              title: s.title || 'Official University Notice',
              url: safeUrl,
              date: s.date || null
            };
          })
          .filter(Boolean)
      : [];

    return {
      answer: result.answer,
      sources: validSources,
      demo: false
    };
  } catch (err) {
    if (err.name === 'AbortError') {
      const timeoutErr = new Error('Request timed out. The local AI model took longer than 3 minutes to respond. Please ensure Ollama is running and responsive, then try again.');
      timeoutErr.name = 'TimeoutError';
      throw timeoutErr;
    }
    throw err;
  } finally {
    clearTimeout(timeout);
  }
}
