'use client';

import { AdminAuthProvider, useAdminAuth } from '@/lib/admin-auth-context';
import { AdminLoginScreen } from '@/components/AdminLoginScreen';
import { AdminDashboard } from '@/components/AdminDashboard';

function AdminGate() {
  const { loggedIn, loading } = useAdminAuth();

  if (loading) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-[#0B0F08] text-[#5C7A72]">
        Loading…
      </div>
    );
  }

  return loggedIn ? <AdminDashboard /> : <AdminLoginScreen />;
}

export default function AdminPage() {
  return (
    <AdminAuthProvider>
      <AdminGate />
    </AdminAuthProvider>
  );
}
