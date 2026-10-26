const KEY='uniai_conversations_v1';const THEME_KEY='uniai_theme_v1';
export const loadChats=()=>{try{return JSON.parse(localStorage.getItem(KEY)||'[]')}catch{return []}};
export const saveChats=(chats)=>{try{localStorage.setItem(KEY,JSON.stringify(chats))}catch{}};
export const getTheme=()=>localStorage.getItem(THEME_KEY)||'light';
export const saveTheme=(value)=>localStorage.setItem(THEME_KEY,value);
// UUID preferred; secure random bytes also work in browsers without randomUUID.
// Backend accepts only alphanumeric/hyphen/underscore conversation IDs.
export const makeId = () => {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  if (globalThis.crypto?.getRandomValues) {
    const bytes = new Uint8Array(16);
    globalThis.crypto.getRandomValues(bytes);
    return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
  }
  // Local fallback for non-secure legacy browsers: never send punctuation
  // that the FastAPI request schema rejects.
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
};
