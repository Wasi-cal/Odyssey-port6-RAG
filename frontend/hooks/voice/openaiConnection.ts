import * as api from '@/lib/api';
import type { VoiceConnection, VoiceConnectionCallbacks } from './types';

const OPENAI_REALTIME_CALLS_URL = 'https://api.openai.com/v1/realtime/calls';

/**
 * Browser-to-OpenAI WebRTC connection to the Realtime API -- the original
 * Phase 1 implementation, unchanged in behavior, just extracted out of
 * useRealtimeVoice.ts so it can sit alongside deepgramConnection.ts behind
 * the same VoiceConnection shape. The connection goes DIRECTLY from this
 * browser to OpenAI (never proxied through our backend): only the
 * ephemeral credential minted by POST /voice/session crosses our own
 * server.
 *
 * The realtime model calls its one tool, search_policies, whenever it
 * needs a grounded answer; this intercepts that function-call event, hits
 * our own POST /voice/ask with the question, and feeds the real grounded
 * answer back into the realtime session as the tool's output so the model
 * speaks it. The committed message thread uses OUR answer text verbatim
 * (not the model's own spoken transcript, which could paraphrase) so
 * citations always match exactly what's shown.
 */
export async function connectOpenAI(
  session: api.VoiceSessionResponse,
  callbacks: VoiceConnectionCallbacks,
): Promise<VoiceConnection> {
  const { setStatus, setCaptionText, setSources, setError, getSessionId, onExchangeComplete } = callbacks;
  const connection = session.connection as api.OpenAIVoiceConnection;

  let pc: RTCPeerConnection | null = null;
  let dc: RTCDataChannel | null = null;
  let micStream: MediaStream | null = null;
  let audioEl: HTMLAudioElement | null = null;

  // Separate AudioContext purely for analysis (never connected to
  // `.destination` itself) -- WebRTC handles actual playback/capture on
  // its own graph via `audioEl`/the RTCPeerConnection, this just taps the
  // same MediaStreamTracks for level/frequency data so VoiceOrb can be
  // genuinely audio-reactive instead of running its simulated envelope.
  let analysisCtx: AudioContext | null = null;
  let inputAnalyser: AnalyserNode | null = null;
  let outputAnalyser: AnalyserNode | null = null;

  // Tracks whether the assistant's own audio for this turn has already
  // started streaming -- guards against a distinct caption race confirmed
  // live (Playwright + real OpenAI Realtime API, fake mic audio): the
  // employee's OWN speech transcript
  // (conversation.item.input_audio_transcription.completed) comes back
  // from a separate, slower async transcription pipeline, and can arrive
  // AFTER the assistant's reply has already started streaming its own
  // response.output_audio_transcript.delta events. Since that handler does
  // a full setCaptionText(message.transcript) REPLACE while the delta
  // handler does setCaptionText((prev) => prev + delta), a late user
  // transcript landing in between two deltas got prepended into the
  // caption and then had more of the assistant's OWN reply appended onto
  // it -- observed live as caption text like "Please give me a detailed
  // multi-sentence answer. provide a thorough" (the user's transcript
  // spliced together with the assistant's in-progress reply) for several
  // hundred ms, until the reply's own .done event happened to fully
  // replace and self-heal it. Once the assistant's audio has started for
  // this turn, the caption belongs to ITS transcript, not a delayed
  // display of what the employee said -- so a late transcription-completed
  // event is simply dropped instead of stomping on it.
  let assistantAudioActive = false;

  // Set the moment the USER intentionally hangs up (the returned
  // `disconnect`, as opposed to `cleanup()` also being called internally
  // on a genuine connection failure) -- guards a race confirmed live:
  // hanging up while the assistant's audio is still mid-playback (e.g.
  // right after the speed-adjusted response.audio.done/output_audio_buffer
  // bookkeeping) can leave a non-fatal, already-irrelevant server 'error'
  // event (e.g. "Audio content of 15000ms is already shorter than
  // 16500ms") in flight on the data channel, which can still be delivered
  // after dc.close() was called (WebRTC data channels don't guarantee
  // already-buffered messages are dropped on close). That error is about a
  // call the user already ended on purpose, so it's noise, not a real
  // failure -- suppress it instead of popping it into the chat's error
  // banner right after a clean hangup.
  let userInitiatedDisconnect = false;

  const cleanup = () => {
    dc?.close();
    dc = null;
    pc?.close();
    pc = null;
    micStream?.getTracks().forEach((t) => t.stop());
    micStream = null;
    if (audioEl) {
      audioEl.srcObject = null;
      audioEl = null;
    }
    inputAnalyser = null;
    outputAnalyser = null;
    analysisCtx?.close().catch(() => {});
    analysisCtx = null;
  };

  const handleFunctionCall = async (channel: RTCDataChannel, message: any) => {
    if (message.name !== 'search_policies') return;
    let question = '';
    try {
      question = JSON.parse(message.arguments || '{}').question || '';
    } catch {
      question = '';
    }
    if (!question) return;

    // "thinking" -- the request is in flight (real event, not a timer):
    // drives the orb's faster/larger rim wobble per the design spec.
    setStatus('thinking');
    console.log('[voice/openai] /voice/ask ->', question);
    try {
      const sid = await getSessionId();
      const res = await api.voiceAsk(question, sid);
      console.log('[voice/openai] /voice/ask <-', res.answer, res.sources);
      setSources(res.sources);

      channel.send(
        JSON.stringify({
          type: 'conversation.item.create',
          item: {
            type: 'function_call_output',
            call_id: message.call_id,
            output: JSON.stringify({ answer: res.answer }),
          },
        }),
      );
      channel.send(JSON.stringify({ type: 'response.create' }));

      onExchangeComplete(question, { role: 'assistant', text: res.answer, sources: res.sources });
    } catch (err) {
      // Tell the model the lookup failed so it can say so out loud,
      // instead of leaving the tool call hanging forever.
      const detail = err instanceof Error ? err.message : 'Lookup failed.';
      channel.send(
        JSON.stringify({
          type: 'conversation.item.create',
          item: {
            type: 'function_call_output',
            call_id: message.call_id,
            output: JSON.stringify({ error: detail }),
          },
        }),
      );
      channel.send(JSON.stringify({ type: 'response.create' }));
      setError(detail);
    }
  };

  const handleMessage = (channel: RTCDataChannel, event: MessageEvent) => {
    let message: any;
    try {
      message = JSON.parse(event.data);
    } catch {
      return;
    }

    switch (message.type) {
      case 'session.created':
        console.log('[voice/openai] session.created', message.session);
        setStatus('listening');
        // OpenAI's Realtime session never speaks on its own -- unlike
        // Deepgram's dedicated agent.greeting field, there's no
        // session-level "speak first" setting here, so the model only
        // knows to greet first via its instructions (see api.py's
        // _VOICE_SESSION_INSTRUCTIONS); this response.create is what
        // actually triggers it to say that opening line now, before any
        // user audio has arrived.
        channel.send(JSON.stringify({ type: 'response.create' }));
        break;

      case 'input_audio_buffer.speech_started':
        console.log('[voice/openai] speech_started');
        setCaptionText('');
        setSources([]);
        setStatus('listening');
        // A new employee utterance is starting (including a barge-in over
        // the agent) -- the caption no longer belongs to whatever the
        // assistant was saying, so a still-in-flight transcription-
        // completed event for THAT prior turn is stale too and shouldn't
        // land once this fires. This mirrors resetting below on the
        // assistant's own turn start.
        assistantAudioActive = false;
        break;

      case 'conversation.item.input_audio_transcription.completed':
        console.log('[voice/openai] user transcript:', message.transcript);
        // See assistantAudioActive's docstring above -- this transcript
        // comes from a slower, separate async pipeline and can arrive
        // after the assistant's reply has already started streaming its
        // own caption text. Dropping it once that's happened is what
        // actually fixes the race, rather than just narrowing the window
        // it can land in.
        if (message.transcript && !assistantAudioActive) setCaptionText(message.transcript);
        break;

      case 'response.function_call_arguments.done':
        console.log('[voice/openai] tool call:', message.name, message.arguments);
        handleFunctionCall(channel, message);
        break;

      case 'output_audio_buffer.started':
        setStatus('speaking');
        setCaptionText('');
        assistantAudioActive = true;
        break;

      case 'response.output_audio_transcript.delta':
        setCaptionText((prev) => prev + (message.delta || ''));
        break;

      case 'response.output_audio_transcript.done':
        console.log('[voice/openai] assistant transcript:', message.transcript);
        if (message.transcript) setCaptionText(message.transcript);
        break;

      case 'output_audio_buffer.stopped':
        setStatus('listening');
        assistantAudioActive = false;
        break;

      case 'error': {
        // OpenAI's Realtime 'error' events are often non-fatal (e.g. one
        // rejected client event) and the session otherwise keeps running,
        // so this doesn't force a disconnect -- but it must at least
        // surface via setError, which it previously didn't (console-only),
        // so a real failure here looked identical to no response at all.
        // A truly dead connection is caught separately by
        // pc.onconnectionstatechange below.
        const errMsg: string = message.error?.message || '';

        // Live-reported repeatedly (three separate occurrences, different
        // numbers each time: "Audio content of 15000ms is already shorter
        // than 16500ms", then 6300/6620, then 7950/8140) -- always
        // surfaces AFTER the call already ended, never during. The
        // shorter/longer ratio isn't constant across occurrences (1.10x,
        // 1.05x, 1.02x), which rules out a fixed cause like our own
        // speed:0.9/0.8 playback-rate setting (that would produce a
        // constant ratio) -- this looks like an inherent, benign
        // duration-accounting message OpenAI's server emits internally
        // around response truncation/interruption bookkeeping, unrelated
        // to anything actually going wrong in the conversation (the
        // exchange itself always completed fine). Purely cosmetic and not
        // actionable by the user, so suppress this specific message class
        // unconditionally rather than only around hangup timing -- if it
        // ever turns out to correlate with an actual broken exchange,
        // narrow this back down instead of removing it outright.
        if (/audio content of .*is already shorter than/i.test(errMsg)) {
          console.warn('[voice/openai] benign server duration-accounting error, suppressed:', message.error);
          break;
        }
        // Anything else: if the user already hung up on purpose, see
        // userInitiatedDisconnect's comment above.
        if (userInitiatedDisconnect) {
          console.warn('[voice/openai] server error event after intentional hangup, suppressed:', message.error);
          break;
        }
        console.error('[voice/openai] server error event:', message.error);
        setError(errMsg || 'Voice session error.');
        break;
      }

      default:
        break;
    }
  };

  try {
    console.log('[voice/openai] requesting microphone...');
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    console.log('[voice/openai] microphone granted, tracks:', micStream.getAudioTracks().length);
  } catch (err) {
    console.error('[voice/openai] getUserMedia failed:', err);
    throw new Error('Microphone access is required for voice.');
  }

  analysisCtx = new AudioContext();
  inputAnalyser = analysisCtx.createAnalyser();
  inputAnalyser.fftSize = 256;
  analysisCtx.createMediaStreamSource(micStream).connect(inputAnalyser);

  try {
    pc = new RTCPeerConnection();

    // Without this, a dropped/failed connection left status stuck at
    // 'listening'/'speaking' forever -- the mic toggle button
    // (useDocAssist's onToggleListen) only calls connect() when status is
    // 'idle', so pressing it again just called disconnect() on an
    // already-dead session: exactly "doesn't respond at all".
    pc.onconnectionstatechange = () => {
      if (!pc) return;
      console.log('[voice/openai] connection state:', pc.connectionState);
      if (pc.connectionState === 'failed' || pc.connectionState === 'closed') {
        setError('Voice connection lost.');
        cleanup();
        setStatus('idle');
      }
    };

    audioEl = new Audio();
    audioEl.autoplay = true;
    pc.ontrack = (e) => {
      if (audioEl) audioEl.srcObject = e.streams[0];
      // Same track, tapped a second time into the analysis-only graph --
      // native <audio> playback above is unaffected, this is purely a
      // parallel consumer for level data.
      if (analysisCtx) {
        outputAnalyser = analysisCtx.createAnalyser();
        outputAnalyser.fftSize = 256;
        analysisCtx.createMediaStreamSource(e.streams[0]).connect(outputAnalyser);
      }
    };

    const [audioTrack] = micStream.getAudioTracks();
    pc.addTrack(audioTrack, micStream);

    dc = pc.createDataChannel('oai-events');
    dc.addEventListener('message', (e) => handleMessage(dc!, e));

    console.log('[voice/openai] creating local SDP offer...');
    await pc.setLocalDescription();
    console.log('[voice/openai] local SDP offer ready, length:', pc.localDescription?.sdp?.length);

    console.log('[voice/openai] exchanging SDP with OpenAI...');
    const response = await fetch(OPENAI_REALTIME_CALLS_URL, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${session.credential}`,
        'Content-Type': 'application/sdp',
      },
      body: pc.localDescription?.sdp,
    });
    console.log('[voice/openai] SDP exchange response status:', response.status);
    if (!response.ok) {
      const bodyText = await response.text();
      throw new Error(`OpenAI Realtime connection failed (${response.status}): ${bodyText}`);
    }
    const answerSdp = await response.text();
    await pc.setRemoteDescription({ type: 'answer', sdp: answerSdp });
    console.log('[voice/openai] WebRTC connected, peer connection state:', pc.connectionState, connection.model, connection.voice);
  } catch (err) {
    cleanup();
    throw err;
  }

  const setMuted = (muted: boolean) => {
    micStream?.getAudioTracks().forEach((t) => {
      t.enabled = !muted;
    });
  };

  const disconnect = () => {
    userInitiatedDisconnect = true;
    cleanup();
  };

  const getAnalysers = () => ({ input: inputAnalyser, output: outputAnalyser });

  return { disconnect, setMuted, getAnalysers };
}
