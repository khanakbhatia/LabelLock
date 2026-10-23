import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { api, type User } from './api';

interface AuthValue { token: string | null; user: User | null; loading: boolean; login: (username: string, password: string) => Promise<User>; logout: () => void }
const AuthContext = createContext<AuthValue | null>(null);
const storageKey = 'labellock_token';
const panel = import.meta.env.VITE_APP_MODE === 'panel';
async function readToken(): Promise<string | null> {
  if (panel && typeof chrome !== 'undefined' && chrome.storage?.session) {
    const value = await chrome.storage.session.get(storageKey);
    return typeof value[storageKey] === 'string' ? value[storageKey] : null;
  }
  return localStorage.getItem(storageKey);
}
async function saveToken(token: string | null) {
  if (panel && typeof chrome !== 'undefined' && chrome.storage?.session) {
    if (token) await chrome.storage.session.set({ [storageKey]: token });
    else await chrome.storage.session.remove(storageKey);
  } else if (token) localStorage.setItem(storageKey, token);
  else localStorage.removeItem(storageKey);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    readToken().then(found => { if (active) { setToken(found); if (!found) setLoading(false); } }).catch(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (!token) return;
    let active = true;
    api.me(token).then(found => { if (active) setUser(found); }).catch(() => {
      if (active) { void saveToken(null); setToken(null); setUser(null); }
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [token]);
  const login = async (username: string, password: string) => {
    const result = await api.login(username, password);
    await saveToken(result.token);
    setUser(result.user);
    setToken(result.token);
    setLoading(false);
    return result.user;
  };
  const logout = () => { void saveToken(null); setToken(null); setUser(null); setLoading(false); };
  return <AuthContext.Provider value={{ token, user, loading, login, logout }}>{children}</AuthContext.Provider>;
}
export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('AuthProvider is missing');
  return context;
}
export function homeFor(role: User['role']) {
  switch (role) {
    case 'supplier': return '/supplier';
    case 'qa_specialist': case 'qa_manager': return panel ? '/gmail' : '/inbox';
    case 'shipping_supervisor': return panel ? '/gmail' : '/cases';
    case 'admin': return '/settings';
    case 'agent': return '/service';
  }
}
