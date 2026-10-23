import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { api, type User } from './api';

interface AuthValue { token: string | null; user: User | null; loading: boolean; login: (username: string, password: string) => Promise<User>; logout: () => void }
const AuthContext = createContext<AuthValue | null>(null);
const storageKey = 'labellock_token';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(storageKey));
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(!!token);
  useEffect(() => {
    if (!token) { setUser(null); setLoading(false); return; }
    let active = true;
    api.me(token).then(found => { if (active) setUser(found); }).catch(() => {
      if (active) { localStorage.removeItem(storageKey); setToken(null); setUser(null); }
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [token]);
  const login = async (username: string, password: string) => {
    const result = await api.login(username, password);
    localStorage.setItem(storageKey, result.token);
    setUser(result.user);
    setToken(result.token);
    setLoading(false);
    return result.user;
  };
  const logout = () => { localStorage.removeItem(storageKey); setToken(null); setUser(null); setLoading(false); };
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
    case 'qa_specialist': case 'qa_manager': return '/inbox';
    case 'shipping_supervisor': return '/cases';
    case 'admin': return '/settings';
    case 'agent': return '/service';
  }
}
