'use client';

import { useEffect, useRef } from 'react';
import { VoiceOrb, type OrbState } from './VoiceOrb';
import { SourceChips } from './SourceChips';
import type { SourceInfo, VoiceStatus } from '@/lib/types';

interface VoiceOverlayProps {
  voiceStatus: VoiceStatus;
  captionText: string;
  sources: SourceInfo[];
  muted: boolean;
  /** Real Web Audio AnalyserNode for the orb's audio-reactive motion --
   * whichever side actually has live audio right now (mic while
   * listening, agent output while speaking), or null when there's
   * nothing to react to (thinking/connecting), in which case VoiceOrb
   * falls back to its own simulated envelope. */
  analyser?: AnalyserNode | null;
  onToggleMute: () => void;
  onClose: () => void;
  onOpenSource: (doc?: string) => void;
}

const STATUS_TEXT: Record<VoiceStatus, string> = {
  idle: '',
  connecting: 'Connecting',
  listening: 'Listening',
  thinking: 'Thinking',
  speaking: 'Speaking',
};

const STATUS_HINT: Record<VoiceStatus, string> = {
  idle: '',
  connecting: 'Getting things ready…',
  listening: 'Go ahead, I’m listening',
  thinking: 'Let me think about that…',
  speaking: 'Here’s what I found',
};

