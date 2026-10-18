const KEY='uniai_conversations_v1';const THEME_KEY='uniai_theme_v1';
export const loadChats=()=>{try{return JSON.parse(localStorage.getItem(KEY)||'[]')}catch{return []}};
export const saveChats=(chats)=>{try{localStorage.setItem(KEY,JSON.stringify(chats))}catch{}};
export const getTheme=()=>localStorage.getItem(THEME_KEY)||'light';
export const saveTheme=(value)=>localStorage.setItem(THEME_KEY,value);
export const makeId=()=>globalThis.crypto?.randomUUID?.()||`${Date.now()}-${Math.random().toString(36).slice(2)}`;
