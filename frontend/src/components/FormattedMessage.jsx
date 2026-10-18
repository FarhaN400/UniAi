import React from 'react';
import { ExternalLink, FileText, Globe } from 'lucide-react';

/**
 * Normalizes a URL so that it has an http:// or https:// protocol.
 * Prevents javascript: or data: XSS vectors.
 */
export function normalizeUrl(url) {
  if (!url || typeof url !== 'string') return '';
  const trimmed = url.trim();
  // Disallow unsafe schemes
  if (/^(javascript|data|vbscript):/i.test(trimmed)) {
    return '#';
  }
  if (/^https?:\/\//i.test(trimmed)) {
    return trimmed;
  }
  if (/^www\./i.test(trimmed)) {
    return `https://${trimmed}`;
  }
  return `https://${trimmed}`;
}

/**
 * Strips trailing punctuation often caught by regex (like period, comma, closing paren)
 */
function cleanUrlAndTrailingPunctuation(rawUrl) {
  let url = rawUrl;
  let trailing = '';
  while (url.length > 0 && /[.,;:!?)\]}>]$/.test(url)) {
    // If there's a closing parenthesis, but no open parenthesis in the url, strip it
    if (url.endsWith(')')) {
      const openCount = (url.match(/\(/g) || []).length;
      const closeCount = (url.match(/\)/g) || []).length;
      if (openCount >= closeCount) break;
    }
    trailing = url.slice(-1) + trailing;
    url = url.slice(0, -1);
  }
  return { cleanUrl: url, trailing };
}

/**
 * Formats inline text with bold, italic, code, markdown links, and auto-linked raw URLs.
 */
