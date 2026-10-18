import {
  Settings as SettingsIcon,
  Moon,
  Sun,
  Trash2,
  Info,
  Wifi,
  WifiOff,
  ExternalLink,
  Globe,
  GraduationCap
} from 'lucide-react';
import { demoMode } from '../lib/api';

const officialLinks = [
  {
    title: 'MAKAUT Official Website',
    url: 'https://makautwb.ac.in',
    desc: 'University homepage & main announcements'
  },
  {
    title: 'University Notice Board',
    url: 'https://makautwb.ac.in/page.php?id=340',
    desc: 'Primary source of all official university notifications'
  },
  {
    title: 'MAKAUT Examination Portal',
    url: 'https://makautexam.net',
    desc: 'Exam schedules, admit cards & semester results'
  },
  {
    title: 'Student Registration / UCanApply',
    url: 'https://makaut1.ucanapply.com',
    desc: 'Application form fill-up & student account services'
  }
];

export default function Settings({ theme, onThemeChange, onClearAll }) {
  return (
    <div className="max-w-3xl mx-auto px-6 py-12">
      <div className="flex items-center gap-3">
        <div className="bg-brand-50 dark:bg-slate-800 rounded-2xl p-3 text-brand-600 dark:text-blue-400">
          <SettingsIcon size={24} />
        </div>
        <div>
          <h1 className="font-display font-bold text-3xl dark:text-white">Settings & Resources</h1>
          <p className="text-sm text-slate-500 mt-1">
            Customize appearance, manage local data, and access verified university links.
          </p>
        </div>
      </div>

      <div className="mt-10 space-y-5">
        {/* Appearance */}
        <section className="bg-white dark:bg-slate-800 border dark:border-slate-700 rounded-2xl p-5 shadow-xs">
          <h2 className="font-bold text-sm dark:text-white">Appearance</h2>
          <p className="text-xs text-slate-400 mt-1">Choose your preferred interface theme.</p>
          <div className="flex gap-3 mt-4">
            {[
              { value: 'light', label: 'Light', icon: Sun },
              { value: 'dark', label: 'Dark', icon: Moon }
            ].map(o => {
              const Icon = o.icon;
              return (
                <button
                  key={o.value}
                  onClick={() => onThemeChange(o.value)}
                  className={`flex items-center gap-2 rounded-xl border px-5 py-3 text-sm font-medium transition ${
                    theme === o.value
                      ? 'border-brand-600 bg-brand-50 dark:bg-blue-950/40 text-brand-700 dark:text-blue-300 font-semibold'
                      : 'border-slate-200 dark:border-slate-700 text-slate-500 hover:border-slate-300'
                  }`}
                >
                  <Icon size={16} />
                  {o.label}
                </button>
              );
            })}
          </div>
        </section>

        {/* Official Links */}
        <section className="bg-white dark:bg-slate-800 border dark:border-slate-700 rounded-2xl p-5 shadow-xs">
          <div className="flex items-center gap-2 font-bold text-sm dark:text-white">
            <GraduationCap size={17} className="text-brand-600 dark:text-blue-400" />
            <span>Official MAKAUT University Links</span>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Verified web portals for Maulana Abul Kalam Azad University of Technology.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mt-4">
            {officialLinks.map(link => (
              <a
                key={link.url}
                href={link.url}
                target="_blank"
                rel="noopener noreferrer"
                className="group flex flex-col justify-between p-3.5 rounded-xl border border-slate-200/90 dark:border-slate-700/80 hover:border-brand-500 bg-slate-50/50 dark:bg-slate-800/50 hover:bg-white dark:hover:bg-slate-800 transition"
              >
                <div>
                  <div className="text-xs font-bold text-slate-800 dark:text-slate-100 group-hover:text-brand-600 dark:group-hover:text-blue-300 flex items-center justify-between">
                    <span>{link.title}</span>
                    <ExternalLink size={13} className="text-slate-400 group-hover:text-brand-600 shrink-0" />
                  </div>
                  <div className="text-[11px] text-slate-400 mt-1">{link.desc}</div>
                </div>
                <div className="mt-2 text-[10px] text-brand-600 dark:text-blue-400 font-mono truncate">
                  {link.url}
                </div>
              </a>
            ))}
          </div>
        </section>

        {/* Backend connection */}
        <section className="bg-white dark:bg-slate-800 border dark:border-slate-700 rounded-2xl p-5 shadow-xs">
          <h2 className="font-bold text-sm dark:text-white">Backend connection</h2>
          <p className="text-xs text-slate-400 mt-2 flex items-center gap-2">
            {demoMode ? (
              <WifiOff size={16} className="text-amber-500" />
            ) : (
              <Wifi size={16} className="text-emerald-500" />
            )}
            <span>
              {demoMode
                ? 'Demo mode active — No API URL configured'
                : 'FastAPI Backend connected — live notice queries will be processed'}
            </span>
          </p>
          <p className="text-xs text-slate-400 mt-3 font-mono bg-slate-50 dark:bg-slate-900/50 p-2.5 rounded-lg border border-slate-200/60 dark:border-slate-700/60">
            Configure <code className="text-brand-600 dark:text-blue-400 font-bold">VITE_API_BASE_URL=http://localhost:8000</code> in frontend/.env
          </p>
        </section>

        {/* Conversation data */}
        <section className="bg-white dark:bg-slate-800 border dark:border-slate-700 rounded-2xl p-5 shadow-xs">
          <h2 className="font-bold text-sm dark:text-white">Conversation data</h2>
          <p className="text-xs text-slate-400 mt-2">
            Chat history is saved locally in your browser’s localStorage.
          </p>
          <button
            onClick={() => {
              if (window.confirm('Delete all local chat history? This cannot be undone.')) {
                onClearAll();
              }
            }}
            className="mt-4 inline-flex gap-2 items-center px-4 py-2.5 rounded-xl bg-red-50 hover:bg-red-100 dark:bg-red-950/30 dark:hover:bg-red-900/40 text-red-600 dark:text-red-300 text-xs font-bold transition"
          >
            <Trash2 size={15} />
            <span>Clear all chat history</span>
          </button>
        </section>

        {/* Disclaimer */}
        <section className="flex gap-3 p-5 text-xs text-slate-500 dark:text-slate-400">
          <Info size={18} className="shrink-0 text-brand-600 dark:text-blue-400 mt-0.5" />
          <p>
            UniAI is an independent academic assistant project. Always consult original university notices and authorized college authorities for official decisions.
          </p>
        </section>
      </div>
    </div>
  );
}
