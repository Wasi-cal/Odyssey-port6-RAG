// App background -- two soft radial washes (pink + violet) over a near-white
// base, per the HR Chatbot design handoff's "Background gradient" token.
export function GradientBackdrop() {
  return (
    <div
      className="pointer-events-none absolute inset-0 z-0"
      style={{
        background:
          'radial-gradient(ellipse 60% 55% at 18% 78%, rgba(250,205,232,0.85) 0%, rgba(250,205,232,0) 68%), ' +
          'radial-gradient(ellipse 55% 50% at 78% 26%, rgba(210,198,245,0.85) 0%, rgba(210,198,245,0) 68%), ' +
          '#f7f4fb',
      }}
    />
  );
}