function renderInlineContent(text) {
  if (!text) return null;

  // Regex to match:
  // 1. Markdown link: [label](url)
  // 2. Raw URL: (https?:\/\/[^\s]+|www\.[^\s]+)
  // 3. Inline code: `code`
  // 4. Bold: \*\*(.*?)\*\*
  // 5. Italic: \*(.*?)\*
  const combinedRegex = /(\[([^\]]+)\]\((https?:\/\/[^\s)]+|www\.[^\s)]+)\))|((?:https?:\/\/|www\.)[^\s<>"']+)|(`[^`]+`)|(\*\*([^*]+)\*\*)|(\*([^*]+)\*)/g;

  const parts = [];
  let lastIndex = 0;
  let match;

  while ((match = combinedRegex.exec(text)) !== null) {
    // Plain text before the match
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }

    if (match[1]) {
      // 1. Markdown link [label](url)
      const label = match[2];
      const rawUrl = match[3];
      const isPdf = /\.pdf($|\?)/i.test(rawUrl);
      const safeHref = normalizeUrl(rawUrl);

      parts.push(
        <a
          key={`md-link-${match.index}`}
          href={safeHref}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 font-semibold text-brand-600 dark:text-blue-400 hover:text-brand-700 dark:hover:text-blue-300 underline underline-offset-2 decoration-brand-300 dark:decoration-blue-500 hover:decoration-brand-600 transition group"
          title={`Open ${safeHref}`}
        >
          {isPdf && <FileText size={12} className="inline shrink-0 text-red-500" />}
          <span>{label}</span>
          <ExternalLink size={11} className="inline shrink-0 opacity-75 group-hover:opacity-100 group-hover:translate-x-0.5 transition-transform" />
        </a>
      );
    } else if (match[4]) {
      // 2. Raw URL (https://... or www....)
      const { cleanUrl, trailing } = cleanUrlAndTrailingPunctuation(match[4]);
      const safeHref = normalizeUrl(cleanUrl);
      const isPdf = /\.pdf($|\?)/i.test(cleanUrl);
      // Friendly display label for long links
      let displayLabel = cleanUrl;
      try {
        const parsed = new URL(safeHref);
        // Shorten long paths
        if (parsed.pathname.length > 25) {
          const pathSegments = parsed.pathname.split('/').filter(Boolean);
          const fileName = pathSegments[pathSegments.length - 1] || '';
          displayLabel = `${parsed.hostname}/…/${fileName}`;
        }
      } catch {
        if (displayLabel.length > 40) {
          displayLabel = displayLabel.slice(0, 37) + '…';
        }
      }

      parts.push(
        <React.Fragment key={`raw-url-${match.index}`}>
          <a
            href={safeHref}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 font-semibold text-brand-600 dark:text-blue-400 hover:text-brand-700 dark:hover:text-blue-300 underline underline-offset-2 decoration-brand-300 dark:decoration-blue-500 hover:decoration-brand-600 transition group break-all"
            title={`Visit: ${safeHref}`}
          >
            {isPdf ? (
              <FileText size={12} className="inline shrink-0 text-red-500" />
            ) : (
              <Globe size={12} className="inline shrink-0 text-brand-500 dark:text-blue-400" />
            )}
            <span>{displayLabel}</span>
            <ExternalLink size={11} className="inline shrink-0 opacity-75 group-hover:opacity-100 group-hover:translate-x-0.5 transition-transform" />
          </a>
          {trailing}
        </React.Fragment>
      );
    } else if (match[5]) {
      // 3. Inline code `code`
      const code = match[5].slice(1, -1);
      parts.push(
        <code
          key={`code-${match.index}`}
          className="px-1.5 py-0.5 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200 font-mono text-xs border border-slate-200/60 dark:border-slate-700"
        >
          {code}
        </code>
      );
    } else if (match[6]) {
      // 4. Bold **text**
      parts.push(
        <strong key={`bold-${match.index}`} className="font-bold text-slate-900 dark:text-white">
          {match[7]}
        </strong>
      );
    } else if (match[8]) {
      // 5. Italic *text*
      parts.push(
        <em key={`italic-${match.index}`} className="italic">
          {match[9]}
        </em>
      );
    }

    lastIndex = combinedRegex.lastIndex;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts;
}

/**
 * Extracts all distinct URLs from a text block
 */
export function extractUrlsFromText(text) {
  if (!text || typeof text !== 'string') return [];
  const regex = /(?:https?:\/\/|www\.)[^\s<>"')\]}]+/gi;
  const matches = text.match(regex) || [];
  const unique = [];
  const seen = new Set();

  for (const m of matches) {
    const { cleanUrl } = cleanUrlAndTrailingPunctuation(m);
    const normalized = normalizeUrl(cleanUrl);
    if (normalized && !seen.has(normalized)) {
      seen.add(normalized);
      const isPdf = /\.pdf($|\?)/i.test(cleanUrl);
      let title = 'Official Link';
      try {
        const u = new URL(normalized);
        const file = u.pathname.split('/').filter(Boolean).pop();
        if (file) {
          title = decodeURIComponent(file.replace(/[-_]/g, ' '));
        } else {
          title = u.hostname;
        }
      } catch {
        title = cleanUrl;
      }
      unique.push({ url: normalized, raw: cleanUrl, isPdf, title });
    }
  }

  return unique;
}

/**
 * Renders multi-line structured text with paragraphs, bullet lists, numbered lists,
 * blockquotes, headers, and fully clickable links.
 */
export default function FormattedMessage({ text, isUser = false }) {
  if (!text) return null;

  // Split into lines to parse line-level markdown (lists, headers, quotes)
  const lines = text.split('\n');
  const elements = [];
  let currentList = null; // { type: 'ul' | 'ol', items: [] }

  function flushList() {
    if (!currentList) return;
    const ListTag = currentList.type;
    elements.push(
      <ListTag
        key={`list-${elements.length}`}
        className={`my-2 space-y-1 pl-5 ${currentList.type === 'ul' ? 'list-disc' : 'list-decimal'} marker:text-brand-500`}
      >
        {currentList.items.map((item, idx) => (
          <li key={idx} className="leading-6">
            {renderInlineContent(item)}
          </li>
        ))}
      </ListTag>
    );
    currentList = null;
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      flushList();
      // Empty line / paragraph gap
      if (elements.length > 0 && elements[elements.length - 1]?.type !== 'div') {
        elements.push(<div key={`spacer-${i}`} className="h-2" />);
      }
      continue;
    }

    // Unordered bullet list: "- item" or "* item"
    const bulletMatch = line.match(/^(\s*)[-*•]\s+(.*)$/);
    if (bulletMatch) {
      if (currentList && currentList.type !== 'ul') flushList();
      if (!currentList) currentList = { type: 'ul', items: [] };
      currentList.items.push(bulletMatch[2]);
      continue;
    }

    // Ordered list: "1. item"
    const numberMatch = line.match(/^(\s*)\d+\.\s+(.*)$/);
    if (numberMatch) {
      if (currentList && currentList.type !== 'ol') flushList();
      if (!currentList) currentList = { type: 'ol', items: [] };
      currentList.items.push(numberMatch[2]);
      continue;
    }

    // If it's not a list item, flush any pending list
    flushList();

    // Headers: "### Header", "## Header", "# Header"
    const headerMatch = line.match(/^(#{1,3})\s+(.*)$/);
    if (headerMatch) {
      const level = headerMatch[1].length;
      const headerText = headerMatch[2];
      if (level === 1) {
        elements.push(
          <h2 key={`h1-${i}`} className="text-base font-bold text-slate-900 dark:text-white mt-3 mb-1">
            {renderInlineContent(headerText)}
          </h2>
        );
      } else if (level === 2) {
        elements.push(
          <h3 key={`h2-${i}`} className="text-sm font-bold text-slate-900 dark:text-white mt-2 mb-1">
            {renderInlineContent(headerText)}
          </h3>
        );
      } else {
        elements.push(
          <h4 key={`h3-${i}`} className="text-sm font-semibold text-slate-800 dark:text-slate-100 mt-2 mb-0.5">
            {renderInlineContent(headerText)}
          </h4>
        );
      }
      continue;
    }

    // Blockquote: "> quote"
    if (line.startsWith('>')) {
      const quoteText = line.replace(/^>\s?/, '');
      elements.push(
        <blockquote
          key={`quote-${i}`}
          className="my-2 border-l-4 border-brand-400 dark:border-brand-600 pl-3 py-1 text-slate-600 dark:text-slate-300 italic bg-brand-50/50 dark:bg-slate-800/40 rounded-r-lg"
        >
          {renderInlineContent(quoteText)}
        </blockquote>
      );
      continue;
    }

    // Normal paragraph line
    elements.push(
      <p key={`p-${i}`} className="leading-7 min-w-0 break-words">
        {renderInlineContent(line)}
      </p>
    );
  }

  flushList();

  return (
    <div className={`formatted-message ${isUser ? '' : 'space-y-1'}`}>
      {elements}
    </div>
  );
}
