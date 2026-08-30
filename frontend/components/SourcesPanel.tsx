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
    <div className="w-[300px] flex-shrink-0 overflow-y-auto border-l border-[#132521] bg-[#0A1412]/60 p-[18px] backdrop-blur-sm">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-sm font-bold text-[#EDF2E6]">Sources</span>
        <button onClick={onClose} className="p-1 text-[#5C7A72] transition-colors hover:text-[#EDF2E6]">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
      </div>
      <div className="mb-3.5 text-xs text-[#5C7A72]">Documents referenced in this workspace</div>

      {docs.length === 0 && <div className="mb-3 text-[12.5px] text-[#4E6A62]">No documents in the library yet.</div>}

      {docs.map((d) => {
        const active = d.name === activeDoc;
        return (
          <a
            key={d.name}
            href={`/api/documents/${encodeURIComponent(d.name)}`}
            target="_blank"
            rel="noreferrer"
            className={`mb-2 flex items-start gap-2.5 rounded-[10px] border p-2.5 transition-shadow hover:shadow-md ${
              active ? 'border-[#2FA98F] bg-[#173832]' : 'border-[#1B332D] bg-[#101E1B]'
            }`}
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#5EEAD4"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="mt-0.5 flex-shrink-0"
            >
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <path d="M14 2v6h6" />
            </svg>
            <div className="min-w-0">
              <div className="truncate text-[13px] font-semibold text-[#EDF2E6]">{d.name}</div>
              <div className="mt-0.5 text-[11.5px] text-[#5C7A72]">{d.meta}</div>
            </div>
          </a>
        );
      })}

      <button
        onClick={onUpload}
        className="mt-1.5 w-full rounded-[10px] border-[1.5px] border-dashed border-[#2A4A42] p-3 text-[12.5px] text-[#5C7A72] transition-colors hover:border-[#5EEAD4] hover:text-[#5EEAD4]"
      >
        {uploading ? 'Uploading…' : 'Drop a policy doc here to upload'}
      </button>
    </div>
  );
}
