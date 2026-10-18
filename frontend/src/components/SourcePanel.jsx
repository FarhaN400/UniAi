import { BookOpen, ExternalLink, X, FileSearch, ShieldCheck, FileText, Globe } from 'lucide-react';
import { normalizeUrl } from './FormattedMessage';

export default function SourcePanel({ sources, open, onClose }) {
  return (
    <aside
      className={`${
        open ? 'flex' : 'hidden'
      } w-full lg:w-[340px] shrink-0 flex-col border-l border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 absolute lg:static z-20 right-0 top-0 bottom-0 max-w-[390px] shadow-xl lg:shadow-none transition-all duration-200`}
    >
      {/* Panel Header */}
      <div className="flex justify-between items-center p-5 border-b border-slate-100 dark:border-slate-800">
        <div className="flex items-center gap-2 font-display font-bold text-slate-800 dark:text-white">
          <BookOpen size={18} className="text-brand-600 dark:text-blue-400" />
          <span>Official sources</span>
          {sources.length > 0 && (
            <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-brand-50 text-brand-700 dark:bg-blue-950/60 dark:text-blue-300">
              {sources.length}
            </span>
          )}
        </div>
        <button
          aria-label="Close sources"
          className="p-1 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition"
          onClick={onClose}
        >
          <X size={19} />
        </button>
      </div>

      {/* Sources List */}
      <div className="p-5 space-y-3.5 overflow-auto scrollbar-thin flex-1">
        {sources.length > 0 ? (
          sources.map((s, i) => {
            const safeUrl = normalizeUrl(s.url);
            const isPdf = /\.pdf($|\?)/i.test(s.url || '');

            return (
              <a
                href={safeUrl}
                target="_blank"
                rel="noreferrer noopener"
                key={`${safeUrl}-${i}`}
                className="group block rounded-2xl border border-slate-200/90 dark:border-slate-700/80 p-4 hover:border-brand-500 hover:shadow-sm bg-white dark:bg-slate-800/80 transition-all duration-150"
              >
                <div className="flex items-center justify-between">
                  <span className="inline-flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-brand-600 dark:text-blue-300">
                    {isPdf ? (
                      <FileText size={12} className="text-red-500 shrink-0" />
                    ) : (
                      <Globe size={12} className="text-brand-500 shrink-0" />
                    )}
                    Official Notice {i + 1}
                  </span>
                  <ExternalLink
                    size={14}
                    className="text-slate-400 group-hover:text-brand-600 dark:group-hover:text-blue-400 group-hover:translate-x-0.5 transition-transform"
                  />
                </div>
                <div className="mt-2 text-sm font-semibold text-slate-800 dark:text-slate-100 group-hover:text-brand-700 dark:group-hover:text-blue-300 line-clamp-2">
                  {s.title || 'University official notice'}
                </div>
                {s.date && (
                  <div className="mt-2 text-xs text-slate-400 flex items-center gap-1">
                    <span>Issued: {s.date}</span>
                  </div>
                )}
                <div className="mt-2.5 pt-2 border-t border-slate-100 dark:border-slate-700/60 text-[11px] text-brand-600 dark:text-blue-400 font-medium truncate flex items-center gap-1">
                  <span>Open PDF / document</span>
                  <ExternalLink size={10} />
                </div>
              </a>
            );
          })
        ) : (
          <div className="text-center py-12">
            <FileSearch className="mx-auto text-slate-300 dark:text-slate-600" size={38} />
            <p className="mt-3 text-sm font-semibold text-slate-700 dark:text-slate-200">
              No verified sources yet
            </p>
            <p className="mt-2 text-xs leading-6 text-slate-400 max-w-[240px] mx-auto">
              When UniAI grounds an answer in university notices, clickable document links will appear here.
            </p>
          </div>
        )}
      </div>

      {/* Footer disclaimer */}
      <div className="mt-auto p-4 text-xs text-slate-400 flex gap-2.5 border-t border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/40">
        <ShieldCheck size={16} className="shrink-0 text-emerald-500 mt-0.5" />
        <span>Always verify critical dates and requirements in the original university notices.</span>
      </div>
    </aside>
  );
}
