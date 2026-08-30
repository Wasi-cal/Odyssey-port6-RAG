'use client';

import { LiquidSphere } from './LiquidSphere';
import { SourceChips } from './SourceChips';
import type { SourceInfo, VoiceStatus } from '@/lib/types';

interface VoiceScreenProps {
  voiceStatus: VoiceStatus;
  captionText: string;
  sources: SourceInfo[];
  onExit: () => void;
  onToggleListen: () => void;
  onOpenSettings: () => void;
  onOpenSource: (doc?: string) => void;
}

/**
 * Full-screen dedicated voice view -- a real navigation state, not an
 * overlay floating on top of the chat thread. Backed by a live OpenAI
 * Realtime WebRTC session (see hooks/useRealtimeVoice.ts); citations come
 * from the search_policies tool's /voice/ask result and are shown here
 * (never spoken -- see backend/api.py's _VOICE_SESSION_INSTRUCTIONS).
 */
export function VoiceScreen({
  voiceStatus,
  captionText,
  sources,
  onExit,
  onToggleListen,
  onOpenSettings,
  onOpenSource,
}: VoiceScreenProps) {
  const active = voiceStatus === 'listening' || voiceStatus === 'speaking';
  const placeholder =
    voiceStatus === 'connecting' ? 'Connecting…' : voiceStatus === 'listening' ? 'Listening…' : 'Doc Assist is speaking…';

  return (
    <div
      className="relative flex h-screen w-full flex-col items-center overflow-hidden text-[#EDF2E6]"
      style={{ background: 'linear-gradient(180deg, #090D0C 0%, #0A1614 55%, #0D211D 100%)' }}
    >
      <div className="relative z-[1] flex w-full items-center justify-between px-6 pt-6">
        <button
          onClick={onExit}
          title="Back to chat"
          className="flex h-10 w-10 items-center justify-center rounded-full border border-[#1B332D] bg-[#101E1B]/80 text-[#DCE8E3] backdrop-blur-sm transition-colors hover:bg-[#173832]"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="m15 18-6-6 6-6" />
          </svg>
        </button>
        <span className="text-[13px] font-semibold text-[#B7CAC3]">Doc Assist</span>
        <div className="h-10 w-10" />
      </div>

      <div className="relative z-[1] flex flex-1 flex-col items-center justify-center px-10">
        <LiquidSphere size="min(220px, 42vw)" active={active} />

        <div className="mt-9 max-w-[520px] text-center text-[20px] font-medium leading-normal text-[#F4FAF8]">
          {captionText || placeholder}
        </div>

        <SourceChips sources={sources} onOpenSource={onOpenSource} className="mt-5 max-w-[520px] justify-center" />
      </div>

      <div className="relative z-[1] mb-10 flex items-center gap-6">
        <button
          onClick={onOpenSettings}
          title="Settings"
          className="flex h-12 w-12 items-center justify-center rounded-full bg-[#101E1B] text-[#B7CAC3] transition-colors hover:bg-[#173832]"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </button>

        <button
          onClick={onToggleListen}
          title="End voice session"
          disabled={voiceStatus === 'connecting'}
          className="flex h-16 w-16 items-center justify-center rounded-full bg-[#5EEAD4] text-[#06201B] shadow-[0_0_30px_rgba(94,234,212,0.5)] transition-transform hover:scale-105 disabled:opacity-60"
        >
          {voiceStatus === 'connecting' ? (
            <svg className="animate-spin" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <path d="M12 2a10 10 0 0 1 10 10" />
            </svg>
          ) : (
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M8 21v-2a4 4 0 0 1 4-4h0a4 4 0 0 1 4 4v2" />
              <path d="M4 15v2a2 2 0 0 0 2 2M20 15v2a2 2 0 0 1-2 2" />
              <path d="M12 15V3M9 6l3-3 3 3" />
            </svg>
          )}
        </button>

        <button
          onClick={onExit}
          title="Switch to text chat"
          className="flex h-12 w-12 items-center justify-center rounded-full bg-[#101E1B] text-[#B7CAC3] transition-colors hover:bg-[#173832]"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
        </button>
      </div>
    </div>
  );
}
