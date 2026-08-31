'use client';

import { useEffect, useRef } from 'react';

export type OrbState =
  | 'listening'
  | 'thinking'
  | 'speaking';

interface VoiceOrbProps {
  state: OrbState;
  /** Real Web Audio AnalyserNode (mic while listening, agent output while
   * speaking) -- when present, its live level scales height/width/
   * brightness on top of the state profile below, so the shape actually
   * pulses with real audio instead of only the state-driven idle motion.
   * Optional/omittable -- looks and animates exactly as before when
   * absent. */
  analyser?: AnalyserNode | null;
}

type RGBColor = {
  r: number;
  g: number;
  b: number;
};

const PURPLE: RGBColor = {
  r: 109,
  g: 75,
  b: 184,
};

const LAVENDER: RGBColor = {
  r: 157,
  g: 126,
  b: 225,
};

const PINK: RGBColor = {
  r: 218,
  g: 139,
  b: 198,
};

const WHITE: RGBColor = {
  r: 255,
  g: 255,
  b: 255,
};

const rgba = (
  color: RGBColor | string,
  alpha = 1,
): string => {
  const safeAlpha = Math.min(
    1,
    Math.max(0, alpha),
  );

  if (typeof color !== 'string') {
    return `rgba(${color.r}, ${color.g}, ${color.b}, ${safeAlpha})`;
  }

  let hex = color
    .trim()
    .replace(/^#/, '');

  if (
    hex.length === 3 ||
    hex.length === 4
  ) {
    hex = hex
      .split('')
      .map(
        (char) => char + char,
      )
      .join('');
  }

  if (
    /^[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/.test(
      hex,
    )
  ) {
    const num = parseInt(
      hex,
      16,
    );

    let finalAlpha =
      safeAlpha;

    if (
      hex.length === 8 &&
      alpha === 1
    ) {
      finalAlpha = Number(
        (
          (num & 0xff) /
          255
        ).toFixed(2),
      );

      return `rgba(${
        (num >> 24) & 0xff
      }, ${
        (num >> 16) & 0xff
      }, ${
        (num >> 8) & 0xff
      }, ${finalAlpha})`;
    }

    return `rgba(${
      (num >> 16) & 0xff
    }, ${
      (num >> 8) & 0xff
    }, ${
      num & 0xff
    }, ${finalAlpha})`;
  }

  return `rgba(0, 0, 0, ${safeAlpha})`;
};

const clamp = (
  value: number,
  min: number,
  max: number,
) =>
  Math.max(
    min,
    Math.min(max, value),
  );

export function VoiceOrb({
  state,
  analyser = null,
}: VoiceOrbProps) {
  const canvasRef =
    useRef<HTMLCanvasElement | null>(
      null,
    );

  const stateRef =
    useRef<OrbState>(state);

  stateRef.current = state;

  const analyserRef =
    useRef<AnalyserNode | null>(analyser);

  useEffect(() => {
    analyserRef.current = analyser;
  }, [analyser]);

  useEffect(() => {
    const canvas =
      canvasRef.current;

    if (!canvas) return;

    const ctx =
      canvas.getContext('2d');

    if (!ctx) return;

    let width = 0;
    let height = 0;
    let raf = 0;

    // Smoothed 0-1 audio energy from analyserRef.current (mic while
    // listening, agent output while speaking) -- averages the frequency
    // spectrum each frame and eases toward it rather than jumping, so it
    // reads as a natural pulse rather than jittering with every sample.
    // Stays 0 (no effect on the profile below) whenever no analyser is
    // provided, or it hasn't produced real data yet.
    let energy = 0;
    let freqData: Uint8Array<ArrayBuffer> | null = null;
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

    const dpr = Math.min(
      window.devicePixelRatio || 1,
      2,
    );

    /*
     * ------------------------------------------------------------
     * Canvas
     * ------------------------------------------------------------
     */

    const resize = () => {
      const rect =
        canvas.getBoundingClientRect();

      width = rect.width;
      height = rect.height;

      canvas.width =
        Math.round(
          width * dpr,
        );

      canvas.height =
        Math.round(
          height * dpr,
        );

      ctx.setTransform(
        dpr,
        0,
        0,
        dpr,
        0,
        0,
      );
    };

    resize();

    const observer =
      new ResizeObserver(resize);

    observer.observe(canvas);

    /*
     * ------------------------------------------------------------
     * Ribbon definitions
     * ------------------------------------------------------------
     *
     * Each ribbon has its own frequency, phase and width.
     * This prevents the strands from looking cloned.
     */

    const ribbons = [
      {
        phase: 0.0,
        frequency: 1.0,
        width: 1.0,
        opacity: 1.0,
        offset: 0,
      },
      {
        phase: 1.7,
        frequency: 0.83,
        width: 0.72,
        opacity: 0.48,
        offset: -7,
      },
      {
        phase: 3.2,
        frequency: 1.16,
        width: 0.62,
        opacity: 0.34,
        offset: 8,
      },
      {
        phase: 4.4,
        frequency: 0.71,
        width: 0.52,
        opacity: 0.23,
        offset: -13,
      },
      {
        phase: 5.3,
        frequency: 1.31,
        width: 0.44,
        opacity: 0.18,
        offset: 14,
      },
    ];

    /*
     * ------------------------------------------------------------
     * State profiles
     * ------------------------------------------------------------
     */

    const profiles: Record<
      OrbState,
      {
        height: number;
        width: number;
        wave: number;
        speed: number;
        brightness: number;
        strands: number;
      }
    > = {
      listening: {
        height: 0.72,
        width: 0.19,
        wave: 7,
        speed: 0.48,
        brightness: 0.72,
        strands: 2,
      },

      thinking: {
        height: 0.82,
        width: 0.27,
        wave: 15,
        speed: 0.95,
        brightness: 0.9,
        strands: 4,
      },

      speaking: {
        height: 0.88,
        width: 0.36,
        wave: 22,
        speed: 1.45,
        brightness: 1.15,
        strands: 5,
      },
    };

    const start =
      performance.now();

    /*
     * ------------------------------------------------------------
     * Draw one flowing ribbon
     * ------------------------------------------------------------
     */

    const drawRibbon = (
      t: number,
      ribbon: (typeof ribbons)[number],
      profile: (typeof profiles)[OrbState],
      index: number,
    ) => {
      const cx =
        width / 2;

      const bottom =
        height * 0.78;

      const top =
        height *
        (0.78 -
          profile.height);

      const ribbonWidth =
        Math.min(
          width,
          height,
        ) *
        profile.width *
        ribbon.width;

      /*
       * Build the center path first.
       */
      const points: Array<{
        x: number;
        y: number;
      }> = [];

      const steps = 80;

      for (
        let i = 0;
        i <= steps;
        i++
      ) {
        const progress =
          i / steps;

        const y =
          bottom -
          (bottom - top) *
            progress;

        /*
         * Main slow sine.
         */
        const wave1 =
          Math.sin(
            progress *
              Math.PI *
              2.1 +
              t *
                profile.speed *
                ribbon.frequency +
              ribbon.phase,
          );

        /*
         * Secondary deformation.
         */
        const wave2 =
          Math.sin(
            progress *
              Math.PI *
              4.4 -
              t *
                profile.speed *
                0.7 +
              ribbon.phase *
                1.7,
          );

        /*
         * Very slow large movement.
         */
        const wave3 =
          Math.sin(
            progress *
              Math.PI *
              1.15 -
              t *
                profile.speed *
                0.28,
          );

        /*
         * Speaking has stronger movement toward the middle
         * of the ribbon.
         */
        const centerWeight =
          Math.sin(
            progress *
              Math.PI,
          );

        const movement =
          wave1 *
            profile.wave *
            0.62 +
          wave2 *
            profile.wave *
            0.23 +
          wave3 *
            profile.wave *
            0.15;

        /*
         * Subtle state-specific movement.
         */
        const stateOffset =
          stateRef.current ===
          'speaking'
            ? Math.sin(
                t * 2.4 +
                  progress * 8,
              ) *
              centerWeight *
              3.5
            : stateRef.current ===
                'thinking'
              ? Math.sin(
                  t * 1.4 +
                    progress * 10,
                ) *
                centerWeight *
                2
              : 0;

        /*
         * Ribbons separate slightly near the top.
         */
        const separation =
          ribbon.offset *
          (
            0.25 +
            progress *
              0.85
          );

        points.push({
          x:
            cx +
            movement +
            stateOffset +
            separation,

          y,
        });
      }

      /*
       * ----------------------------------------------------------
       * Ribbon width
       * ----------------------------------------------------------
       *
       * Wider around the middle, narrow at both ends.
       */

      const getWidth =
        (
          progress: number,
        ) => {
          const body =
            Math.sin(
              progress *
                Math.PI,
            );

          /*
           * The bottom remains concentrated.
           * The middle blooms.
           * The top fades.
           */
          return (
            ribbonWidth *
            (
              0.18 +
              body * 0.82
            )
          );
        };

      /*
       * ----------------------------------------------------------
       * Build filled ribbon
       * ----------------------------------------------------------
       */

      const left: Array<{
        x: number;
        y: number;
      }> = [];

      const right: Array<{
        x: number;
        y: number;
      }> = [];

      for (
        let i = 0;
        i < points.length;
        i++
      ) {
        const point =
          points[i];

        const progress =
          i /
          (points.length - 1);

        const previous =
          points[
            Math.max(
              0,
              i - 1,
            )
          ];

        const next =
          points[
            Math.min(
              points.length - 1,
              i + 1,
            )
          ];

        /*
         * Tangent.
         */
        const dx =
          next.x -
          previous.x;

        const dy =
          next.y -
          previous.y;

        const length =
          Math.sqrt(
            dx * dx +
              dy * dy,
          ) || 1;

        /*
         * Normal.
         */
        const nx =
          -dy / length;

        const ny =
          dx / length;

        const halfWidth =
          getWidth(
            progress,
          ) / 2;

        left.push({
          x:
            point.x +
            nx * halfWidth,

          y:
            point.y +
            ny * halfWidth,
        });

        right.push({
          x:
            point.x -
            nx * halfWidth,

          y:
            point.y -
            ny * halfWidth,
        });
      }

      /*
       * ----------------------------------------------------------
       * Gradient
       * ----------------------------------------------------------
       */

      const gradient =
        ctx.createLinearGradient(
          0,
          top,
          0,
          bottom,
        );

      const alpha =
        ribbon.opacity *
        profile.brightness;

      gradient.addColorStop(
        0,
        rgba(
          LAVENDER,
          alpha * 0.02,
        ),
      );

      gradient.addColorStop(
        0.18,
        rgba(
          PURPLE,
          alpha * 0.28,
        ),
      );

      gradient.addColorStop(
        0.45,
        rgba(
          LAVENDER,
          alpha * 0.52,
        ),
      );

      gradient.addColorStop(
        0.68,
        rgba(
          PINK,
          alpha * 0.38,
        ),
      );

      gradient.addColorStop(
        0.88,
        rgba(
          LAVENDER,
          alpha * 0.22,
        ),
      );

      gradient.addColorStop(
        1,
        rgba(
          PURPLE,
          0,
        ),
      );

      /*
       * ----------------------------------------------------------
       * Fill
       * ----------------------------------------------------------
       */

      ctx.beginPath();

      ctx.moveTo(
        left[0].x,
        left[0].y,
      );

      for (
        let i = 1;
        i < left.length;
        i++
      ) {
        ctx.lineTo(
          left[i].x,
          left[i].y,
        );
      }

      for (
        let i =
          right.length - 1;
        i >= 0;
        i--
      ) {
        ctx.lineTo(
          right[i].x,
          right[i].y,
        );
      }

      ctx.closePath();

      ctx.fillStyle =
        gradient;

      ctx.fill();

      /*
       * ----------------------------------------------------------
       * Luminous center filament
       * ----------------------------------------------------------
       */

      ctx.beginPath();

      for (
        let i = 0;
        i < points.length;
        i++
      ) {
        const point =
          points[i];

        if (i === 0) {
          ctx.moveTo(
            point.x,
            point.y,
          );
        } else {
          ctx.lineTo(
            point.x,
            point.y,
          );
        }
      }

      const filament =
        ctx.createLinearGradient(
          0,
          top,
          0,
          bottom,
        );

      filament.addColorStop(
        0,
        rgba(
          LAVENDER,
          0,
        ),
      );

      filament.addColorStop(
        0.28,
        rgba(
          LAVENDER,
          alpha * 0.5,
        ),
      );

      filament.addColorStop(
        0.55,
        rgba(
          WHITE,
          alpha * 0.78,
        ),
      );

      filament.addColorStop(
        0.75,
        rgba(
          PINK,
          alpha * 0.5,
        ),
      );

      filament.addColorStop(
        1,
        rgba(
          WHITE,
          0,
        ),
      );

      ctx.strokeStyle =
        filament;

      ctx.lineWidth =
        Math.max(
          0.7,
          ribbonWidth *
            0.055,
        );

      ctx.lineCap =
        'round';

      ctx.stroke();
    };

    /*
     * ------------------------------------------------------------
     * Ground glow
     * ------------------------------------------------------------
     */

    const drawBaseGlow = (
      t: number,
      profile: (typeof profiles)[OrbState],
    ) => {
      const cx =
        width / 2;

      const cy =
        height * 0.78;

      const pulse =
        0.5 +
        0.5 *
          Math.sin(
            t *
              profile.speed *
              0.75,
          );

      const radius =
        Math.min(
          width,
          height,
        ) *
        (
          0.16 +
          pulse * 0.025
        );

      const glow =
        ctx.createRadialGradient(
          cx,
          cy,
          0,
          cx,
          cy,
          radius,
        );

      glow.addColorStop(
        0,
        rgba(
          WHITE,
          0.18 *
            profile.brightness,
        ),
      );

      glow.addColorStop(
        0.12,
        rgba(
          LAVENDER,
          0.16 *
            profile.brightness,
        ),
      );

      glow.addColorStop(
        0.4,
        rgba(
          PURPLE,
          0.08 *
            profile.brightness,
        ),
      );

      glow.addColorStop(
        1,
        rgba(
          PURPLE,
          0,
        ),
      );

      ctx.fillStyle =
        glow;

      ctx.beginPath();

      ctx.ellipse(
        cx,
        cy,
        radius,
        radius * 0.22,
        0,
        0,
        Math.PI * 2,
      );

      ctx.fill();

      /*
       * Very thin base reflection.
       */
      ctx.beginPath();

      ctx.ellipse(
        cx,
        cy,
        radius * 0.7,
        radius * 0.08,
        0,
        0,
        Math.PI * 2,
      );

      ctx.strokeStyle =
        rgba(
          LAVENDER,
          0.10 *
            profile.brightness,
        );

      ctx.lineWidth = 1;

      ctx.stroke();
    };

    /*
     * ------------------------------------------------------------
     * Main render
     * ------------------------------------------------------------
     */

    const render = (
      now: number,
    ) => {
      const t =
        (now - start) / 1000;

      const currentState =
        stateRef.current;

      const rawEnergy = readEnergy();
      energy += (rawEnergy - energy) * 0.25;

      const baseProfile =
        profiles[
          currentState
        ];

      // Real audio pushes height/width/brightness ABOVE the state's own
      // idle baseline -- multiplicative, so it's a genuine pulse on top
      // of the existing motion design, not a replacement for it. Every
      // other field (wave/speed/strands) is untouched, so the shape's
      // character never changes, only its intensity.
      const profile = {
        ...baseProfile,
        height: baseProfile.height * (1 + energy * 0.35),
        width: baseProfile.width * (1 + energy * 0.5),
        brightness: baseProfile.brightness * (1 + energy * 0.4),
      };

      ctx.clearRect(
        0,
        0,
        width,
        height,
      );

      /*
       * ----------------------------------------------------------
       * Huge soft atmospheric glow
       * ----------------------------------------------------------
       */

      const cx =
        width / 2;

      const cy =
        height * 0.48;

      const atmosphere =
        ctx.createRadialGradient(
          cx,
          cy,
          0,
          cx,
          cy,
          Math.min(
            width,
            height,
          ) *
            0.48,
        );

      atmosphere.addColorStop(
        0,
        rgba(
          PURPLE,
          0.045 *
            profile.brightness,
        ),
      );

      atmosphere.addColorStop(
        0.45,
        rgba(
          LAVENDER,
          0.022 *
            profile.brightness,
        ),
      );

      atmosphere.addColorStop(
        1,
        rgba(
          PURPLE,
          0,
        ),
      );

      ctx.fillStyle =
        atmosphere;

      ctx.beginPath();

      ctx.arc(
        cx,
        cy,
        Math.min(
          width,
          height,
        ) *
          0.48,
        0,
        Math.PI * 2,
      );

      ctx.fill();

      /*
       * ----------------------------------------------------------
       * Base
       * ----------------------------------------------------------
       */

      drawBaseGlow(
        t,
        profile,
      );

      /*
       * ----------------------------------------------------------
       * Ribbons
       * ----------------------------------------------------------
       *
       * Draw back → front.
       */

      const activeRibbons =
        ribbons.slice(
          0,
          profile.strands,
        );

      for (
        let i =
          activeRibbons.length -
          1;
        i >= 0;
        i--
      ) {
        drawRibbon(
          t,
          activeRibbons[i],
          profile,
          i,
        );
      }

      /*
       * ----------------------------------------------------------
       * Floating light near the core
       * ----------------------------------------------------------
       */

      const corePulse =
        0.5 +
        0.5 *
          Math.sin(
            t *
              profile.speed *
              0.9,
          );

      const coreX =
        cx +
        Math.sin(
          t *
            profile.speed *
            0.35,
        ) *
          3;

      const coreY =
        height * 0.75;

      const coreRadius =
        Math.min(
          width,
          height,
        ) *
        (
          0.025 +
          corePulse *
            0.008
        );

      const core =
        ctx.createRadialGradient(
          coreX,
          coreY,
          0,
          coreX,
          coreY,
          coreRadius * 4,
        );

      core.addColorStop(
        0,
        rgba(
          WHITE,
          0.9 *
            profile.brightness,
        ),
      );

      core.addColorStop(
        0.18,
        rgba(
          LAVENDER,
          0.6 *
            profile.brightness,
        ),
      );

      core.addColorStop(
        0.45,
        rgba(
          PURPLE,
          0.15 *
            profile.brightness,
        ),
      );

      core.addColorStop(
        1,
        rgba(
          PURPLE,
          0,
        ),
      );

      ctx.fillStyle =
        core;

      ctx.beginPath();

      ctx.arc(
        coreX,
        coreY,
        coreRadius * 4,
        0,
        Math.PI * 2,
      );

      ctx.fill();

      /*
       * ----------------------------------------------------------
       * Speaking-only outer breath
       * ----------------------------------------------------------
       */

      if (
        currentState ===
        'speaking'
      ) {
        const pulse =
          0.5 +
          0.5 *
            Math.sin(
              t * 2.2,
            );

        const outer =
          Math.min(
            width,
            height,
          ) *
          (
            0.32 +
            pulse * 0.035
          );

        const outerGlow =
          ctx.createRadialGradient(
            cx,
            height * 0.48,
            outer * 0.55,
            cx,
            height * 0.48,
            outer,
          );

        outerGlow.addColorStop(
          0,
          rgba(
            PURPLE,
            0,
          ),
        );

        outerGlow.addColorStop(
          0.72,
          rgba(
            PINK,
            0.012,
          ),
        );

        outerGlow.addColorStop(
          1,
          rgba(
            PURPLE,
            0,
          ),
        );

        ctx.fillStyle =
          outerGlow;

        ctx.beginPath();

        ctx.arc(
          cx,
          height * 0.48,
          outer,
          0,
          Math.PI * 2,
        );

        ctx.fill();
      }

      raf =
        requestAnimationFrame(
          render,
        );
    };

    raf =
      requestAnimationFrame(
        render,
      );

    return () => {
      cancelAnimationFrame(
        raf,
      );

      observer.disconnect();
    };
  }, []);

  return (
    <div
      className="
        flex
        h-[340px]
        w-[340px]
        items-center
        justify-center
      "
    >
      <canvas
        ref={canvasRef}
        className="
          block
          h-full
          w-full
        "
        aria-hidden="true"
      />
    </div>
  );
}