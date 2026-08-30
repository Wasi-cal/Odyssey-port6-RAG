'use client';

interface LiquidSphereProps {
  /** CSS size value, e.g. '64px' or 'min(240px, 40vw)'. */
  size: string;
  /** True while voiceStatus is 'listening' | 'speaking' -- speeds up the swirl and brightens the glow. */
  active?: boolean;
  onClick?: () => void;
  title?: string;
}

/**
 * CSS approximation of the reference's glossy, liquid-chrome sphere --
 * layered radial gradients (base sheen + a rotating, off-center "swirl"
 * blob blended on top) plus a soft outer glow, in place of a literal
 * ray-traced render. Deliberately NOT the old pixel-grid Orb.tsx approach
 * (retired -- see redesign brief) and not a flat single-tone gradient
 * circle either.
 */
export function LiquidSphere({ size, active = false, onClick, title }: LiquidSphereProps) {
  return (
    <div
      onClick={onClick}
      title={title}
      className="relative flex items-center justify-center"
      style={{ width: size, height: size, cursor: onClick ? 'pointer' : undefined }}
    >
      {/* Outer glow halo */}
      <div
        className="absolute rounded-full transition-opacity duration-500"
        style={{
          inset: '-18%',
          background: 'radial-gradient(circle, rgba(94,234,212,0.45), transparent 70%)',
          filter: 'blur(24px)',
          opacity: active ? 1 : 0.65,
        }}
      />
      {/* Sphere base -- glassy sheen, darker at the rim for volume */}
      <div
        className="absolute rounded-full overflow-hidden"
        style={{
          inset: 0,
          background:
            'radial-gradient(circle at 32% 28%, #E8FFFA 0%, #9FEFE0 18%, #3FBBA8 46%, #145048 78%, #05201C 100%)',
          boxShadow: 'inset 0 0 30px rgba(0,0,0,0.5), 0 0 40px rgba(63,187,168,0.35)',
        }}
      >
        {/* Rotating swirl blend -- suggests internal liquid movement */}
        <div
          className={`absolute ${active ? 'animate-[spin_6s_linear_infinite]' : 'animate-[spin_22s_linear_infinite]'}`}
          style={{
            inset: '-30%',
            background:
              'conic-gradient(from 90deg at 50% 50%, transparent 0deg, rgba(255,255,255,0.55) 40deg, transparent 90deg, transparent 200deg, rgba(20,80,72,0.6) 250deg, transparent 300deg)',
            mixBlendMode: 'overlay',
          }}
        />
        {/* Static highlight -- the "glossy" specular hotspot */}
        <div
          className="absolute rounded-full"
          style={{
            top: '14%',
            left: '20%',
            width: '30%',
            height: '20%',
            background: 'radial-gradient(circle, rgba(255,255,255,0.9), transparent 70%)',
            filter: 'blur(2px)',
          }}
        />
      </div>
    </div>
  );
}
