import { normalizeUrl } from '../components/FormattedMessage';

// Public frontend setting only. Never expose MongoDB/Pinecone/Groq credentials here.
const BASE = (import.meta.env.VITE_API_BASE_URL || '').trim().replace(/\/+$/, '');
export const demoMode = !BASE;

const sampleSources = [{
  title: 'MAKAUT Official Notice Board',
  url: 'https://makautwb.ac.in/page.php?id=340',
  date: 'Current Session'
}];

export async function askUniAI(question, conversationId) {
  if (!BASE) {
    return {
      answer: `UniAI is running in frontend demo mode. You asked: “${question}”\n\nTo use official MAKAUT notices, configure VITE_API_BASE_URL to the deployed FastAPI backend URL. University notice board: https://makautwb.ac.in/page.php?id=340`,
      sources: sampleSources,
      conversation_id: conversationId,
      demo: true
    };
  }

  const controller = new AbortController();
  // Allow a cold start + cloud LLM inference on the free hosting tier.
  const timeout = setTimeout(() => controller.abort(), 120000);
  try {
    const response = await fetch(`${BASE}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, conversation_id: conversationId }),
      signal: controller.signal
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      throw new Error(detail?.detail || `Server returned HTTP ${response.status}`);
    }
    const result = await response.json();
    if (typeof result.answer !== 'string') {
      throw new Error('Invalid API response: answer missing');
    }
    const validSources = Array.isArray(result.sources)
      ? result.sources.map(s => {
          if (!s || typeof s !== 'object') return null;
          const url = typeof s.url === 'string' ? normalizeUrl(s.url.trim()) : '';
          if (!/^https?:\/\//i.test(url)) return null;
          return { title: s.title || 'Official University Notice', url, date: s.date || null };
        }).filter(Boolean)
      : [];
    return {
      answer: result.answer,
      sources: validSources,
      conversation_id: result.conversation_id || conversationId,
      demo: false
    };
  } catch (error) {
    if (error.name === 'AbortError') {
      const timeoutError = new Error('The cloud backend took too long to respond. It may be starting up. Please retry.');
      timeoutError.name = 'TimeoutError';
      throw timeoutError;
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}
