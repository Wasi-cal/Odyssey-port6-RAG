'use client';

import { VoiceOrb, type OrbState } from './VoiceOrb';
import { SourceChips } from './SourceChips';
import type { SourceInfo, VoiceStatus } from '@/lib/types';

interface VoiceOverlayProps {
  voiceStatus: VoiceStatus;
  captionText: string;
  sources: SourceInfo[];
  muted: boolean;
  onToggleMute: () => void;
  onClose: () => void;
  onOpenSource: (doc?: string) => void;
}

const STATUS_TEXT: Record<VoiceStatus, string> = {
  idle: '',
  connecting: 'Connecting…',
  listening: 'Listening…',
  thinking: 'Thinking…',
  speaking: 'Speaking…',
};

/**
 * Full-viewport voice-call overlay -- a fixed, blurred layer on top of the
 * chat workspace (per the HR Chatbot design handoff), not a dedicated
 * screen that replaces the whole app. Backed by the real WebRTC/WebSocket
 * voice pipeline (see hooks/useRealtimeVoice.ts) -- listening/thinking/
 * speaking are real events, not a scripted demo.
 */
export function VoiceOverlay({ voiceStatus, captionText, sources, muted, onToggleMute, onClose, onOpenSource }: VoiceOverlayProps) {
  // "connecting" has no dedicated design state -- visually closest to
  // "thinking" (request in flight, no user/agent audio yet).
  const orbState: OrbState = voiceStatus === 'listening' ? 'listening' : voiceStatus === 'speaking' ? 'speaking' : 'thinking';

  return (
    <div
      // animate-fadeIn: the backdrop used to appear/disappear instantly the
      // moment the overlay mounted/unmounted -- a soft fade (+ the
      // backdrop-filter blur already there) reads as the call opening/
      // closing rather than snapping on screen (bug #5).
      className="animate-fadeIn fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'rgba(35,25,50,0.35)', backdropFilter: 'blur(6px)' }}
    >
      <div className="animate-fadeInUp flex w-[420px] max-w-[90vw] flex-col items-center gap-[22px] rounded-[28px] bg-transparent p-10 px-8">
        <VoiceOrb state={orbState} />

        <div className="text-center">
          <div className="text-[15px] font-semibold text-[#211f2b]">{STATUS_TEXT[voiceStatus]}</div>
          <div className="mt-2 min-h-[20px] max-w-[320px] text-[13.5px] text-[#7d7690]">{captionText}</div>
          <SourceChips sources={sources} onOpenSource={onOpenSource} className="mt-3 max-w-[320px] justify-center" />
        </div>

        <div className="mt-1.5 flex items-center gap-4">
          <button
            onClick={onToggleMute}
            title={muted ? 'Unmute microphone' : 'Mute microphone'}
            className="flex h-12 w-12 items-center justify-center rounded-full bg-white shadow-[0_1px_4px_rgba(30,20,45,0.08)] transition-transform duration-200 ease-out hover:scale-105"
          >
            <svg
              viewBox="0 0 24 24"
              width="19"
              height="19"
              fill="none"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              stroke={muted ? '#e0455a' : '#6d4bb8'}
            >
              <path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3z" />
              <path d="M19 11a7 7 0 0 1-14 0" />
              <path d="M12 18v3" />
              {muted && <path d="M4 4l16 16" />}
            </svg>
          </button>

          <button
            onClick={onClose}
            title="End call"
            className="flex h-14 w-14 items-center justify-center rounded-full bg-[#e0455a] shadow-[0_4px_14px_rgba(224,69,90,0.35)] transition-transform duration-200 ease-out hover:scale-105"
          >
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinecap="round">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
