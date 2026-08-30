'use client';

import type { Doc } from '@/lib/types';

interface SourcesPanelProps {
  docs: Doc[];
  activeDoc: string | null;
  uploading: boolean;
  onClose: () => void;
  onUpload: () => void;
}

export function SourcesPanel({ docs, activeDoc, uploading, onClose, onUpload }: SourcesPanelProps) {
  return (
    <div
      className="w-[300px] flex-shrink-0 overflow-y-auto border-l border-[rgba(30,20,45,0.07)] p-[18px]"
      style={{ background: 'rgba(255,255,255,0.65)', backdropFilter: 'blur(16px)' }}
    >
      <div className="mb-1 flex items-center justify-between">
        <span className="text-sm font-bold text-[#211f2b]">Documents</span>
        <button onClick={onClose} className="p-1 text-[#9a93a8] transition-colors hover:text-[#211f2b]">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
      </div>
      <div className="mb-3.5 text-xs text-[#7d7690]">Documents referenced in this workspace</div>

      {docs.length === 0 && <div className="mb-3 text-[12.5px] text-[#9a93a8]">No documents in the library yet.</div>}

      {docs.map((d) => {
        const active = d.name === activeDoc;
        return (
          <a
            key={d.name}
            href={`/api/documents/${encodeURIComponent(d.name)}`}
            target="_blank"
            rel="noreferrer"
            className="mb-2 flex items-start gap-2.5 rounded-[14px] border p-2.5 shadow-[0_1px_3px_rgba(30,20,45,0.04)] transition-colors"
            style={{
              borderColor: active ? 'rgba(138,99,214,0.35)' : 'rgba(30,20,45,0.08)',
              background: active ? 'rgba(138,99,214,0.08)' : '#ffffff',
            }}
          >
            <div className="mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-[rgba(138,99,214,0.10)]">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#6d4bb8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <path d="M14 2v6h6" />
              </svg>
            </div>
            <div className="min-w-0">
              <div className="truncate text-[13.5px] font-semibold text-[#211f2b]">{d.name}</div>
              <div className="mt-0.5 text-[12px] text-[#9a93a8]">{d.meta}</div>
            </div>
          </a>
        );
      })}

      <button
        onClick={onUpload}
        className="mt-1.5 w-full rounded-[14px] border-[1.5px] border-dashed border-[rgba(138,99,214,0.35)] p-3 text-[12.5px] text-[#7d7690] transition-colors hover:border-[#6d4bb8] hover:text-[#6d4bb8]"
      >
        {uploading ? 'Uploading…' : 'Drop a policy doc here to upload'}
      </button>
    </div>
  );
}
