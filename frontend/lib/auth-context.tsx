'use client';

import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import * as api from './api';

interface AuthState {
  username: string | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [username, setUsername] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = api.getToken();
    if (!token) {
      setLoading(false);
      return;
    }
    api
      .whoami()
      .then((res) => setUsername(res.username))
      .catch(() => api.setToken(null))
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (u: string, p: string) => {
    const res = await api.login(u, p);
    api.setToken(res.access_token);
    setUsername(res.username);
  }, []);

  const register = useCallback(async (u: string, p: string) => {
    const res = await api.register(u, p);
    api.setToken(res.access_token);
    setUsername(res.username);
  }, []);

  const logout = useCallback(() => {
    api.setToken(null);
    setUsername(null);
  }, []);

  return (
    <AuthContext.Provider value={{ username, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
