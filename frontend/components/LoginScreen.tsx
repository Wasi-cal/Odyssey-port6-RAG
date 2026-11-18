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
    <div className="relative flex h-screen w-full items-center justify-center overflow-hidden font-sans text-[#211f2b]">
      <GradientBackdrop />
      <form
        onSubmit={submit}
        className="relative z-[1] w-[380px] max-w-[90vw] rounded-[18px] border border-[rgba(30,20,45,0.08)] bg-white p-[30px] shadow-2xl"
      >
        <div className="mb-1 flex items-center gap-2">
          <div
            className="flex h-9 w-9 items-center justify-center rounded-full text-[15px] font-bold text-white"
            style={{ background: 'linear-gradient(135deg,#9b7fe0,#e79bd0)' }}
          >
            D
          </div>
          <span className="text-[20px] font-bold tracking-[-0.01em] text-[#211f2b]">Doc Assist</span>
        </div>
        <div className="mb-6 text-[13px] text-[#7d7690]">
          {mode === 'login' ? 'Sign in to your workspace.' : 'Create an account to get started.'}
        </div>

        <label className="mb-3 block text-[13px] font-semibold text-[#433d55]">
          Username
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
            required
            className="mt-1.5 w-full rounded-[10px] border border-[rgba(30,20,45,0.10)] bg-[#fdfcff] px-3 py-2.5 text-[14px] text-[#211f2b] outline-none focus:border-[#6d4bb8]"
          />
        </label>

        <label className="mb-4 block text-[13px] font-semibold text-[#433d55]">
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            className="mt-1.5 w-full rounded-[10px] border border-[rgba(30,20,45,0.10)] bg-[#fdfcff] px-3 py-2.5 text-[14px] text-[#211f2b] outline-none focus:border-[#6d4bb8]"
          />
        </label>

        {error && <div className="mb-4 text-[13px] text-[#c23a4d]">{error}</div>}

        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-[10px] py-2.5 text-[14px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-60"
          style={{ background: 'linear-gradient(135deg,#9b7fe0,#e79bd0)' }}
        >
          {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
        </button>

        <button
          type="button"
          onClick={() => {
            setError(null);
            setMode((m) => (m === 'login' ? 'register' : 'login'));
          }}
          className="mt-4 w-full text-center text-[13px] text-[#7d7690] hover:text-[#6d4bb8]"
        >
          {mode === 'login' ? "Don't have an account? Register" : 'Already have an account? Sign in'}
        </button>
      </form>
    </div>
  );
}
