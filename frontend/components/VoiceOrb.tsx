'use client';

import { useEffect, useRef } from 'react';

export type OrbState = 'listening' | 'thinking' | 'speaking';

interface VoiceOrbProps {
  state: OrbState;
}

/**
 * Voice orb, take 3 -- a smooth glowing gradient blob instead of the
 * earlier pixelated particle-field version. Fills its container (sized by
 * VoiceOverlay.tsx) rather than a fixed internal resolution, redrawn on
 * resize via ResizeObserver, and rendered at devicePixelRatio for crisp
 * edges instead of the old canvas's deliberate pixelation.
 *
 * Built from three soft, blurred, overlapping circles (a "lava lamp"
 * blob) drifting and breathing at a state-dependent amplitude/speed, plus
 * a bright core and a thin outer ring. No audio-level input is wired up
 * (state is the only real signal we have -- listening/thinking/speaking
 * come from the actual realtime voice pipeline, see
 * hooks/useRealtimeVoice.ts) -- motion is state-driven, not amplitude-
 * driven, same as the previous implementation.
 */
export function VoiceOrb({ state }: VoiceOrbProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let raf = 0;
    let width = 0;
    let height = 0;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      width = rect.width;
      height = rect.height;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    // Per-state motion profile: `breathe` is how much the overall blob
    // scales in/out, `drift` is how far the inner blobs wander from
    // center, `speed` scales every sine's time coefficient (higher =
    // faster/busier motion), `glow` is the outer glow's blur radius as a
    // fraction of the orb radius.
    const PROFILES: Record<OrbState, { breathe: number; drift: number; speed: number; glow: number }> = {
      listening: { breathe: 0.05, drift: 0.14, speed: 0.6, glow: 0.35 },
      thinking: { breathe: 0.08, drift: 0.22, speed: 1.6, glow: 0.5 },
      speaking: { breathe: 0.16, drift: 0.1, speed: 2.6, glow: 0.65 },
    };

    const start = performance.now();

    const draw = (now: number) => {
      const t = (now - start) / 1000;
      const p = PROFILES[stateRef.current];

      ctx.clearRect(0, 0, width, height);

      const cx = width / 2;
      const cy = height / 2;
      const baseR = Math.min(width, height) * 0.28;
      const breathe = 1 + p.breathe * Math.sin(t * p.speed);
      const r = baseR * breathe;

      // Outer soft glow -- a large, heavily blurred radial wash behind
      // everything, pulsing a bit slower/wider than the core blob so it
      // reads as ambient light rather than a hard edge.
      const glowR = r * (1.8 + 0.15 * Math.sin(t * p.speed * 0.7));
      const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowR);
      glow.addColorStop(0, `rgba(155, 127, 224, ${0.35 * p.glow + 0.15})`);
      glow.addColorStop(0.6, 'rgba(231, 155, 208, 0.12)');
      glow.addColorStop(1, 'rgba(231, 155, 208, 0)');
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(cx, cy, glowR, 0, Math.PI * 2);
      ctx.fill();

      // Three overlapping blobs (screen-blended) drifting on independent
      // orbits -- this is what gives the "lava lamp" liveliness instead of
      // a single static circle. Each blob is itself a radial gradient
      // (bright center fading to transparent) so overlaps brighten
      // naturally rather than showing hard seams.
      ctx.globalCompositeOperation = 'screen';
      const blobs = [
        { hue: [155, 127, 224] as const, a: t * p.speed * 0.9, phase: 0 },
        { hue: [231, 155, 208] as const, a: t * p.speed * 1.1, phase: (Math.PI * 2) / 3 },
        { hue: [109, 75, 184] as const, a: t * p.speed * 0.75, phase: (Math.PI * 4) / 3 },
      ];
      for (const b of blobs) {
        const angle = b.a + b.phase;
        const dist = r * p.drift * (0.6 + 0.4 * Math.sin(t * p.speed * 0.5 + b.phase));
        const bx = cx + Math.cos(angle) * dist;
        const by = cy + Math.sin(angle) * dist;
        const br = r * 0.75;
        const [red, green, blue] = b.hue;
        const grad = ctx.createRadialGradient(bx, by, 0, bx, by, br);
        grad.addColorStop(0, `rgba(${red}, ${green}, ${blue}, 0.9)`);
        grad.addColorStop(1, `rgba(${red}, ${green}, ${blue}, 0)`);
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(bx, by, br, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalCompositeOperation = 'source-over';

      // Bright core -- a small, mostly-opaque highlight near center so the
      // orb reads as one cohesive object with a "light source" rather than
      // three loose blobs, plus a thin ring tracing the orb's nominal
      // radius for definition against the blurred glow.
      const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, r * 0.55);
      core.addColorStop(0, 'rgba(255, 255, 255, 0.85)');
      core.addColorStop(0.4, 'rgba(219, 199, 245, 0.55)');
      core.addColorStop(1, 'rgba(219, 199, 245, 0)');
      ctx.fillStyle = core;
      ctx.beginPath();
      ctx.arc(cx, cy, r * 0.55, 0, Math.PI * 2);
      ctx.fill();

      ctx.strokeStyle = 'rgba(255, 255, 255, 0.45)';
      ctx.lineWidth = Math.max(1, r * 0.015);
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.stroke();

      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, []);

  return <canvas ref={canvasRef} style={{ width: '100%', height: '100%', display: 'block' }} />;
}
