'use client';

import { useCallback, useRef, useState } from 'react';
import * as api from '@/lib/api';
import { connectDeepgram } from './voice/deepgramConnection';
import { connectOpenAI } from './voice/openaiConnection';
import type { VoiceConnection } from './voice/types';
import type { Message, SourceInfo, VoiceStatus } from '@/lib/types';

interface UseRealtimeVoiceOptions {
  /** Returns the chat session id to use for the search_policies tool's
   * /voice/ask call -- same session the text UI uses, via useDocAssist's
   * ensureSession(), so voice and text turns share history. */
  getSessionId: () => Promise<string>;
  /** Called once a search_policies round trip resolves -- pushes the
   * exchange into the shared message thread (viaVoice: true), same as the
   * old commitVoiceExchange did. */
  onExchangeComplete: (question: string, reply: Message) => void;
}

/**
 * Realtime voice connection, provider-agnostic -- mirrors the backend's
 * RealtimeVoiceProvider split (assistant/voice/). POST /voice/session
 * tells us which vendor is configured (config_store's voice/provider) via
 * its `provider` field; this hook owns all the shared UI state (status,
 * captions, sources, error) and just hands the minted session off to
 * whichever connection module (hooks/voice/openaiConnection.ts or
 * deepgramConnection.ts) matches. Both modules intercept the model's
 * search_policies tool call the same way: hit our own POST /voice/ask,
 * feed the grounded answer back into the session, and report the
 * exchange up via onExchangeComplete so it lands in the shared thread.
 */
export function useRealtimeVoice({ getSessionId, onExchangeComplete }: UseRealtimeVoiceOptions) {
  const [status, setStatus] = useState<VoiceStatus>('idle');
  const [captionText, setCaptionText] = useState('');
  const [sources, setSources] = useState<SourceInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [muted, setMuted] = useState(false);

  const connectionRef = useRef<VoiceConnection | null>(null);

  const reset = useCallback(() => {
    connectionRef.current?.disconnect();
    connectionRef.current = null;
    setStatus('idle');
    setCaptionText('');
    setSources([]);
    setMuted(false);
  }, []);

  const disconnect = useCallback(() => {
    reset();
  }, [reset]);

  const connect = useCallback(async () => {
    console.log('[voice] connect() called');
    setError(null);
    setStatus('connecting');

    try {
      console.log('[voice] minting session via /voice/session...');
      const session = await api.createVoiceSession();
      console.log('[voice] session minted, provider:', session.provider, 'expires_at:', session.expires_at);

      const callbacks = { setStatus, setCaptionText, setSources, setError, getSessionId, onExchangeComplete };
      const connection =
        session.provider === 'deepgram'
          ? await connectDeepgram(session, callbacks)
          : await connectOpenAI(session, callbacks);

      connectionRef.current = connection;
    } catch (err) {
      console.error('[voice] connect() failed:', err);
      setError(err instanceof Error ? err.message : 'Failed to start voice session.');
      reset();
    }
  }, [getSessionId, onExchangeComplete, reset]);

  const toggleMute = useCallback(() => {
    setMuted((prev) => {
      const next = !prev;
      connectionRef.current?.setMuted?.(next);
      return next;
    });
  }, []);

  return { status, captionText, sources, error, muted, connect, disconnect, toggleMute };
}
