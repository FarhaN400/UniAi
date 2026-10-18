import { useEffect, useState } from 'react';
import { Menu, Sparkles } from 'lucide-react';
import Sidebar from './components/Sidebar';
import Home from './pages/Home';
import Chat from './pages/Chat';
import History from './pages/History';
import Settings from './pages/Settings';
import { loadChats, saveChats, getTheme, saveTheme, makeId } from './lib/storage';
import { askUniAI, demoMode } from './lib/api';

export default function App() {
  const [page, setPage] = useState('home');
  const [chats, setChats] = useState(loadChats);
  const [activeId, setActiveId] = useState(null);
  const [expanded, setExpanded] = useState(true);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [theme, setTheme] = useState(getTheme);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const activeChat = chats.find(c => c.id === activeId);

  useEffect(() => {
    saveChats(chats);
  }, [chats]);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    saveTheme(theme);
  }, [theme]);

  function navigate(to) {
    setError('');
    if (to === 'chat') {
      setActiveId(null);
      setPage('home');
    } else {
      setPage(to);
    }
  }

  function openChat(id) {
    setActiveId(id);
    setPage('chat');
    setError('');
  }

  function removeChat(id) {
    if (!window.confirm('Delete this conversation?')) return;
    setChats(old => old.filter(c => c.id !== id));
    if (activeId === id) {
      setActiveId(null);
      setPage('home');
    }
  }

  async function send(question) {
    if (loading) return;
    setError('');

    const id = activeId || makeId();
    const isNew = !activeId;
    const message = {
      id: makeId(),
      role: 'user',
      text: question,
      timestamp: Date.now()
    };

    setActiveId(id);
    setPage('chat');

    setChats(prev =>
      isNew
        ? [
            {
              id,
              title: question.slice(0, 49),
              createdAt: Date.now(),
              updatedAt: Date.now(),
              messages: [message]
            },
            ...prev
          ]
        : prev.map(c =>
            c.id === id
              ? {
                  ...c,
                  updatedAt: Date.now(),
                  messages: [...c.messages, message]
                }
              : c
          )
    );

    setLoading(true);

    try {
      const result = await askUniAI(question, id);

      setChats(prev =>
        prev.map(c =>
          c.id === id
            ? {
                ...c,
                updatedAt: Date.now(),
                messages: [
                  ...c.messages,
                  {
                    id: makeId(),
                    role: 'assistant',
                    text: result.answer,
                    sources: result.sources,
                    demo: result.demo,
                    timestamp: Date.now()
                  }
                ]
              }
            : c
        )
      );
    } catch (e) {
      const isTimeout = e.name === 'TimeoutError' || e.name === 'AbortError';
      setError(
        isTimeout
          ? e.message || 'Request timed out. The local AI model took longer than expected. Please verify Ollama is running and try again.'
          : `Unable to get a response: ${e.message}`
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="h-screen overflow-hidden bg-[#f7f9fd] dark:bg-slate-950 text-ink flex">
      <Sidebar
        page={page}
        onNavigate={navigate}
        expanded={expanded}
        setExpanded={setExpanded}
        mobileOpen={mobileOpen}
        setMobileOpen={setMobileOpen}
        chats={chats}
        onOpenChat={openChat}
        onDeleteChat={removeChat}
      />

      <div
        className={`flex-1 min-w-0 flex flex-col transition-all duration-200 ${
          expanded ? 'lg:ml-[256px]' : 'lg:ml-[78px]'
        }`}
      >
        {/* Mobile Header */}
        <div className="h-14 lg:hidden flex items-center gap-3 px-4 border-b border-slate-200/80 dark:border-slate-800 bg-white/90 dark:bg-slate-900/90 backdrop-blur">
          <button
            aria-label="Open navigation"
            onClick={() => setMobileOpen(true)}
            className="p-1 rounded-lg text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <Menu size={21} />
          </button>
          <div className="font-display font-bold text-slate-800 dark:text-white">
            Uni<span className="text-brand-600 dark:text-blue-400">AI</span>
          </div>
        </div>

        {/* Page Content */}
        {page === 'home' && (
          <main className="overflow-y-auto flex-1">
            <Home onSend={send} loading={loading} />
          </main>
        )}
        {page === 'chat' && (
          <main className="min-h-0 flex-1">
            <Chat chat={activeChat} onSend={send} loading={loading} error={error} />
          </main>
        )}
        {page === 'history' && (
          <main className="overflow-y-auto flex-1">
            <History chats={chats} onOpenChat={openChat} onDeleteChat={removeChat} />
          </main>
        )}
        {page === 'settings' && (
          <main className="overflow-y-auto flex-1">
            <Settings
              theme={theme}
              onThemeChange={setTheme}
              onClearAll={() => {
                setChats([]);
                setActiveId(null);
                setPage('home');
              }}
            />
          </main>
        )}

        {demoMode && (
          <div className="absolute bottom-2.5 right-3 pointer-events-none hidden md:flex items-center gap-1.5 rounded-full bg-amber-50 dark:bg-amber-900/50 border border-amber-200 dark:border-amber-800 px-3 py-1 text-[10px] font-bold text-amber-700 dark:text-amber-200 shadow-xs">
            <Sparkles size={11} /> Demo Mode
          </div>
        )}
      </div>
    </div>
  );
}
