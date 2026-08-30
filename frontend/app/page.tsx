'use client';

import { useAuth } from '@/lib/auth-context';
import { LoginScreen } from '@/components/LoginScreen';
import { Workspace } from '@/components/Workspace';

export default function Page() {
  const { username, loading } = useAuth();

  if (loading) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-[#0B0F08] text-[#7C8A70]">
        Loading…
      </div>
    );
  }

  if (!username) return <LoginScreen />;
  return <Workspace />;
}
