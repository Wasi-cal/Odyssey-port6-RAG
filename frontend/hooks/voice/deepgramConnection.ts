import * as api from '@/lib/api';
import type { VoiceConnection, VoiceConnectionCallbacks } from './types';

/**
 * Browser-to-Deepgram WebSocket connection to the Voice Agent API. Wire
 * protocol confirmed against the actual @deepgram/sdk package source
 * (not guessed from docs prose, which didn't spell out the browser-auth
 * mechanism):
 *
 * - Browser WebSocket auth: native `WebSocket` can't set an Authorization
 *   header, so the credential travels as a subprotocol instead --
 *   `new WebSocket(url, ['bearer', credential])` -- exactly what
 *   @deepgram/sdk's browser transport does internally
 *   (getWebSocketOptions in its bundled dist/browser/index.global.js) when
 *   given an `Authorization: Bearer <token>` header to send.
 * - Server event `type` values (Welcome, SettingsApplied, UserStartedSpeaking,
 *   ConversationText, AgentStartedSpeaking, AgentAudioDone,
 *   FunctionCallRequest, Error, Warning) and the FunctionCallResponse shape
 *   are taken from @deepgram/sdk's shipped AgentV1*.d.ts type definitions.
 * - Audio frames are raw linear16 PCM binary WebSocket messages (per the
 *   Settings message assistant/voice/deepgram_provider.py sends, audio.
 *   input/output both linear16 @ 24000 Hz) -- not wrapped in any JSON
 *   envelope.
 */
