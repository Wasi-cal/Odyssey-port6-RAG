'use client';

import { useEffect, useRef } from 'react';

export type OrbState = 'listening' | 'thinking' | 'speaking';

interface VoiceOrbProps {
  state: OrbState;
}

/**
 * Voice visualizer, take 4 -- deliberately NOT an orb/blob this time (see
 * git history for takes 1-3). Current-generation voice assistants
 * (Apple's post-2024 Siri, Google's Gemini Live) have largely moved away
 * from a single glowing sphere toward a glowing ring / audio-reactive
 * waveform instead -- this is a radial bar equalizer: a ring of glowing
 * bars around a center point, each pulsing independently (layered sine
 * waves with per-bar phase/frequency offsets, since we have no real
 * amplitude data to react to -- state is the only real signal, from the
 * actual realtime voice pipeline, see hooks/useRealtimeVoice.ts), plus a
 * soft ambient glow and a small breathing center dot so it still reads as
 * one cohesive object, not just loose bars.
 *
 * Same public interface (OrbState, VoiceOrb({state})) as the previous
 * takes, so VoiceOverlay.tsx needs no changes.
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

    const BAR_COUNT = 48;
    // Per-bar random phase/frequency so bars don't all move in lockstep
    // (that would read as a single pulsing ring, not a "listening" ring of
    // independent bars) -- generated once, stable for the component's
    // lifetime.
    const bars = Array.from({ length: BAR_COUNT }, () => ({
      phase: Math.random() * Math.PI * 2,
      freq: 0.6 + Math.random() * 0.8,
    }));

    // Per-state motion profile: `base`/`amp` are the bar length's resting
    // length and how much it pulses (as a fraction of the ring radius),
    // `speed` scales every sine's time coefficient, `spin` slowly rotates
    // the whole ring (a static ring of bars reads as inert; a slow spin
    // keeps it feeling alive even at rest), `hueShift` pushes the gradient
    // further toward pink for more "active" states.
    const PROFILES: Record<OrbState, { base: number; amp: number; speed: number; spin: number; hueShift: number }> = {
      listening: { base: 0.25, amp: 0.12, speed: 0.9, spin: 0.06, hueShift: 0 },
      thinking: { base: 0.28, amp: 0.22, speed: 2.2, spin: 0.22, hueShift: 0.3 },
      speaking: { base: 0.32, amp: 0.38, speed: 3.4, spin: 0.02, hueShift: 0.6 },
    };

    const start = performance.now();

    const draw = (now: number) => {
      const t = (now - start) / 1000;
      const p = PROFILES[stateRef.current];

      ctx.clearRect(0, 0, width, height);

      const cx = width / 2;
      const cy = height / 2;
      const R = Math.min(width, height) * 0.5;
      const innerR = R * 0.42;
      const spinAngle = t * p.spin;

      // Ambient glow wash behind the ring, breathing slowly.
      const glowR = R * (0.95 + 0.05 * Math.sin(t * p.speed * 0.4));
      const glow = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowR);
      glow.addColorStop(0, `rgba(155, 127, 224, ${0.22 + 0.1 * p.hueShift})`);
      glow.addColorStop(1, 'rgba(231, 155, 208, 0)');
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(cx, cy, glowR, 0, Math.PI * 2);
      ctx.fill();

      // The bars themselves -- each a short gradient-colored, rounded
      // stroke radiating outward from innerR, length modulated by two
      // summed sines (its own phase/freq plus a shared time base) so
      // neighboring bars move somewhat together (a "wave" traveling
      // around the ring) without being perfectly synchronized.
      ctx.lineCap = 'round';
      for (let i = 0; i < BAR_COUNT; i++) {
        const b = bars[i];
        const angle = (i / BAR_COUNT) * Math.PI * 2 + spinAngle;
        const wave =
          Math.sin(t * p.speed * b.freq + b.phase) * 0.6 + Math.sin(t * p.speed * 0.5 + angle * 3) * 0.4;
        const len = R * (p.base + p.amp * Math.max(0, wave));

        const x1 = cx + Math.cos(angle) * innerR;
        const y1 = cy + Math.sin(angle) * innerR;
        const x2 = cx + Math.cos(angle) * (innerR + len);
        const y2 = cy + Math.sin(angle) * (innerR + len);

        const hue = 265 + p.hueShift * 40 * Math.sin(angle + t * 0.3);
        ctx.strokeStyle = `hsla(${hue}, 70%, 72%, ${0.55 + 0.35 * Math.max(0, wave)})`;
        ctx.lineWidth = Math.max(2, R * 0.028);
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
      }

      // Small breathing center dot -- ties the ring together as one
      // object and gives "thinking"/"speaking" a focal point.
      const dotR = innerR * (0.4 + 0.08 * Math.sin(t * p.speed * 1.3));
      const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, dotR);
      core.addColorStop(0, 'rgba(255, 255, 255, 0.9)');
      core.addColorStop(1, 'rgba(219, 199, 245, 0)');
      ctx.fillStyle = core;
      ctx.beginPath();
      ctx.arc(cx, cy, dotR, 0, Math.PI * 2);
      ctx.fill();

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
