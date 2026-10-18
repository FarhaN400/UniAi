import { useEffect, useRef, useState } from 'react';
import {
  Bot,
  BookOpen,
  ExternalLink,
  LoaderCircle,
  AlertCircle,
  Sparkles,
  Copy,
  Check,
  FileText,
  Clock,
  RotateCcw
} from 'lucide-react';
import Composer from '../components/Composer';
import SourcePanel from '../components/SourcePanel';
import FormattedMessage, { extractUrlsFromText } from '../components/FormattedMessage';

export default function Chat({ chat, onSend, loading, error }) {
  const [open, setOpen] = useState(false);
  const [copiedId, setCopiedId] = useState(null);
  const [loadingSeconds, setLoadingSeconds] = useState(0);
  const bottom = useRef(null);

  const messages = chat?.messages || [];
  const latestSources =
    [...messages].reverse().find(m => m.role === 'assistant' && m.sources?.length)?.sources || [];

  // Track loading time to give friendly progress feedback
  useEffect(() => {
    let timer;
    if (loading) {
      setLoadingSeconds(0);
      timer = setInterval(() => {
        setLoadingSeconds(prev => prev + 1);
      }, 1000);
    } else {
      setLoadingSeconds(0);
    }
    return () => clearInterval(timer);
  }, [loading]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages.length, loading]);

  useEffect(() => {
    setOpen(false);
  }, [chat?.id]);

  const copyToClipboard = (text, id) => {
    navigator.clipboard?.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  return (
    <div className="relative flex h-full min-h-0">
      <div className="flex-1 min-w-0 flex flex-col">
        {/* Header */}
        <header className="h-16 px-5 md:px-8 border-b border-slate-100 dark:border-slate-800 bg-white/80 dark:bg-slate-900/60 backdrop-blur flex items-center justify-between shrink-0">
          <div className="min-w-0 pr-4">
            <div className="font-display text-sm font-bold text-slate-800 dark:text-white truncate max-w-[200px] sm:max-w-md md:max-w-xl">
              {chat?.title || 'New conversation'}
            </div>
            <div className="text-[11px] text-slate-400 flex items-center gap-1.5">
              <span>UniAI</span>
              <span>·</span>
              <span className="text-emerald-500 font-medium">MAKAUT Academic Assistant</span>
            </div>
          </div>
          <button
            onClick={() => setOpen(v => !v)}
            className={`flex items-center gap-2 px-3.5 py-2 rounded-xl border text-xs font-semibold transition ${
              open
                ? 'bg-brand-50 border-brand-300 text-brand-700 dark:bg-blue-950/50 dark:border-blue-700 dark:text-blue-300'
                : 'border-slate-200 text-slate-600 hover:border-brand-400 dark:border-slate-700 dark:text-slate-300'
            }`}
          >
            <BookOpen size={15} className="text-brand-600 dark:text-blue-400" />
            <span>Sources</span>
            {latestSources.length > 0 && (
              <span className="px-1.5 py-0.2 rounded-full text-[10px] font-bold bg-brand-100 dark:bg-blue-900 text-brand-700 dark:text-blue-200">
                {latestSources.length}
              </span>
            )}
          </button>
        </header>

        {/* Message scroll container */}
        <div className="flex-1 overflow-y-auto scrollbar-thin px-4 md:px-8">
          <div className="max-w-[780px] mx-auto py-8 space-y-6">
            {messages.map(m => {
              const isAssistant = m.role === 'assistant';
              const detectedLinks = isAssistant ? extractUrlsFromText(m.text) : [];

              return (
                <div
                  key={m.id}
                  className={`flex gap-3.5 ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  {isAssistant && (
                    <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-brand-600 to-violet-600 shrink-0 flex justify-center items-center shadow-sm shadow-blue-500/20">
                      <Bot size={18} className="text-white" />
                    </div>
                  )}

                  <div
                    className={`max-w-[88%] sm:max-w-[82%] min-w-0 ${
                      m.role === 'user'
                        ? 'rounded-2xl rounded-tr-sm bg-brand-50 dark:bg-slate-800 border border-brand-100/60 dark:border-slate-700 px-5 py-3.5 text-slate-800 dark:text-white shadow-sm'
                        : 'rounded-2xl bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 p-5 shadow-sm text-slate-800 dark:text-slate-100'
                    }`}
                  >
                    {/* Render message body with full markdown & clickable link support */}
                    <div className="message-content text-sm leading-7">
                      <FormattedMessage text={m.text} isUser={m.role === 'user'} />
                    </div>

                    {/* Detected document/link chips if URLs are in the message */}
                    {isAssistant && detectedLinks.length > 0 && (
                      <div className="mt-4 pt-3 border-t border-slate-100 dark:border-slate-800">
                        <div className="text-[11px] font-bold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                          <FileText size={12} className="text-brand-500" />
                          <span>Direct Links & Notice Documents ({detectedLinks.length})</span>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {detectedLinks.map((link, idx) => (
                            <a
                              key={`chip-${idx}`}
                              href={link.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-brand-50 hover:bg-brand-100 text-brand-700 dark:bg-slate-800 dark:hover:bg-slate-700 dark:text-blue-300 border border-brand-200 dark:border-slate-700 transition shadow-2xs group"
                            >
                              {link.isPdf ? (
                                <FileText size={13} className="text-red-500 shrink-0" />
                              ) : (
                                <ExternalLink size={13} className="text-brand-600 dark:text-blue-400 shrink-0" />
                              )}
                              <span className="truncate max-w-[220px]">{link.title}</span>
                              <ExternalLink
                                size={11}
                                className="opacity-60 group-hover:opacity-100 group-hover:translate-x-0.5 transition-transform shrink-0"
                              />
                            </a>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Assistant metadata footer */}
                    {isAssistant && (
                      <div className="mt-3.5 pt-2 flex flex-wrap gap-3 items-center justify-between text-xs text-slate-400">
                        <div className="flex flex-wrap gap-2 items-center">
                          {m.demo && (
                            <span className="text-[10px] rounded-full px-2 py-0.5 bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 font-bold border border-amber-200 dark:border-amber-900">
                              DEMO RESPONSE
                            </span>
                          )}

                          {m.sources?.length > 0 && (
                            <button
                              onClick={() => setOpen(true)}
                              className="text-xs font-semibold text-brand-600 dark:text-blue-400 hover:text-brand-700 dark:hover:text-blue-300 flex items-center gap-1.5 bg-brand-50/60 dark:bg-blue-950/30 px-2.5 py-1 rounded-lg border border-brand-100 dark:border-blue-900/50 transition"
                            >
                              <BookOpen size={13} />
                              <span>{m.sources.length} official notice source(s)</span>
                              <ExternalLink size={11} />
                            </button>
                          )}
                        </div>

                        <button
                          onClick={() => copyToClipboard(m.text, m.id)}
                          className="flex items-center gap-1 text-[11px] text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition"
                          title="Copy response"
                        >
                          {copiedId === m.id ? (
                            <>
                              <Check size={12} className="text-emerald-500" />
                              <span className="text-emerald-500">Copied</span>
                            </>
                          ) : (
                            <>
                              <Copy size={12} />
                              <span>Copy</span>
                            </>
                          )}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}

            {/* Dynamic loading state */}
            {loading && (
              <div className="flex items-start gap-3.5 text-sm">
                <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-brand-600 to-violet-600 shrink-0 flex justify-center items-center shadow-sm">
                  <Sparkles size={18} className="text-white animate-pulse" />
                </div>
                <div className="rounded-2xl bg-white dark:bg-slate-900 border border-slate-200/80 dark:border-slate-800 p-4 shadow-sm min-w-[280px]">
                  <div className="flex items-center gap-2.5 font-semibold text-slate-700 dark:text-slate-200">
                    <LoaderCircle size={16} className="animate-spin text-brand-600 dark:text-blue-400" />
                    <span>
                      {loadingSeconds < 8
                        ? 'Understanding query & searching notices…'
                        : loadingSeconds < 25
                        ? 'Analyzing official university documents…'
                        : 'Synthesizing verified claims with citations…'}
                    </span>
                  </div>
                  <div className="mt-2 text-xs text-slate-400 flex items-center gap-1.5">
                    <Clock size={12} />
                    <span>
                      Local LLM inference in progress ({loadingSeconds}s)
                      {loadingSeconds > 30 && ' · First query loads model into GPU memory'}
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* Error display with retry */}
            {error && (
              <div className="flex items-start gap-3 bg-red-50 text-red-800 dark:bg-red-950/40 dark:text-red-200 border border-red-200 dark:border-red-900/60 p-4 rounded-2xl text-xs leading-relaxed shadow-sm">
                <AlertCircle size={18} className="shrink-0 text-red-500 mt-0.5" />
                <div className="flex-1">
                  <div className="font-bold text-red-900 dark:text-red-100">Request Error</div>
                  <div className="mt-1">{error}</div>
                  {messages.length > 0 && (
                    <button
                      onClick={() => {
                        const lastUserMsg = [...messages].reverse().find(m => m.role === 'user');
                        if (lastUserMsg) onSend(lastUserMsg.text);
                      }}
                      className="mt-2.5 inline-flex items-center gap-1 px-3 py-1.5 bg-red-100 hover:bg-red-200 dark:bg-red-900/50 dark:hover:bg-red-800/60 text-red-800 dark:text-red-200 rounded-lg font-semibold transition"
                    >
                      <RotateCcw size={12} /> Retry last query
                    </button>
                  )}
                </div>
              </div>
            )}

            <div ref={bottom} />
          </div>
        </div>

        {/* Input Composer */}
        <div className="px-4 md:px-8 pb-4 pt-3 bg-gradient-to-t from-[#f7f9fd] via-[#f7f9fd]/90 to-transparent dark:from-slate-950 dark:via-slate-950/90 shrink-0">
          <div className="max-w-[780px] mx-auto">
            <Composer onSend={onSend} loading={loading} />
            <p className="mt-2 text-center text-[10px] text-slate-400 flex items-center justify-center gap-1">
              <span>UniAI can make mistakes. Always verify important dates & details with</span>
              <a
                href="https://makautwb.ac.in/page.php?id=340"
                target="_blank"
                rel="noopener noreferrer"
                className="text-brand-600 dark:text-blue-400 underline font-medium hover:text-brand-700"
              >
                official notices
              </a>.
            </p>
          </div>
        </div>
      </div>

      {/* Sources Right Sidebar */}
      <SourcePanel sources={latestSources} open={open} onClose={() => setOpen(false)} />
    </div>
  );
}
