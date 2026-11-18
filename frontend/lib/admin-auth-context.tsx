'use client';

import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import * as api from './api';

interface AdminAuthState {
  loggedIn: boolean;
  loading: boolean;
  login: (adminPassword: string) => Promise<void>;
  logout: () => void;
  handleUnauthorized: () => void;
}

const AdminAuthContext = createContext<AdminAuthState | null>(null);

export function AdminAuthProvider({ children }: { children: React.ReactNode }) {
  const [loggedIn, setLoggedIn] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoggedIn(!!api.getAdminToken());
    setLoading(false);
  }, []);

  const login = useCallback(async (adminPassword: string) => {
    const res = await api.adminLogin(adminPassword);
    api.setAdminToken(res.access_token);
    setLoggedIn(true);
  }, []);

  const logout = useCallback(() => {
    api.setAdminToken(null);
    setLoggedIn(false);
  }, []);

  return (
    <AdminAuthContext.Provider value={{ loggedIn, loading, login, logout, handleUnauthorized: logout }}>
      {children}
    </AdminAuthContext.Provider>
  );
}

export function useAdminAuth() {
  const ctx = useContext(AdminAuthContext);
  if (!ctx) throw new Error('useAdminAuth must be used within AdminAuthProvider');
  return ctx;
}
