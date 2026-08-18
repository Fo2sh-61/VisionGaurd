import type { ReactNode } from 'react';
import type { Stat, Tone } from '@/types';

export const toneColors: Record<Tone, { bg: string; fg: string }> = {
  good: { bg: 'var(--chip)', fg: 'var(--ac2)' },
  warn: { bg: 'var(--am-bg)', fg: 'var(--am)' },
  bad: { bg: 'var(--rd-bg)', fg: 'var(--rd)' },
  neutral: { bg: 'var(--bg)', fg: 'var(--tx2)' },
};

export function Badge({ tone, children, icon }: { tone: Tone; children: ReactNode; icon?: string }) {
  const { bg, fg } = toneColors[tone];
  return (
    <span
      className="badge"
      style={{
        background: bg,
        color: fg,
        display: icon ? 'inline-flex' : 'inline-block',
        alignItems: 'center',
        gap: 6,
      }}
    >
      {icon && (
        <span
          aria-hidden="true"
          style={{
            width: 15,
            height: 15,
            borderRadius: '50%',
            background: fg,
            color: bg,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 10,
            fontWeight: 800,
            lineHeight: 1,
            flexShrink: 0,
          }}
        >
          {icon}
        </span>
      )}
      {children}
    </span>
  );
}

/** Tone → the leading character the design uses for that state. */
export const toneGlyph: Record<Tone, string> = {
  good: '✓',
  warn: '!',
  bad: '✕',
  neutral: '·',
};

/** Home's "Campus today" tiles — card-coloured with a shadow, unlike the
 *  inset `Stats` tiles used inside a tool's answer card. */
export function HomeStats({ items }: { items: Stat[] }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
      {items.map((s) => (
        <div
          key={s.label}
          style={{ background: 'var(--card)', borderRadius: 14, padding: '14px 16px', boxShadow: 'var(--sh)' }}
        >
          <div style={{ fontSize: 12, color: 'var(--tx2)' }}>{s.label}</div>
          <div style={{ fontSize: 24, fontWeight: 700, letterSpacing: '-.02em' }}>{s.value}</div>
        </div>
      ))}
    </div>
  );
}

export function Card({
  children,
  large,
  dashed,
}: {
  children: ReactNode;
  large?: boolean;
  dashed?: boolean;
}) {
  const classes = ['card', large && 'card--lg', dashed && 'card--dashed'].filter(Boolean).join(' ');
  return <div className={classes}>{children}</div>;
}

export function Stats({ items }: { items: Stat[] }) {
  return (
    <div className="stats2">
      {items.map((s) => (
        <div className="stat" key={s.label}>
          <div className="stat__label">{s.label}</div>
          <div className="stat__value">{s.value}</div>
        </div>
      ))}
    </div>
  );
}

export function Toggle({ on, onToggle, label }: { on: boolean; onToggle: () => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      className="toggle"
      onClick={onToggle}
      style={{ background: on ? 'var(--ac)' : 'var(--toggle-off)' }}
    >
      <span className="toggle__knob" style={{ left: on ? 20 : 2 }} />
    </button>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}
