import type { Message, SourceInfo, VoiceStatus } from '@/lib/types';

/**
 * Shared shape both per-provider connection modules (openaiConnection.ts,
 * deepgramConnection.ts) are built against -- mirrors the backend's
 * RealtimeVoiceProvider split (assistant/voice/base.py): useRealtimeVoice.ts
 * owns all the React state and picks which module to hand it to based on
 * POST /voice/session's `provider` field; the module itself never touches
 * React state directly, only through these callbacks.
 */
export interface VoiceConnectionCallbacks {
  setStatus: (status: VoiceStatus) => void;
  setCaptionText: (text: string | ((prev: string) => string)) => void;
  setSources: (sources: SourceInfo[]) => void;
  setError: (error: string | null) => void;
  /** Same session the text UI uses (useDocAssist's ensureSession), so voice
   * and text turns share history. */
  getSessionId: () => Promise<string>;
  /** Pushes a completed search_policies exchange into the shared message
   * thread (viaVoice: true). */
  onExchangeComplete: (question: string, reply: Message) => void;
}

/** A live realtime connection to one provider -- the only thing the
 * orchestrator hook holds onto once connect() resolves. */
export interface VoiceConnection {
  disconnect: () => void;
  /** Mutes/unmutes the outgoing mic track (real hardware mute, not just a
   * UI flag) -- wired from the voice overlay's mute button. */
  setMuted?: (muted: boolean) => void;
  /** Real Web Audio AnalyserNodes tapped off the live mic input and the
   * agent's spoken output (never connected to a destination themselves --
   * purely for level/frequency analysis, e.g. VoiceOrb's audio-reactive
   * motion), so the orb reacts to actual audio rather than a simulated
   * envelope. Both null until the underlying audio graph is actually
   * live (e.g. before the first track arrives). */
  getAnalysers?: () => { input: AnalyserNode | null; output: AnalyserNode | null };
}