export async function connectDeepgram(
  session: api.VoiceSessionResponse,
  callbacks: VoiceConnectionCallbacks,
): Promise<VoiceConnection> {
  const { setStatus, setCaptionText, setSources, setError, getSessionId, onExchangeComplete } = callbacks;
  const connection = session.connection as api.DeepgramVoiceConnection;

  const SAMPLE_RATE = 24000; // must match assistant/voice/deepgram_provider.py's Settings audio config

  let ws: WebSocket | null = null;
  let micStream: MediaStream | null = null;
  let audioCtx: AudioContext | null = null;
  let micSource: MediaStreamAudioSourceNode | null = null;
  let micProcessor: ScriptProcessorNode | null = null;
  let muteSink: GainNode | null = null;
  let nextPlayTime = 0;

  const cleanup = () => {
    ws?.close();
    ws = null;
    micProcessor?.disconnect();
    micProcessor = null;
    micSource?.disconnect();
    micSource = null;
    muteSink?.disconnect();
    muteSink = null;
    micStream?.getTracks().forEach((t) => t.stop());
    micStream = null;
    audioCtx?.close().catch(() => {});
    audioCtx = null;
    nextPlayTime = 0;
  };

  const playPcm16 = (data: ArrayBuffer) => {
    if (!audioCtx) return;
    const int16 = new Int16Array(data);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768;

    const buffer = audioCtx.createBuffer(1, float32.length, SAMPLE_RATE);
    buffer.copyToChannel(float32, 0);

    const source = audioCtx.createBufferSource();
    source.buffer = buffer;
    source.connect(audioCtx.destination);

    const startAt = Math.max(audioCtx.currentTime, nextPlayTime);
    source.start(startAt);
    nextPlayTime = startAt + buffer.duration;
  };

  const startMicStreaming = () => {
    if (!audioCtx || !micStream) return;
    micSource = audioCtx.createMediaStreamSource(micStream);
    // ScriptProcessorNode is deprecated in favor of AudioWorklet, but needs
    // no separately-served worklet module -- simplest reliable option for
    // this size of feature. connected to a zero-gain sink (never to
    // speakers) purely so onaudioprocess actually fires in every browser.
    micProcessor = audioCtx.createScriptProcessor(4096, 1, 1);
    muteSink = audioCtx.createGain();
    muteSink.gain.value = 0;

    micProcessor.onaudioprocess = (e) => {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      const float32 = e.inputBuffer.getChannelData(0);
      const int16 = new Int16Array(float32.length);
      for (let i = 0; i < float32.length; i++) {
        const s = Math.max(-1, Math.min(1, float32[i]));
        int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }
      ws.send(int16.buffer);
    };

    micSource.connect(micProcessor);
    micProcessor.connect(muteSink);
    muteSink.connect(audioCtx.destination);
  };

  const handleFunctionCallRequest = async (message: any) => {
    for (const fn of message.functions || []) {
      if (fn.name !== 'search_policies') continue;
      let question = '';
      try {
        question = JSON.parse(fn.arguments || '{}').question || '';
      } catch {
        question = '';
      }
      if (!question) continue;

      // "thinking" -- the request is in flight (real event, not a timer):
      // drives the orb's faster/larger rim wobble per the design spec.
      setStatus('thinking');
      console.log('[voice/deepgram] /voice/ask ->', question);
      try {
        const sid = await getSessionId();
        const res = await api.voiceAsk(question, sid);
        console.log('[voice/deepgram] /voice/ask <-', res.answer, res.sources);
        setSources(res.sources);

        ws?.send(
          JSON.stringify({
            type: 'FunctionCallResponse',
            id: fn.id,
            name: fn.name,
            content: JSON.stringify({ answer: res.answer }),
          }),
        );
        onExchangeComplete(question, { role: 'assistant', text: res.answer, sources: res.sources });
      } catch (err) {
        const detail = err instanceof Error ? err.message : 'Lookup failed.';
        ws?.send(
          JSON.stringify({
            type: 'FunctionCallResponse',
            id: fn.id,
            name: fn.name,
            content: JSON.stringify({ error: detail }),
          }),
        );
        setError(detail);
      }
    }
  };

  const handleJsonMessage = (message: any) => {
    switch (message.type) {
      case 'Welcome':
        console.log('[voice/deepgram] Welcome', message.request_id);
        break;

      case 'SettingsApplied':
        console.log('[voice/deepgram] SettingsApplied');
        setStatus('listening');
        startMicStreaming();
        break;

      case 'UserStartedSpeaking':
        setCaptionText('');
        setSources([]);
        setStatus('listening');
        break;

      case 'ConversationText':
        console.log('[voice/deepgram] transcript:', message.role, message.content);
        if (message.content) setCaptionText(message.content);
        break;

      case 'AgentThinking':
        setStatus('thinking');
        break;

      case 'AgentStartedSpeaking':
        setStatus('speaking');
        setCaptionText('');
        break;

      case 'AgentAudioDone':
        setStatus('listening');
        break;

      case 'FunctionCallRequest':
        console.log('[voice/deepgram] FunctionCallRequest', message.functions);
        handleFunctionCallRequest(message);
        break;

      case 'Error':
        // Deepgram's Error type (distinct from the non-fatal Warning below)
        // ends the session server-side -- e.g. FAILED_TO_THINK after
        // repeated think-endpoint failures. Without tearing the connection
        // down and resetting status here, the UI was stuck showing
        // "listening"/"speaking" forever and the mic button's toggle logic
        // (useDocAssist's onToggleListen) only calls connect() when status
        // is 'idle' -- so pressing it again just called disconnect() on an
        // already-dead session, i.e. exactly "doesn't respond at all".
        console.error('[voice/deepgram] server error:', message.code, message.description);
        setError(message.description || 'Voice session error.');
        cleanup();
        setStatus('idle');
        break;

      case 'Warning':
        console.warn('[voice/deepgram] warning:', message.code, message.description);
        break;

      default:
        break;
    }
  };

  try {
    console.log('[voice/deepgram] requesting microphone...');
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    console.log('[voice/deepgram] microphone granted, tracks:', micStream.getAudioTracks().length);
  } catch (err) {
    console.error('[voice/deepgram] getUserMedia failed:', err);
    throw new Error('Microphone access is required for voice.');
  }

  try {
    // Browsers clamp the actual sample rate to what the hardware supports
    // in some cases -- if this AudioContext doesn't land on exactly
    // SAMPLE_RATE, both playback and captured audio would be off-rate.
    // Works on current Chrome/Firefox/Safari in practice; flagged here as
    // the one thing to verify on a real device during testing.
    audioCtx = new AudioContext({ sampleRate: SAMPLE_RATE });

    await new Promise<void>((resolve, reject) => {
      ws = new WebSocket(connection.websocket_url, ['bearer', session.credential]);
      ws.binaryType = 'arraybuffer';

      ws.onopen = () => {
        console.log('[voice/deepgram] websocket open, sending Settings');
        ws?.send(JSON.stringify(connection.settings));
        resolve();
      };

      ws.onerror = (e) => {
        console.error('[voice/deepgram] websocket error', e);
        reject(new Error('Failed to connect to Deepgram voice agent.'));
      };

      ws.onmessage = (event) => {
        if (typeof event.data === 'string') {
          try {
            handleJsonMessage(JSON.parse(event.data));
          } catch {
            // ignore malformed frame
          }
        } else if (event.data instanceof ArrayBuffer) {
          playPcm16(event.data);
        }
      };

      ws.onclose = (e) => {
        console.log('[voice/deepgram] websocket closed', e.code, e.reason);
        // Safety net for any close this module didn't itself initiate
        // (network drop, server-side close without an Error message
        // first, etc.) -- same "status must return to idle or the mic
        // button gets stuck" reasoning as the Error case above. A close
        // from our own cleanup() sets ws to null first, so this is a
        // harmless no-op reset in that case.
        setStatus('idle');
      };
    });
  } catch (err) {
    cleanup();
    throw err;
  }

  const setMuted = (muted: boolean) => {
    micStream?.getAudioTracks().forEach((t) => {
      t.enabled = !muted;
    });
  };

  return { disconnect: cleanup, setMuted };
}
