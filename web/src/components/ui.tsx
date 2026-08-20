import type { ReactNode } from 'react';
import type { Capability } from '@/services/wire';
import type { Stat, Tone } from '@/types';

/** Tone → the pair of tokens the design uses for every status pill. */
export const toneColors: Record<Tone, { bg: string; fg: string }> = {
  good: { bg: 'var(--chip)', fg: 'var(--ac2)' },
  warn: { bg: 'var(--am-bg)', fg: 'var(--am)' },
  bad: { bg: 'var(--rd-bg)', fg: 'var(--rd)' },
  neutral: { bg: 'var(--bg)', fg: 'var(--tx2)' },
};

/** The design leads most status pills with a character — a tick, a bang, a
 *  cross — so the state reads without relying on colour alone. `icon` renders
 *  it in a filled circle (attention cards); `glyph` inlines it (table rows). */
export function Badge({
  tone,
  children,
  icon,
  glyph,
}: {
  tone: Tone;
  children: ReactNode;
  icon?: string;
  glyph?: string;
}) {
  const { bg, fg } = toneColors[tone];
  return (
    <span className={icon ? 'badge badge--dot' : 'badge'} style={{ background: bg, color: fg }}>
      {icon && (
        <span className="glyph" style={{ width: 15, height: 15, fontSize: 10, background: fg, color: bg }}>
          {icon}
        </span>
      )}
      {glyph ? `${glyph} ` : ''}
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

export function Card({
  children,
  tight,
  dashed,
  className = '',
}: {
  children: ReactNode;
  tight?: boolean;
  dashed?: boolean;
  className?: string;
}) {
  const classes = ['card', tight && 'card--tight', dashed && 'card--dashed', className]
    .filter(Boolean)
    .join(' ');
  return <div className={classes}>{children}</div>;
}

export function CardHeader({ title, sub }: { title: string; sub?: string }) {
  return (
    <>
      <div className="card__title">{title}</div>
      {sub && <div className="card__sub">{sub}</div>}
    </>
  );
}

export function PageHeader({ title, lead }: { title: string; lead: string }) {
  return (
    <>
      <h1 className="page__title">{title}</h1>
      <p className="page__lead">{lead}</p>
    </>
  );
}

export function Stats({ items, columns }: { items: Stat[]; columns?: number }) {
  const cols = columns ?? items.length;
  return (
    <div className="stats" style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}>
      {items.map((s) => (
        <div className="stat" key={s.label}>
          <div className="stat__label">{s.label}</div>
          <div className="stat__value">{s.value}</div>
        </div>
      ))}
    </div>
  );
}

export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span className="field__label">{label}</span>
      {children}
    </label>
  );
}

export function Select({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (value: string) => void;
  options: readonly string[];
}) {
  return (
    <select className="input" value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  );
}

export function Toggle({
  on,
  onToggle,
  label,
}: {
  on: boolean;
  onToggle: () => void;
  label: string;
}) {
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
      <span className="toggle__knob" style={{ left: on ? 18 : 2 }} />
    </button>
  );
}

/** Says why a page has nothing to show, instead of leaving it blank.
 *
 *  A blank page and a quiet morning look identical, so this is the difference
 *  between "nobody came" and "nothing was watching". It renders nothing at all
 *  when the capability is live, so a page can mount it unconditionally and
 *  cannot forget to.
 *
 *  Amber, not red: an unbuilt feature is not a fault, and an operator should
 *  not be waiting for it to come back. */
export function DataNotice({ capability }: { capability: Capability | null }) {
  if (!capability || capability.state === 'live') return null;

  const demo = capability.state === 'demo';
  return (
    <div
      role="status"
      style={{
        display: 'flex', gap: 10, alignItems: 'baseline',
        padding: '11px 14px', borderRadius: 10, marginBottom: 14,
        background: 'var(--am-bg)', color: 'var(--am)',
        fontSize: 13.5, lineHeight: 1.45,
      }}
    >
      <span style={{ fontWeight: 700, whiteSpace: 'nowrap' }}>
        {demo ? 'Demo data' : 'Not available'}
      </span>
      <span>{capability.reason ?? `${capability.name} is not available.`}</span>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

/** The request failed. Say so, and offer the one useful action.
 *
 *  Renders nothing when `error` is null, so a page mounts it unconditionally
 *  and cannot forget to — the same reason `DataNotice` works that way.
 *
 *  Red, unlike `DataNotice`'s amber, and the difference is the point. Amber
 *  means "this feature is not built yet, stop waiting for it". Red means
 *  "this should work and right now it does not", which is worth a retry and
 *  possibly worth telling somebody about.
 *
 *  It sits above the data rather than replacing it. A refresh that fails
 *  while an operator is reading a table should not blank the table: what is
 *  on screen was true when it arrived, and removing it says less than
 *  leaving it with a warning attached. */
export function LoadError({
  error,
  onRetry,
  what,
}: {
  error: string | null;
  onRetry?: () => void;
  /** What could not be loaded, e.g. "the register". Used in the sentence. */
  what?: string;
}) {
  if (!error) return null;

  return (
    <div
      role="alert"
      style={{
        display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap',
        padding: '11px 14px', borderRadius: 10, marginBottom: 14,
        background: 'var(--rd-bg)', color: 'var(--rd)',
        fontSize: 13.5, lineHeight: 1.45,
      }}
    >
      <span style={{ fontWeight: 700, whiteSpace: 'nowrap' }}>
        {what ? `Could not load ${what}` : 'Could not load this'}
      </span>
      <span>{error}</span>
      {onRetry && (
        <button
          type="button"
          className="linkbtn"
          onClick={onRetry}
          style={{ color: 'inherit', fontWeight: 600, textDecoration: 'underline' }}
        >
          Try again
        </button>
      )}
    </div>
  );
}

export function StatusDot({ tone, children }: { tone: Tone; children: ReactNode }) {
  const color = toneColors[tone].fg;
  return (
    <span className="dotline" style={{ color }}>
      <span className="dot" style={{ background: color }} />
      {children}
    </span>
  );
}
