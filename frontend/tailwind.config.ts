import type { Config } from 'tailwindcss';

// Colors are used as raw hex via Tailwind's arbitrary-value syntax
// (e.g. bg-[#6d4bb8]) directly at each usage site rather than as named
// theme tokens, so each component's palette stays visible at the call
// site -- see the HR Chatbot design handoff (light purple/pink gradient
// theme, Plus Jakarta Sans) this palette and type scale are drawn from.
const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['var(--font-jakarta)', 'system-ui', '-apple-system', 'sans-serif'],
      },
      keyframes: {
        breathe: {
          '0%, 100%': { transform: 'scale(1)' },
          '50%': { transform: 'scale(1.05)' },
        },
        // Matches the design handoff's `fadeUp` keyframe exactly --
        // translateY(6px) -> 0, opacity 0 -> 1.
        fadeInUp: {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        fadeIn: {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
      },
      animation: {
        breathe: 'breathe 3.4s ease-in-out infinite',
        fadeInUp: 'fadeInUp 0.25s ease',
        fadeIn: 'fadeIn 0.3s ease',
      },
    },
  },
  plugins: [],
};

export default config;