export function VoiceOverlay({
  voiceStatus,
  captionText,
  sources,
  muted,
  analyser = null,
  onToggleMute,
  onClose,
  onOpenSource,
}: VoiceOverlayProps) {
  const overlayRef =
    useRef<HTMLDivElement | null>(null);

  /*
   * Map the real voice state to the orb state.
   */
  const orbState: OrbState =
    voiceStatus === 'listening'
      ? 'listening'
      : voiceStatus === 'speaking'
        ? 'speaking'
        : 'thinking';

  /*
   * Escape closes the voice session.
   */
  useEffect(() => {
    const handleKeyDown = (
      event: KeyboardEvent,
    ) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    window.addEventListener(
      'keydown',
      handleKeyDown,
    );

    return () => {
      window.removeEventListener(
        'keydown',
        handleKeyDown,
      );
    };
  }, [onClose]);

  return (
    <div
      ref={overlayRef}
      className="
        fixed
        inset-0
        z-50
        flex
        min-h-screen
        items-center
        justify-center
        overflow-hidden
      "
      role="dialog"
      aria-modal="true"
      aria-label="Voice conversation"
    >
      {/* ─────────────────────────────────────────
          BACKGROUND
      ───────────────────────────────────────── */}

      <div
        className="
          absolute
          inset-0
          bg-[#f8f6fb]
        "
      />

      {/* Large ambient glow behind the orb */}
      <div
        className="
          pointer-events-none
          absolute
          left-1/2
          top-1/2
          h-[520px]
          w-[520px]
          -translate-x-1/2
          -translate-y-1/2
          rounded-full
          bg-[#6d4bb8]/[0.035]
          blur-[80px]
        "
      />

      {/* Secondary atmospheric glow */}
      <div
        className="
          pointer-events-none
          absolute
          left-1/2
          top-[38%]
          h-[280px]
          w-[280px]
          -translate-x-1/2
          -translate-y-1/2
          rounded-full
          bg-[#8b6dcc]/[0.035]
          blur-[70px]
        "
      />

      {/* ─────────────────────────────────────────
          TOP BAR
      ───────────────────────────────────────── */}

      <div
        className="
          absolute
          left-0
          right-0
          top-0
          flex
          items-center
          justify-between
          px-6
          py-5
          sm:px-8
          sm:py-7
        "
      >
        <div
          className="
            flex
            items-center
            gap-2.5
          "
        >
          <div
            className="
              h-2
              w-2
              rounded-full
              bg-[#6d4bb8]
            "
          />

          <span
            className="
              text-[13px]
              font-medium
              tracking-[0.01em]
              text-[#625b70]
            "
          >
            Voice mode
          </span>
        </div>

        <button
          type="button"
          onClick={onClose}
          aria-label="Close voice mode"
          className="
            flex
            h-10
            w-10
            items-center
            justify-center
            rounded-full
            text-[#7d7690]
            transition
            duration-200
            hover:bg-black/[0.04]
            hover:text-[#211f2b]
            active:scale-95
          "
        >
          <svg
            viewBox="0 0 24 24"
            width="20"
            height="20"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
          >
            <path d="M6 6l12 12" />
            <path d="M18 6L6 18" />
          </svg>
        </button>
      </div>

      {/* ─────────────────────────────────────────
          MAIN CONTENT
      ───────────────────────────────────────── */}

      <main
        className="
          relative
          z-10
          flex
          w-full
          max-w-[680px]
          flex-col
          items-center
          px-6
          pb-8
          pt-20
          sm:px-8
          sm:pb-10
        "
      >
        {/* Orb */}
        <div
          className="
            flex
            h-[300px]
            w-[300px]
            items-center
            justify-center
            sm:h-[360px]
            sm:w-[360px]
          "
        >
          <VoiceOrb
            state={orbState}
            analyser={analyser}
          />
        </div>

        {/* ─────────────────────────────────────
            STATUS
        ───────────────────────────────────── */}

        <div
          className="
            mt-2
            flex
            flex-col
            items-center
            text-center
          "
        >
          <div
            className="
              flex
              items-center
              gap-2
              text-[18px]
              font-semibold
              tracking-[-0.02em]
              text-[#211f2b]
            "
          >
            <span>
              {STATUS_TEXT[voiceStatus]}
            </span>

            {voiceStatus ===
              'connecting' && (
              <span className="flex gap-1">
                <span className="animate-pulse">
                  .
                </span>
                <span
                  className="animate-pulse"
                  style={{
                    animationDelay:
                      '150ms',
                  }}
                >
                  .
                </span>
                <span
                  className="animate-pulse"
                  style={{
                    animationDelay:
                      '300ms',
                  }}
                >
                  .
                </span>
              </span>
            )}
          </div>

          {!captionText && (
            <div
              className="
                mt-2
                text-[14px]
                text-[#918a9d]
              "
            >
              {STATUS_HINT[voiceStatus]}
            </div>
          )}
        </div>

        {/* ─────────────────────────────────────
            LIVE CAPTION
        ───────────────────────────────────── */}

        <div
          className="
            mt-5
            flex
            min-h-[68px]
            w-full
            max-w-[500px]
            items-center
            justify-center
            px-4
            text-center
          "
        >
          {captionText && (
            <p
              className="
                animate-fadeIn
                text-[17px]
                font-medium
                leading-[26px]
                tracking-[-0.01em]
                text-[#514a60]
                sm:text-[18px]
                sm:leading-[28px]
              "
            >
              {captionText}
            </p>
          )}
        </div>

        {/* ─────────────────────────────────────
            SOURCES
        ───────────────────────────────────── */}

        {sources.length > 0 && (
          <div
            className="
              mt-1
              flex
              max-w-[500px]
              justify-center
            "
          >
            <SourceChips
              sources={sources}
              onOpenSource={onOpenSource}
              className="
                justify-center
              "
            />
          </div>
        )}

        {/* ─────────────────────────────────────
            CONTROLS
        ───────────────────────────────────── */}

        <div
          className="
            mt-10
            flex
            items-center
            gap-5
          "
        >
          {/* Microphone */}
          <button
            type="button"
            onClick={onToggleMute}
            aria-label={
              muted
                ? 'Unmute microphone'
                : 'Mute microphone'
            }
            aria-pressed={muted}
            className={`
              group
              relative
              flex
              h-[58px]
              w-[58px]
              items-center
              justify-center
              rounded-full
              border
              transition-all
              duration-200
              active:scale-95
              ${
                muted
                  ? `
                    border-[#e0455a]/20
                    bg-[#fff5f6]
                    text-[#e0455a]
                  `
                  : `
                    border-black/[0.06]
                    bg-white
                    text-[#6d4bb8]
                    shadow-[0_4px_18px_rgba(30,20,45,0.08)]
                    hover:-translate-y-0.5
                    hover:shadow-[0_7px_24px_rgba(30,20,45,0.12)]
                  `
              }
            `}
          >
            <svg
              viewBox="0 0 24 24"
              width="21"
              height="21"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.9"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <rect
                x="9"
                y="3"
                width="6"
                height="12"
                rx="3"
              />

              <path d="M5 11a7 7 0 0 0 14 0" />
              <path d="M12 18v3" />
              <path d="M9 21h6" />

              {muted && (
                <path d="M4 4l16 16" />
              )}
            </svg>

            {/* Muted indicator */}
            {muted && (
              <span
                className="
                  absolute
                  right-[8px]
                  top-[7px]
                  h-[6px]
                  w-[6px]
                  rounded-full
                  bg-[#e0455a]
                "
              />
            )}
          </button>

          {/* End call */}
          <button
            type="button"
            onClick={onClose}
            aria-label="End voice call"
            className="
              flex
              h-[66px]
              w-[66px]
              items-center
              justify-center
              rounded-full
              bg-[#e0455a]
              text-white
              shadow-[0_7px_24px_rgba(224,69,90,0.28)]
              transition-all
              duration-200
              hover:-translate-y-0.5
              hover:bg-[#d83d52]
              hover:shadow-[0_10px_30px_rgba(224,69,90,0.34)]
              active:scale-95
            "
          >
            <svg
              viewBox="0 0 24 24"
              width="22"
              height="22"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M6 6l12 12" />
              <path d="M18 6L6 18" />
            </svg>
          </button>
        </div>

        {/* Keyboard hint */}
        <div
          className="
            mt-7
            hidden
            items-center
            gap-1.5
            text-[11px]
            text-[#aaa4b3]
            sm:flex
          "
        >
          <kbd
            className="
              rounded
              border
              border-black/[0.07]
              bg-white/70
              px-1.5
              py-0.5
              font-medium
              text-[#918a9d]
            "
          >
            Esc
          </kbd>

          <span>
            to close
          </span>
        </div>
      </main>
    </div>
  );
}