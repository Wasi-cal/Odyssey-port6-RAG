'use client';

import { useEffect, useRef } from 'react';

export type OrbState = 'listening' | 'thinking' | 'speaking';

interface Particle {
  a: number; // fixed polar angle
  r: number; // fixed polar radius from center, 2-26px
  s: number; // square size, mostly 0.9px, ~15% at 1.6px
  ph: number; // twinkle phase
  jph: number; // jitter phase
}

/**
 * Canvas-based voice orb, ported 1:1 from the HR Chatbot design handoff's
 * `_startOrb`/`_drawOrb` methods (see design_handoff_hr_chatbot/HR
 * Chatbot.dc.html). Renders at 72x72 internal resolution, displayed at
 * 180x180 CSS px with `image-rendering: pixelated` for the chunky/pixel
 * texture -- driven by the REAL voice state machine (listening/thinking/
 * speaking come from actual speech-to-text / LLM / TTS events, see
 * hooks/useRealtimeVoice.ts and hooks/voice/*), not a scripted demo timer.
 */
export function VoiceOrb({ state }: { state: OrbState }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.imageSmoothingEnabled = false;

    const particles: Particle[] = Array.from({ length: 70 }, () => ({
      a: Math.random() * Math.PI * 2,
      r: Math.random() * 24 + 2,
      s: Math.random() < 0.15 ? 1.6 : 0.9,
      ph: Math.random() * Math.PI * 2,
      jph: Math.random() * Math.PI * 2,
    }));

    const start = performance.now();
    let raf = 0;

    const drawOrb = (cx: number, cy: number, t: number) => {
      ctx.clearRect(0, 0, 72, 72);
      const state = stateRef.current;
      const agitated = state !== 'speaking';
      const amp = state === 'thinking' ? 6.5 : state === 'listening' ? 4 : 1.4;
      const freq = state === 'thinking' ? 3.4 : 2.4;
      const speed = state === 'thinking' ? 1.7 : state === 'listening' ? 1.1 : 0.45;
      const R = 27;

      particles.forEach((p) => {
        let jx = 0;
        let jy = 0;
        if (agitated) {
          const k = state === 'thinking' ? 1.8 : 0.9;
          jx = Math.sin(t * 2.2 + p.jph) * k;
          jy = Math.cos(t * 2.0 + p.jph) * k;
        }
        const x = cx + Math.cos(p.a) * p.r + jx;
        const y = cy + Math.sin(p.a) * p.r + jy;
        const op = 0.4 + 0.55 * Math.abs(Math.sin(t * (agitated ? 2.6 : 1.1) + p.ph));
        ctx.fillStyle = `rgba(109,75,184,${op.toFixed(2)})`;
        ctx.fillRect(x, y, p.s, p.s);
      });

      const N = 18;
      for (let pass = 0; pass < 2; pass++) {
        const rimR = R + 1 + pass * 2;
        ctx.beginPath();
        for (let i = 0; i <= N; i++) {
          const a = (i / N) * Math.PI * 2;
          const rad = rimR + amp * Math.sin(freq * a + t * speed) + amp * 0.5 * Math.sin(freq * 1.8 * a - t * speed * 1.3);
          const x = cx + Math.cos(a) * rad;
          const y = cy + Math.sin(a) * rad;
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.strokeStyle = pass === 0 ? 'rgba(109,75,184,0.7)' : 'rgba(109,75,184,0.3)';
        ctx.lineWidth = 1;
        ctx.stroke();
      }
    };

    const loop = (now: number) => {
      drawOrb(36, 36, (now - start) / 1000);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);

    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <div className="flex h-[180px] w-[180px] items-center justify-center">
      <canvas
        ref={canvasRef}
        width={72}
        height={72}
        style={{ width: 180, height: 180, imageRendering: 'pixelated' }}
      />
    </div>
  );
}
