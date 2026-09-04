/** The mark: a rounded square with a single "lens" notch cut out of one corner. */
export function Logo({ size = 28 }: { size?: number }) {
  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: size * 0.32,
        background: 'var(--ac)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
      }}
    >
      <div
        style={{
          width: size * 0.43,
          height: size * 0.43,
          borderRadius: '50% 50% 50% 4px',
          background: 'var(--panel)',
        }}
      />
    </div>
  );
}
