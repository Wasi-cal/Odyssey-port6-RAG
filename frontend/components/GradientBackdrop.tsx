// Subtle vertical gradient -- near-black at the top, fading to a
// teal-tinted dark at the bottom. Not a flat black, not a radial glow
// (that was the previous, superseded reference) -- see redesign brief.
export function GradientBackdrop() {
  return (
    <div
      className="pointer-events-none absolute inset-0 z-0"
      style={{ background: 'linear-gradient(180deg, #090D0C 0%, #0A1614 55%, #0D211D 100%)' }}
    />
  );
}
