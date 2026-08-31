'use client';

import { useEffect, useRef } from 'react';

export type OrbState = 'listening' | 'thinking' | 'speaking';

interface Particle {
  a: number;
  r: number;
  size: number;
  phase: number;
  speed: number;
  drift: number;
}

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

    const SIZE = 104;
    const CENTER = SIZE / 2;

    const particles: Particle[] = Array.from(
      { length: 120 },
      (_, i) => {
        const angle =
          (i / 120) * Math.PI * 2;

        return {
          a:
            angle +
            (Math.random() - 0.5) * 0.2,

          r:
            4 +
            Math.pow(Math.random(), 0.65) * 36,

          size:
            Math.random() < 0.14
              ? 1.8
              : 1,

          phase:
            Math.random() *
            Math.PI *
            2,

          speed:
            0.15 +
            Math.random() * 0.45,

          drift:
            0.5 +
            Math.random() * 1.2,
        };
      },
    );

    const start = performance.now();
    let raf = 0;

    const drawOrb = (t: number) => {
      ctx.clearRect(
        0,
        0,
        SIZE,
        SIZE,
      );

      const state = stateRef.current;

      const config = {
        listening: {
          pulse: 0.9,
          rimAmplitude: 3.2,
          rimSpeed: 0.8,
          particleSpeed: 0.8,
          jitter: 0.45,
          opacity: 0.72,
        },

        thinking: {
          pulse: 1.35,
          rimAmplitude: 6.5,
          rimSpeed: 1.8,
          particleSpeed: 1.7,
          jitter: 1.8,
          opacity: 0.92,
        },

        speaking: {
          pulse: 1.8,
          rimAmplitude: 2.3,
          rimSpeed: 0.65,
          particleSpeed: 1.1,
          jitter: 0.3,
          opacity: 0.84,
        },
      }[state];

      /*
       * Overall breathing motion.
       */
      const breath =
        Math.sin(
          t * config.pulse,
        ) *
          0.7 +
        Math.sin(
          t *
            config.pulse *
            0.47,
        ) *
          0.3;

      const baseR =
        38 +
        breath * 1.5;

      /*
       * Particles.
       */
      particles.forEach((p) => {
        const angle =
          p.a +
          t *
            p.speed *
            config.particleSpeed *
            0.35;

        const radialWave =
          Math.sin(
            t * p.drift +
              p.phase,
          ) *
          config.jitter;

        const radius =
          p.r + radialWave;

        const x =
          CENTER +
          Math.cos(angle) *
            radius;

        const y =
          CENTER +
          Math.sin(angle) *
            radius;

        const twinkle =
          0.45 +
          0.5 *
            Math.abs(
              Math.sin(
                t *
                  (state ===
                  'thinking'
                    ? 3
                    : 1.6) +
                  p.phase,
              ),
            );

        const distanceFade =
          0.55 +
          0.45 *
            (p.r / 42);

        const opacity =
          config.opacity *
          twinkle *
          distanceFade;

        ctx.fillStyle =
          `rgba(109,75,184,${opacity.toFixed(2)})`;

        ctx.fillRect(
          Math.round(x),
          Math.round(y),
          p.size,
          p.size,
        );
      });

      /*
       * Organic outer rim.
       */
      const POINTS = 64;

      for (
        let pass = 2;
        pass >= 0;
        pass--
      ) {
        const radius =
          baseR +
          pass * 2.2;

        ctx.beginPath();

        for (
          let i = 0;
          i <= POINTS;
          i++
        ) {
          const angle =
            (i / POINTS) *
            Math.PI *
            2;

          const wave1 =
            Math.sin(
              angle * 3 +
                t *
                  config.rimSpeed,
            );

          const wave2 =
            Math.sin(
              angle * 5.3 -
                t *
                  config.rimSpeed *
                  0.72,
            );

          const wave3 =
            Math.sin(
              angle * 7.7 +
                t *
                  config.rimSpeed *
                  1.4,
            );

          const turbulence =
            state === 'thinking'
              ? Math.sin(
                  angle * 11 -
                    t * 2.4,
                ) * 0.9
              : 0;

          const deformation =
            wave1 *
              config.rimAmplitude +
            wave2 *
              config.rimAmplitude *
              0.42 +
            wave3 *
              config.rimAmplitude *
              0.18 +
            turbulence;

          const r =
            radius +
            deformation;

          const x =
            CENTER +
            Math.cos(angle) *
              r;

          const y =
            CENTER +
            Math.sin(angle) *
              r;

          if (i === 0) {
            ctx.moveTo(x, y);
          } else {
            ctx.lineTo(x, y);
          }
        }

        ctx.closePath();

        const opacity =
          pass === 0
            ? 0.76
            : pass === 1
              ? 0.3
              : 0.12;

        ctx.strokeStyle =
          `rgba(109,75,184,${opacity})`;

        ctx.lineWidth = 1;

        ctx.stroke();
      }

      /*
       * Subtle inner energy ring.
       */
      const corePulse =
        0.5 +
        0.5 *
          Math.sin(
            t * config.pulse,
          );

      const coreR =
        29 +
        corePulse * 1.5;

      ctx.beginPath();

      for (
        let i = 0;
        i <= POINTS;
        i++
      ) {
        const angle =
          (i / POINTS) *
          Math.PI *
          2;

        const wobble =
          Math.sin(
            angle * 4 +
              t * 0.8,
          ) * 0.5;

        const r =
          coreR + wobble;

        const x =
          CENTER +
          Math.cos(angle) * r;

        const y =
          CENTER +
          Math.sin(angle) * r;

        if (i === 0) {
          ctx.moveTo(x, y);
        } else {
          ctx.lineTo(x, y);
        }
      }

      ctx.closePath();

      ctx.strokeStyle =
        `rgba(109,75,184,${(
          0.12 +
          corePulse * 0.08
        ).toFixed(2)})`;

      ctx.stroke();
    };

    const loop = (
      now: number,
    ) => {
      drawOrb(
        (now - start) / 1000,
      );

      raf =
        requestAnimationFrame(
          loop,
        );
    };

    raf =
      requestAnimationFrame(
        loop,
      );

    return () =>
      cancelAnimationFrame(
        raf,
      );
  }, []);

  return (
    <div className="flex h-[260px] w-[260px] items-center justify-center">
      <canvas
        ref={canvasRef}
        width={104}
        height={104}
        style={{
          width: 260,
          height: 260,
          imageRendering:
            'pixelated',
        }}
      />
    </div>
  );
}