'use client';

import { useEffect, useRef } from 'react';

export type OrbState = 'listening' | 'thinking' | 'speaking';

interface VoiceOrbProps {
  state: OrbState;
  /** Real Web Audio AnalyserNode (mic while listening, agent output while
   * speaking) -- when present, its live level drives how much the circle
   * scales up on top of its resting size. Optional -- without it the
   * circle just holds its resting size and a gentle idle pulse. */
  analyser?: AnalyserNode | null;
}

/**
 * Voice visualizer, take 5 -- back to basics per request ("remove the
 * flame, basic voice bot thing"): a single solid circle, softly glowing,
 * that scales up with real audio level and changes color/pulse speed by
 * state. No particles, no ribbons, no multi-layer compositing -- the
 * simplest thing that still reads as "listening/thinking/speaking" and
 * reacts to actual sound.
 */
export function VoiceOrb({ state, analyser = null }: VoiceOrbProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;
  const analyserRef = useRef<AnalyserNode | null>(analyser);
  useEffect(() => {
    analyserRef.current = analyser;
  }, [analyser]);

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

    let freqData: Uint8Array<ArrayBuffer> | null = null;
    let energy = 0;
    const readEnergy = (): number => {
      const a = analyserRef.current;
      if (!a) return 0;
      if (!freqData || freqData.length !== a.frequencyBinCount) {
        freqData = new Uint8Array(new ArrayBuffer(a.frequencyBinCount));
      }
      a.getByteFrequencyData(freqData);
      let sum = 0;
      for (let i = 0; i < freqData.length; i++) sum += freqData[i];
      return sum / freqData.length / 255;
    };

    // idlePulse: how much the resting size breathes on its own with no
    // audio at all. pulseSpeed: that breathing's rate. color: the solid
    // fill. energyGain: how much real audio scales the circle beyond its
    // resting size.
    const PROFILES: Record<OrbState, { idlePulse: number; pulseSpeed: number; color: string; energyGain: number }> = {
      listening: { idlePulse: 0.03, pulseSpeed: 1.2, color: '#8b6dcc', energyGain: 0.35 },
      thinking: { idlePulse: 0.06, pulseSpeed: 2.4, color: '#6d4bb8', energyGain: 0.15 },
      speaking: { idlePulse: 0.04, pulseSpeed: 1.6, color: '#9b7fe0', energyGain: 0.5 },
    };

    const start = performance.now();

    const draw = (now: number) => {
      const t = (now - start) / 1000;
      const p = PROFILES[stateRef.current];

      const raw = readEnergy();
      energy += (raw - energy) * 0.25;

      ctx.clearRect(0, 0, width, height);

      const cx = width / 2;
      const cy = height / 2;
      const baseR = Math.min(width, height) * 0.3;
      const idle = 1 + p.idlePulse * Math.sin(t * p.pulseSpeed);
      const r = baseR * idle * (1 + energy * p.energyGain);

      // Soft outer glow.
      const glow = ctx.createRadialGradient(cx, cy, r * 0.6, cx, cy, r * 1.8);
      glow.addColorStop(0, `${p.color}33`);
      glow.addColorStop(1, `${p.color}00`);
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(cx, cy, r * 1.8, 0, Math.PI * 2);
      ctx.fill();

      // The circle itself.
      ctx.fillStyle = p.color;
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
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
