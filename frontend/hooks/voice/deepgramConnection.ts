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

  // Silent lead time given to the FIRST audio chunk of each agent speaking
  // turn (see AgentStartedSpeaking below) -- absorbs ordinary network
  // jitter on the next chunk or two instead of it audibilizing as a gap.
  // 120ms is short enough to be imperceptible as added latency but long
  // enough to cover the jitter actually observed live.
  const STARTUP_BUFFER_SECONDS = 0.12;
  // Linear fade in/out applied to every PCM chunk's own gain envelope (see
  // playPcm16) -- each chunk plays through its own AudioBufferSourceNode,
  // and back-to-back nodes aren't guaranteed to be sample-continuous at
  // their boundary (the encoder/network can chunk mid-waveform), which
  // reproduces live as an audible click/pop -- reported as "sudden
  // bursts" -- at every chunk boundary, worst right at the start of a
  // turn where there's nothing to mask it yet. 4ms is short enough that it
  // doesn't audibly shave the actual speech content.
  const CHUNK_FADE_SECONDS = 0.004;

  let ws: WebSocket | null = null;
  let micStream: MediaStream | null = null;
  let audioCtx: AudioContext | null = null;
  let micSource: MediaStreamAudioSourceNode | null = null;
  let micProcessor: ScriptProcessorNode | null = null;
  let muteSink: GainNode | null = null;
  let nextPlayTime = 0;

  // Root cause of BOTH "captions flash to the last line" and part of the
  // "audio sounds garbled" reports (confirmed live via a mock Deepgram
  // server that reproduces the real cadence: ConversationText for segment
  // N+1 arrives while segment N's audio is still only a fraction of the
  // way through playing, since Deepgram generates text+speech well ahead
  // of real-time and each spoken segment gets its own
  // AgentStartedSpeaking/ConversationText/AgentAudioDone triplet -- see
  // AgentAudioDone's comment below): ConversationText used to call
  // setCaptionText(message.content) the instant the event arrived, i.e. at
  // TEXT-GENERATION time, not at the moment that segment's audio actually
  // reaches the speaker. Across a 3-segment answer this measured as each
  // segment's caption getting overwritten within ~150-250ms of appearing,
  // while its own audio was still 2+ seconds from finishing -- so by the
  // time playback caught up, only the last segment's text was ever left on
  // screen; the first two were never on screen long enough to read.
  //
  // Fix: caption reveals are scheduled against the same clock the audio
  // itself is scheduled on (audioCtx's clock via nextPlayTime), not shown
  // the instant the text arrives. `nextPlayTime` at the moment a segment's
  // ConversationText arrives is exactly when that segment's audio will
  // begin playing (chunks always arrive after the text in the wire
  // protocol, and are appended to the running nextPlayTime schedule), so a
  // setTimeout keyed off `nextPlayTime - audioCtx.currentTime` reveals each
  // segment's caption in sync with the listener actually hearing it,
  // instead of racing ahead of their ears.
  let captionTimers: ReturnType<typeof setTimeout>[] = [];

  const clearCaptionSchedule = () => {
    captionTimers.forEach((t) => clearTimeout(t));
    captionTimers = [];
  };

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
    clearCaptionSchedule();
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

    // Route through a per-chunk GainNode instead of straight to
    // destination, purely to ramp gain up/down over CHUNK_FADE_SECONDS at
    // each chunk's start/end -- see CHUNK_FADE_SECONDS' comment above for
    // why (audible clicks/"bursts" at chunk boundaries otherwise). Fades
    // are clamped to at most half the buffer's own duration so a very
    // short chunk still fades smoothly rather than the in/out ramps
    // overlapping and fighting each other.
    const gain = audioCtx.createGain();
    source.connect(gain);
    gain.connect(audioCtx.destination);

    const startAt = Math.max(audioCtx.currentTime, nextPlayTime);
    const fade = Math.min(CHUNK_FADE_SECONDS, buffer.duration / 2);
    gain.gain.setValueAtTime(0, startAt);
    gain.gain.linearRampToValueAtTime(1, startAt + fade);
    gain.gain.setValueAtTime(1, startAt + buffer.duration - fade);
    gain.gain.linearRampToValueAtTime(0, startAt + buffer.duration);

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
        // Barge-in / next turn starting -- cancel any still-pending
        // scheduled caption reveals from a turn that's being interrupted,
        // so a stale future segment's text can't pop in after the user has
        // already started talking over the agent.
        clearCaptionSchedule();
        setCaptionText('');
        setSources([]);
        setStatus('listening');
        break;

      case 'ConversationText':
        console.log('[voice/deepgram] transcript:', message.role, message.content);
        if (message.content) {
          if (message.role === 'assistant' && audioCtx) {
            // Sync this segment's caption reveal to when its audio will
            // actually be HEARD, not to when the text itself arrived --
            // see the caption-scheduling comment above nextPlayTime's
            // declaration for why. `nextPlayTime` right now (before this
            // segment's own PCM chunks get appended to the schedule by
            // playPcm16 below) is exactly that moment.
            const text = message.content;
            const playAt = nextPlayTime;
            const delayMs = Math.max(0, (playAt - audioCtx.currentTime) * 1000);
            captionTimers.push(setTimeout(() => setCaptionText(text), delayMs));
          } else {
            // The employee's own live transcript (role 'user') isn't tied
            // to any scheduled playback -- show it immediately, same as
            // before.
            setCaptionText(message.content);
          }
        }
        break;

      case 'AgentThinking':
        setStatus('thinking');
        break;

      case 'AgentStartedSpeaking':
        // Deliberately does NOT clear the caption here: ConversationText
        // for the agent's own turn (see above) carries the spoken text and
        // is confirmed live to arrive at essentially the same moment as
        // this event -- sometimes a beat before it, since Deepgram needs
        // the text before TTS synthesis can even start. Clearing the
        // caption here used to wipe out that just-set text almost
        // immediately, which read as the subtitle flashing and
        // disappearing before (or as) the agent actually started speaking.
        //
        // Also resets the playback scheduling clock (see playPcm16) to
        // "now plus a small pre-roll," not straight to "now" -- confirmed
        // live that scheduling the very first chunk of a turn right at
        // audioCtx.currentTime left no slack for ordinary network jitter
        // on the next couple of chunks, so a slightly-late chunk kept
        // getting rescheduled to "whatever time it happens to arrive"
        // instead of "right after the previous chunk," producing an
        // audible gap -- most noticeable right at the start of a turn,
        // before enough chunks had arrived to naturally build up slack of
        // their own. STARTUP_BUFFER_SECONDS of silent lead time absorbs
        // that jitter instead of audibilizing it.
        setStatus('speaking');
        // Bug fix: Deepgram fires AgentStartedSpeaking once per spoken
        // SEGMENT, not once per turn (confirmed live -- see AgentAudioDone
        // below), but this used to unconditionally overwrite nextPlayTime
        // with "now plus a small buffer" on every single one of those
        // events. For every segment after the first in a turn, the
        // previous segment's audio was almost always still scheduled
        // *well* into the future at that point (confirmed live: segment
        // 2's AgentStartedSpeaking fired ~150ms after segment 1's audio
        // started, while segment 1's nextPlayTime schedule ran ~3 more
        // seconds out) -- unconditionally overwriting it rewound the
        // schedule backwards, so segment 2 (and 3, ...) got scheduled to
        // start almost immediately, ON TOP of the still-playing earlier
        // segment(s). That's audio from multiple segments literally
        // overlapping at the speaker -- a very plausible contributor to
        // the separately-reported "garbled/no clarity" voice quality
        // complaint, not just a Deepgram voice-model issue. Math.max here
        // preserves the original startup-jitter-buffer behavior for a
        // genuine first chunk (nextPlayTime is 0, or already in the past
        // because of a real gap) while never rewinding a schedule that's
        // still legitimately ahead of real time.
        if (audioCtx) nextPlayTime = Math.max(nextPlayTime, audioCtx.currentTime + STARTUP_BUFFER_SECONDS);
        break;

      case 'AgentAudioDone':
        // Deliberately does NOT clear the caption -- Deepgram fires this
        // once per spoken audio SEGMENT, not once for the agent's entire
        // turn (confirmed live: a multi-sentence answer produced repeated
        // AgentStartedSpeaking/AgentAudioDone pairs within what reads as
        // one logical turn). Clearing here wiped the caption after just
        // the first segment while the agent kept talking, which is the
        // exact "captions flash and don't stay" bug reported live -- the
        // AgentStartedSpeaking-based clear was fixed first, but this one
        // reproduced the same symptom through a different event. The
        // caption is now cleared only by UserStartedSpeaking above (the
        // start of the employee's NEXT turn), so it simply stays on
        // screen showing the agent's last words until then -- correct
        // regardless of how many audio segments a single answer is split
        // into.
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
