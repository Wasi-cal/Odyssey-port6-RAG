'use client';

import { useState } from 'react';
import { useAuth } from '@/lib/auth-context';
import { ApiError } from '@/lib/api';
import { GradientBackdrop } from './GradientBackdrop';

export function LoginScreen() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === 'login') await login(username, password);
      else await register(username, password);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative flex h-screen w-full items-center justify-center overflow-hidden font-sans text-[#EDF2E6]">
      <GradientBackdrop />
      <form
        onSubmit={submit}
        className="relative z-[1] w-[380px] max-w-[90vw] rounded-[18px] border border-[#1B332D] bg-[#0F1B18] p-[30px] shadow-2xl"
      >
        <div className="mb-1 flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-[#8FEFDC] to-[#2FA98F] font-serif text-xl text-[#06201B]">
            D
          </div>
          <span className="font-serif text-[22px] text-[#EDF2E6]">Doc Assist</span>
        </div>
        <div className="mb-6 text-[13px] text-[#5C7A72]">
          {mode === 'login' ? 'Sign in to your workspace.' : 'Create an account to get started.'}
        </div>

        <label className="mb-3 block text-[13px] font-semibold text-[#B7CAC3]">
          Username
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
            required
            className="mt-1.5 w-full rounded-[10px] border border-[#1B332D] bg-[#101E1B] px-3 py-2.5 text-[14px] text-[#EDF2E6] outline-none focus:border-[#5EEAD4]"
          />
        </label>

        <label className="mb-4 block text-[13px] font-semibold text-[#B7CAC3]">
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            className="mt-1.5 w-full rounded-[10px] border border-[#1B332D] bg-[#101E1B] px-3 py-2.5 text-[14px] text-[#EDF2E6] outline-none focus:border-[#5EEAD4]"
          />
        </label>

        {error && <div className="mb-4 text-[13px] text-[#F0A98C]">{error}</div>}

        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-[10px] bg-[#5EEAD4] py-2.5 text-[14px] font-semibold text-[#06201B] transition-colors hover:bg-[#48D9C1] disabled:opacity-60"
        >
          {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
        </button>

        <button
          type="button"
          onClick={() => {
            setError(null);
            setMode((m) => (m === 'login' ? 'register' : 'login'));
          }}
          className="mt-4 w-full text-center text-[13px] text-[#5C7A72] hover:text-[#5EEAD4]"
        >
          {mode === 'login' ? "Don't have an account? Register" : 'Already have an account? Sign in'}
        </button>
      </form>
    </div>
  );
}
