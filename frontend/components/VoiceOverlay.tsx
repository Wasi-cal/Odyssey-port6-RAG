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

export function VoiceOverlay({
  voiceStatus,
  captionText,
  sources,
  muted,
  onToggleMute,
  onClose,
  onOpenSource,
}: VoiceOverlayProps) {
  /*
   * Connecting has no dedicated visual state, so use the more active
   * thinking animation while the voice pipeline is being established.
   */
  const orbState: OrbState =
    voiceStatus === 'listening'
      ? 'listening'
      : voiceStatus === 'speaking'
        ? 'speaking'
        : 'thinking';

  return (
    <div
      className="
        animate-fadeIn
        fixed inset-0 z-50
        flex items-center justify-center
        overflow-y-auto
        px-5 py-8
      "
      style={{
        background: 'rgba(35, 25, 50, 0.32)',
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
      }}
      role="dialog"
      aria-modal="true"
      aria-label="Voice conversation"
    >
      <div
        className="
          animate-fadeInUp
          flex
          w-[520px]
          max-w-full
          flex-col
          items-center
          rounded-[32px]
          bg-transparent
          px-6
          py-8
          sm:px-10
          sm:py-10
        "
      >
        {/* Orb */}
        <div className="flex items-center justify-center">
          <VoiceOrb state={orbState} />
        </div>

        {/* Conversation information */}
        <div
          className="
            mt-3
            flex
            min-h-[86px]
            w-full
            max-w-[380px]
            flex-col
            items-center
            text-center
          "
        >
          <div
            className="
              text-[16px]
              font-semibold
              tracking-[-0.01em]
              text-[#211f2b]
            "
          >
            {STATUS_TEXT[voiceStatus]}
          </div>

          <div
            className="
              mt-2
              min-h-[40px]
              max-w-[360px]
              text-[14px]
              leading-[20px]
              text-[#7d7690]
            "
          >
            {captionText}
          </div>

          {sources.length > 0 && (
            <SourceChips
              sources={sources}
              onOpenSource={onOpenSource}
              className="
                mt-2
                max-w-[360px]
                justify-center
              "
            />
          )}
        </div>

        {/* Controls */}
        <div className="mt-8 flex items-center gap-5">
          {/* Mute */}
          <button
            type="button"
            onClick={onToggleMute}
            title={
              muted
                ? 'Unmute microphone'
                : 'Mute microphone'
            }
            aria-label={
              muted
                ? 'Unmute microphone'
                : 'Mute microphone'
            }
            aria-pressed={muted}
            className="
              group
              flex
              h-12
              w-12
              items-center
              justify-center
              rounded-full
              bg-white
              shadow-[0_2px_8px_rgba(30,20,45,0.10)]
              transition-all
              duration-200
              ease-out
              hover:scale-105
              hover:shadow-[0_4px_12px_rgba(30,20,45,0.14)]
              active:scale-95
            "
          >
            <svg
              viewBox="0 0 24 24"
              width="19"
              height="19"
              fill="none"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              stroke={
                muted
                  ? '#e0455a'
                  : '#6d4bb8'
              }
              aria-hidden="true"
            >
              <path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3z" />
              <path d="M19 11a7 7 0 0 1-14 0" />
              <path d="M12 18v3" />

              {muted && (
                <path d="M4 4l16 16" />
              )}
            </svg>
          </button>

          {/* End call */}
          <button
            type="button"
            onClick={onClose}
            title="End call"
            aria-label="End voice call"
            className="
              flex
              h-14
              w-14
              items-center
              justify-center
              rounded-full
              bg-[#e0455a]
              shadow-[0_5px_18px_rgba(224,69,90,0.34)]
              transition-all
              duration-200
              ease-out
              hover:scale-105
              hover:shadow-[0_7px_22px_rgba(224,69,90,0.42)]
              active:scale-95
            "
          >
            <svg
              viewBox="0 0 24 24"
              width="20"
              height="20"
              fill="none"
              stroke="#fff"
              strokeWidth="2.2"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M6 6l12 12" />
              <path d="M18 6L6 18" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
