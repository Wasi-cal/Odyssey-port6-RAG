'use client';

import { useState } from 'react';
import { useAdminAuth } from '@/lib/admin-auth-context';
import { ApiError } from '@/lib/api';
import { GradientBackdrop } from './GradientBackdrop';

export function AdminLoginScreen() {
  const { login } = useAdminAuth();
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(password);
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
          <span className="font-serif text-[22px] text-[#EDF2E6]">Doc Assist Admin</span>
        </div>
        <div className="mb-6 text-[13px] text-[#5C7A72]">Enter the shared admin password.</div>

        <label className="mb-4 block text-[13px] font-semibold text-[#B7CAC3]">
          Admin password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus
            required
            className="mt-1.5 w-full rounded-[10px] border border-[#1B332D] bg-[#101E1B] px-3 py-2.5 text-[14px] text-[#EDF2E6] outline-none focus:border-[#5EEAD4]"
          />
        </label>

        {error && <div className="mb-4 text-[13px] text-[#F0A98C]">{error}</div>}

        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-[10px] bg-[#5EEAD4] py-2.5 text-[14px] font-semibold text-[#06201B] transition-colors hover:bg-[#48D9C1] disabled:opacity-60"
        >
          {busy ? 'Please wait…' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}
