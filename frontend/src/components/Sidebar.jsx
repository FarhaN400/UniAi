import {
  GraduationCap,
  House,
  Plus,
  History,
  Settings,
  PanelLeftClose,
  PanelLeftOpen,
  MessageCircle,
  Trash2,
  X,
  ExternalLink
} from 'lucide-react';

const nav = [
  { id: 'home', icon: House, label: 'Home' },
  { id: 'chat', icon: Plus, label: 'New chat' },
  { id: 'history', icon: History, label: 'History' },
  { id: 'settings', icon: Settings, label: 'Settings' }
];

export default function Sidebar({
  page,
  onNavigate,
  expanded,
  setExpanded,
  mobileOpen,
  setMobileOpen,
  chats,
  onOpenChat,
  onDeleteChat
}) {
  return (
    <>
      <div
        onClick={() => setMobileOpen(false)}
        className={`fixed inset-0 z-30 bg-slate-950/40 lg:hidden ${
          mobileOpen ? 'block' : 'hidden'
        }`}
      />
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex flex-col border-r border-slate-200/75 bg-white/95 dark:bg-slate-900 dark:border-slate-800 transition-all duration-200 ${
          expanded ? 'w-[256px]' : 'w-[78px]'
        } ${mobileOpen ? 'translate-x-0' : '-translate-x-full'} lg:translate-x-0`}
      >
        {/* Brand header */}
        <div className="h-20 flex items-center justify-between px-5">
          <div className="flex gap-2.5 items-center min-w-0">
            <div className="bg-brand-600 text-white p-2.5 rounded-xl shadow-sm shadow-blue-500/20">
              <GraduationCap size={22} />
            </div>
            {expanded && (
              <span className="font-display font-extrabold text-xl tracking-tight text-slate-900 dark:text-white">
                Uni<span className="text-brand-600 dark:text-blue-400">AI</span>
              </span>
            )}
          </div>
          <button
            title="Toggle sidebar"
            onClick={() => {
              if (window.innerWidth < 1024) setMobileOpen(false);
              else setExpanded(v => !v);
            }}
            className="hidden lg:block text-slate-400 hover:text-brand-600 transition"
          >
            {expanded ? <PanelLeftClose size={19} /> : <PanelLeftOpen size={19} />}
          </button>
          <button
            onClick={() => setMobileOpen(false)}
            className="lg:hidden text-slate-500 hover:text-slate-700"
          >
            <X size={21} />
          </button>
        </div>

        {/* Navigation buttons */}
        <nav className="px-3 space-y-1">
          {nav.map(n => {
            const Icon = n.icon;
            const active = page === n.id;
            return (
              <button
                key={n.id}
                title={n.label}
                onClick={() => {
                  onNavigate(n.id);
                  setMobileOpen(false);
                }}
                className={`flex w-full items-center gap-3 rounded-xl px-4 py-3 text-sm font-semibold transition ${
                  active
                    ? 'bg-brand-50 text-brand-700 dark:bg-blue-950/40 dark:text-blue-300'
                    : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 dark:text-slate-400'
                } ${!expanded ? 'justify-center' : ''}`}
              >
                <Icon size={19} className={active ? 'text-brand-600 dark:text-blue-400' : ''} />
                {expanded && n.label}
              </button>
            );
          })}
        </nav>

        {/* Recent conversations */}
        {expanded && (
          <div className="mt-8 flex min-h-0 flex-1 flex-col px-4">
            <div className="flex justify-between items-center mb-3">
              <span className="text-[11px] tracking-[.15em] font-bold text-slate-400 uppercase">
                Recent conversations
              </span>
              <MessageCircle size={14} className="text-slate-400" />
            </div>
            <div className="overflow-auto scrollbar-thin space-y-1 flex-1">
              {chats.length ? (
                chats.slice(0, 10).map(c => (
                  <div
                    key={c.id}
                    className="group flex items-center rounded-xl hover:bg-slate-100 dark:hover:bg-slate-800 transition"
                  >
                    <button
                      onClick={() => {
                        onOpenChat(c.id);
                        setMobileOpen(false);
                      }}
                      className="truncate py-2.5 pl-3 text-left text-xs text-slate-600 dark:text-slate-300 flex-1"
                      title={c.title}
                    >
                      {c.title}
                    </button>
                    <button
                      title="Delete conversation"
                      onClick={() => onDeleteChat(c.id)}
                      className="opacity-0 group-hover:opacity-100 px-2 text-slate-400 hover:text-red-500 transition"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))
              ) : (
                <p className="px-2 text-xs leading-relaxed text-slate-400">
                  Your conversations will appear here.
                </p>
              )}
            </div>
          </div>
        )}

        {/* Official university link card */}
        <div className="mt-auto p-3">
          <a
            href="https://makautwb.ac.in"
            target="_blank"
            rel="noopener noreferrer"
            title="Visit MAKAUT Official Portal (opens in new tab)"
            className={`group block bg-gradient-to-br from-blue-50 to-indigo-50 dark:from-slate-800/90 dark:to-slate-800/60 hover:from-blue-100 hover:to-indigo-100 dark:hover:from-slate-800 dark:hover:to-slate-700/80 rounded-2xl ${
              expanded ? 'p-4' : 'p-2.5'
            } text-center border border-blue-100/60 dark:border-slate-700/60 transition shadow-2xs`}
          >
            {expanded ? (
              <>
                <p className="text-xs font-bold text-brand-700 dark:text-blue-200 group-hover:text-brand-800 flex items-center justify-center gap-1.5">
                  <span>MAKAUT Official Portal</span>
                  <ExternalLink size={12} className="opacity-75 group-hover:opacity-100" />
                </p>
                <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                  makautwb.ac.in · Official notices
                </p>
              </>
            ) : (
              <GraduationCap
                size={20}
                className="mx-auto text-brand-600 dark:text-blue-400 group-hover:scale-110 transition-transform"
              />
            )}
          </a>
        </div>
      </aside>
    </>
  );
}
