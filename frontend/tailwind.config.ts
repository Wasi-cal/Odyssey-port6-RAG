import type { Config } from 'tailwindcss';

// Colors are used as raw hex via Tailwind's arbitrary-value syntax
// (e.g. bg-[#161C13]) directly at each usage site rather than as named
// theme tokens, so each component's palette stays visible at the call
// site -- see the redesign brief for the reference (dark near-black +
// green radial glow, lime-green accent) this palette is drawn from.
const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        serif: ['var(--font-instrument-serif)', 'serif'],
        sans: ['var(--font-manrope)', 'sans-serif'],
      },
      keyframes: {
        breathe: {
          '0%, 100%': { transform: 'scale(1)' },
          '50%': { transform: 'scale(1.05)' },
        },
        fadeInUp: {
          from: { opacity: '0', transform: 'translateY(8px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        fadeIn: {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
      },
      animation: {
        breathe: 'breathe 3.4s ease-in-out infinite',
        fadeInUp: 'fadeInUp 0.35s ease',
        fadeIn: 'fadeIn 0.3s ease',
      },
    },
  },
  plugins: [],
};

export default config;
