'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import * as api from '@/lib/api';
import { useAdminAuth } from '@/lib/admin-auth-context';
import { GradientBackdrop } from './GradientBackdrop';

function useAdminGuarded<T>(fetcher: () => Promise<T>, deps: unknown[] = []) {
  const { handleUnauthorized } = useAdminAuth();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    fetcher()
      .then((res) => setData(res))
      .catch((err) => {
        if (err instanceof api.ApiError && err.status === 401) {
          handleUnauthorized();
          return;
        }
        setError(err instanceof Error ? err.message : 'Failed to load.');
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reload]);

  return { data, error, loading, reload };
}

function Card({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex-1 rounded-[14px] border border-[#1B332D] bg-[#0F1B18] p-4">
      <div className="text-[12px] text-[#5C7A72]">{label}</div>
      <div className="mt-1 font-serif text-[26px] text-[#EDF2E6]">{value}</div>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <div className="mb-3 mt-8 text-[13px] font-bold uppercase tracking-[0.06em] text-[#5C7A72]">{children}</div>;
}

function Banner({ text, kind }: { text: string; kind: 'error' | 'ok' }) {
  return (
    <div
      className={`mb-3 rounded-[10px] px-3 py-2 text-[13px] ${
        kind === 'error' ? 'bg-[#231310] text-[#F0A98C]' : 'bg-[#0F2419] text-[#8FE3AE]'
      }`}
    >
      {text}
    </div>
  );
}

export function AdminDashboard() {
  const { logout } = useAdminAuth();
  const [notice, setNotice] = useState<{ text: string; kind: 'error' | 'ok' } | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [uploading, setUploading] = useState(false);

  const monitoring = useAdminGuarded(api.getMonitoring);
  const pending = useAdminGuarded(api.listPendingDocumentsAdmin);
  const documents = useAdminGuarded(api.listDocumentsAdmin);
  const auditLog = useAdminGuarded(api.getAuditLog);

  const [resetUsername, setResetUsername] = useState('');
  const [resetPassword, setResetPassword] = useState('');
  const [newAdminPassword, setNewAdminPassword] = useState('');

  const reloadAll = useCallback(() => {
    monitoring.reload();
    pending.reload();
    documents.reload();
    auditLog.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runAction = async (label: string, action: () => Promise<unknown>) => {
    setNotice(null);
    try {
      await action();
      setNotice({ text: `${label} succeeded.`, kind: 'ok' });
      reloadAll();
    } catch (err) {
      if (err instanceof api.ApiError && err.status === 401) {
        logout();
        return;
      }
      setNotice({ text: err instanceof Error ? err.message : `${label} failed.`, kind: 'error' });
    }
  };

  const onUploadFiles = async (files: FileList) => {
    if (!files.length) return;
    setUploading(true);
    await runAction('Upload', () => api.uploadDocumentsAdmin(Array.from(files)));
    setUploading(false);
  };

  return (
    <div className="relative min-h-screen overflow-hidden px-8 py-8 font-sans text-[#EDF2E6]">
      <GradientBackdrop />
      <input
        ref={fileInputRef}
        type="file"
        accept="application/pdf"
        multiple
        className="hidden"
        onChange={(e) => {
          if (e.target.files) onUploadFiles(e.target.files);
          e.target.value = '';
        }}
      />

      <div className="relative z-[1] mx-auto max-w-[1000px]">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <div className="font-serif text-[26px] text-[#EDF2E6]">Doc Assist — Admin</div>
            <div className="mt-0.5 text-[13px] text-[#5C7A72]">Library, approvals, and monitoring</div>
          </div>
          <button
            onClick={logout}
            className="rounded-[10px] border border-[#1B332D] bg-[#101E1B] px-4 py-2 text-[13px] font-semibold text-[#B7CAC3] hover:bg-[#173832]"
          >
            Sign out
          </button>
        </div>

        {notice && <Banner text={notice.text} kind={notice.kind} />}

        <SectionTitle>Monitoring</SectionTitle>
        {monitoring.error && <Banner text={monitoring.error} kind="error" />}
        <div className="flex flex-wrap gap-3">
          <Card label="Pending approvals" value={monitoring.data?.pending_approvals ?? '—'} />
          <Card label="Embeddings present" value={monitoring.data?.embeddings_present ?? '—'} />
          <Card label="Tokens consumed" value={monitoring.data?.tokens_consumed ?? '—'} />
          <Card label="Cost (USD)" value={monitoring.data ? `$${monitoring.data.cost_usd.toFixed(4)}` : '—'} />
          <Card label="Avg tokens/request" value={monitoring.data ? monitoring.data.average_token_usage.toFixed(1) : '—'} />
        </div>

        <SectionTitle>Pending approvals ({pending.data?.length ?? 0})</SectionTitle>
        {pending.error && <Banner text={pending.error} kind="error" />}
        {pending.data?.length === 0 && <div className="text-[13px] text-[#4E6A62]">Nothing waiting for review.</div>}
        <div className="flex flex-col gap-2">
          {pending.data?.map((d) => (
            <div key={d.id} className="flex items-center justify-between rounded-[10px] border border-[#1B332D] bg-[#0F1B18] px-4 py-3">
              <div className="min-w-0">
                <div className="truncate text-[13.5px] font-semibold text-[#EDF2E6]">{d.filename}</div>
                <div className="mt-0.5 text-[12px] text-[#5C7A72]">
                  Uploaded by {d.uploaded_by} · {new Date(d.uploaded_at).toLocaleString()}
                </div>
              </div>
              <div className="flex flex-shrink-0 gap-2">
                <button
                  onClick={() => runAction('Approve', () => api.approvePendingDocument(d.id))}
                  className="rounded-[8px] bg-[#5EEAD4] px-3 py-1.5 text-[12.5px] font-semibold text-[#06201B] hover:bg-[#48D9C1]"
                >
                  Approve
                </button>
                <button
                  onClick={() => runAction('Reject', () => api.rejectPendingDocument(d.id))}
                  className="rounded-[8px] border border-[#1B332D] bg-[#101E1B] px-3 py-1.5 text-[12.5px] font-semibold text-[#B7CAC3] hover:bg-[#173832]"
                >
                  Reject
                </button>
              </div>
            </div>
          ))}
        </div>

        <SectionTitle>Document library ({documents.data?.length ?? 0})</SectionTitle>
        {documents.error && <Banner text={documents.error} kind="error" />}
        <button
          onClick={() => fileInputRef.current?.click()}
          className="mb-3 rounded-[10px] border-[1.5px] border-dashed border-[#2A4A42] px-4 py-3 text-[13px] text-[#5C7A72] transition-colors hover:border-[#5EEAD4] hover:text-[#5EEAD4]"
        >
          {uploading ? 'Uploading…' : 'Upload PDFs directly (ingests immediately, no approval step)'}
        </button>
        <div className="flex flex-col gap-2">
          {documents.data?.map((d) => (
            <div key={d.name} className="flex items-center justify-between rounded-[10px] border border-[#1B332D] bg-[#0F1B18] px-4 py-3">
              <div className="min-w-0">
                <div className="truncate text-[13.5px] font-semibold text-[#EDF2E6]">{d.name}</div>
                <div className="mt-0.5 text-[12px] text-[#5C7A72]">
                  {d.chunk_count} chunks · ingested {new Date(d.ingested_at).toLocaleDateString()}
                </div>
              </div>
              <button
                onClick={() => {
                  if (!window.confirm(`Delete "${d.name}" from the library? This can't be undone.`)) return;
                  runAction('Delete', () => api.deleteDocumentAdmin(d.name));
                }}
                className="flex-shrink-0 rounded-[8px] border border-[#4A2318] bg-[#231310] px-3 py-1.5 text-[12.5px] font-semibold text-[#F0A98C] transition-colors hover:bg-[#2E1A14]"
              >
                Delete
              </button>
            </div>
          ))}
        </div>

        <SectionTitle>Audit log</SectionTitle>
        {auditLog.error && <Banner text={auditLog.error} kind="error" />}
        <div className="overflow-x-auto rounded-[10px] border border-[#1B332D] bg-[#0F1B18]">
          <table className="w-full text-left text-[12.5px]">
            <thead>
              <tr className="border-b border-[#1B332D] bg-[#101E1B] text-[#5C7A72]">
                <th className="px-3 py-2 font-semibold">Action</th>
                <th className="px-3 py-2 font-semibold">Filename</th>
                <th className="px-3 py-2 font-semibold">By</th>
                <th className="px-3 py-2 font-semibold">When</th>
              </tr>
            </thead>
            <tbody>
              {auditLog.data?.map((row, i) => (
                <tr key={i} className="border-b border-[#132521] text-[#B7CAC3]">
                  <td className="px-3 py-2 capitalize">{row.action}</td>
                  <td className="px-3 py-2">{row.filename}</td>
                  <td className="px-3 py-2">{row.performed_by}</td>
                  <td className="px-3 py-2">{new Date(row.performed_at).toLocaleString()}</td>
                </tr>
              ))}
              {auditLog.data?.length === 0 && (
                <tr>
                  <td className="px-3 py-3 text-[#4E6A62]" colSpan={4}>
                    No admin actions logged yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <SectionTitle>Account tools</SectionTitle>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              runAction('Password reset', () => api.adminResetPassword(resetUsername, resetPassword));
              setResetUsername('');
              setResetPassword('');
            }}
            className="rounded-[12px] border border-[#1B332D] bg-[#0F1B18] p-4"
          >
            <div className="mb-2 text-[13px] font-bold text-[#EDF2E6]">Reset a user's password</div>
            <input
              value={resetUsername}
              onChange={(e) => setResetUsername(e.target.value)}
              placeholder="username"
              required
              className="mb-2 w-full rounded-[8px] border border-[#1B332D] bg-[#101E1B] px-3 py-2 text-[13px] text-[#EDF2E6] outline-none focus:border-[#5EEAD4]"
            />
            <input
              type="password"
              value={resetPassword}
              onChange={(e) => setResetPassword(e.target.value)}
              placeholder="new password (min 8 chars)"
              required
              minLength={8}
              className="mb-3 w-full rounded-[8px] border border-[#1B332D] bg-[#101E1B] px-3 py-2 text-[13px] text-[#EDF2E6] outline-none focus:border-[#5EEAD4]"
            />
            <button type="submit" className="w-full rounded-[8px] bg-[#5EEAD4] py-2 text-[13px] font-semibold text-[#06201B] hover:bg-[#48D9C1]">
              Reset password
            </button>
          </form>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              runAction('Admin password change', () => api.adminChangePassword(newAdminPassword));
              setNewAdminPassword('');
            }}
            className="rounded-[12px] border border-[#1B332D] bg-[#0F1B18] p-4"
          >
            <div className="mb-2 text-[13px] font-bold text-[#EDF2E6]">Change the shared admin password</div>
            <input
              type="password"
              value={newAdminPassword}
              onChange={(e) => setNewAdminPassword(e.target.value)}
              placeholder="new admin password (min 8 chars)"
              required
              minLength={8}
              className="mb-3 w-full rounded-[8px] border border-[#1B332D] bg-[#101E1B] px-3 py-2 text-[13px] text-[#EDF2E6] outline-none focus:border-[#5EEAD4]"
            />
            <button type="submit" className="w-full rounded-[8px] border border-[#1B332D] bg-[#101E1B] py-2 text-[13px] font-semibold text-[#B7CAC3] hover:bg-[#173832]">
              Change admin password
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
