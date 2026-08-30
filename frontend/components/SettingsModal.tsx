'use client';

import type { ResponseStyle } from '@/lib/types';

interface SettingsModalProps {
  open: boolean;
  responseStyle: ResponseStyle;
  citeSources: boolean;
  onClose: () => void;
  onStyleChange: (style: ResponseStyle) => void;
  onToggleCite: () => void;
}

const STYLES: ResponseStyle[] = ['concise', 'balanced', 'detailed'];

export function SettingsModal({ open, responseStyle, citeSources, onClose, onStyleChange, onToggleCite }: SettingsModalProps) {
  if (!open) return null;

  return (
    <div className="animate-fadeIn fixed inset-0 z-50 flex items-center justify-center bg-[rgba(35,25,50,0.35)] backdrop-blur-sm">
      <div className="animate-fadeInUp w-[420px] max-w-[90vw] rounded-[18px] border border-[rgba(30,20,45,0.08)] bg-white p-[26px] shadow-2xl">
        <div className="mb-[18px] flex items-center justify-between">
          <span className="text-[20px] font-bold text-[#211f2b]">Settings</span>
          <button onClick={onClose} className="rounded-full p-0.5 text-[#9a93a8] transition-colors duration-200 ease-out hover:text-[#211f2b]">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="mb-5">
          <div className="mb-2 text-[13px] font-bold text-[#211f2b]">Response style</div>
          <div className="flex gap-2">
            {STYLES.map((k) => {
              const active = k === responseStyle;
              return (
                <button
                  key={k}
                  onClick={() => onStyleChange(k)}
                  className={`flex-1 rounded-[9px] border py-2.5 text-[13px] font-semibold transition-colors duration-200 ease-out ${
                    active ? 'border-[#6d4bb8] bg-[#6d4bb8] text-white' : 'border-[rgba(30,20,45,0.10)] bg-white text-[#5b5566]'
                  }`}
                >
                  {k[0].toUpperCase() + k.slice(1)}
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex items-center justify-between border-t border-[rgba(30,20,45,0.06)] py-3">
          <div>
            <div className="text-[13.5px] font-semibold text-[#211f2b]">Always cite sources</div>
            <div className="mt-0.5 text-xs text-[#9a93a8]">Show document references under answers</div>
          </div>
          <button
            onClick={onToggleCite}
            className={`relative h-6 w-[42px] flex-shrink-0 rounded-full transition-colors duration-200 ease-out ${
              citeSources ? 'bg-[#6d4bb8]' : 'bg-[rgba(30,20,45,0.15)]'
            }`}
          >
            <div
              className="absolute top-0.5 h-5 w-5 rounded-full bg-white shadow-[0_1px_3px_rgba(0,0,0,0.3)] transition-all duration-200 ease-out"
              style={{ left: citeSources ? '20px' : '2px' }}
            />
          </button>
        </div>

        <div className="flex items-center justify-between border-t border-[rgba(30,20,45,0.06)] py-3">
          <div>
            <div className="text-[13.5px] font-semibold text-[#211f2b]">Assistant voice</div>
            <div className="mt-0.5 text-xs text-[#9a93a8]">Used in voice mode</div>
          </div>
          <span className="text-[13px] font-semibold text-[#6d4bb8]">Default</span>
        </div>
      </div>
    </div>
  );
}
