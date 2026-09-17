/* The phone's vocabulary.
 *
 *  Deliberately **not** on the parity list in `tools/check_parity.py`: this is
 *  presentation, and the phone is allowed its own. But it started as a copy of
 *  `web/src/components/ui.tsx` and stays as close to it as a phone permits,
 *  because two of these components are how the product tells the truth.
 *
 *  `DataNotice` says a feature is demo or absent. `LoadError` says a request
 *  failed. Both render `null` when there is nothing to say, so a page mounts
 *  them unconditionally and *cannot forget to*. A phone version that dropped
 *  either — or quietly returned `null` always — would compile, look fine, and
 *  remove every honesty warning in the app at once. So they are copied exactly,
 *  comments included, and the difference from the console is one function.
 *
 *  What actually differs: `Stats` caps itself at two columns; `Select` opens a
 *  bottom sheet instead of a native dropdown, and takes its sheet's title from
 *  the `Field` around it; `PageHeader` draws only the lead, because the title
 *  is already in the phone's back header; `Toggle` is finger-sized. Everything
 *  else renders semantic class names, and `styles/app.css` does the rest.
 */

import { createContext, useContext, useState, type CSSProperties, type ReactNode } from 'react';
import { useT } from '@/app/LanguageContext';
import { Sheet, SheetOption } from './Sheet';
import type { MessageArgs, MessageKey } from '@/i18n';
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
        <span className="glyph" style={{ width: 17, height: 17, fontSize: 12, background: fg, color: bg }}>
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

/** The title is drawn by the phone's back header (`ScreenHeader`, an `h1`),
 *  from the route table, so a screen's own copy of it would be the same words
 *  twice pushing the answer down. `.page__title` hides this one - from screen
 *  readers too, so there is still exactly one `h1` per screen. */
export function PageHeader({ title, lead }: { title: string; lead: string }) {
  return (
    <>
      <h1 className="page__title">{title}</h1>
      <p className="page__lead">{lead}</p>
    </>
  );
}

/** `columns` is a hint here, not an instruction.
 *
 *  The console asks for four across and gets four. On a 375px screen four
 *  columns is roughly 80px each, which turns "1,679 on campus now" into two
 *  cramped lines. So the phone takes the caller's number and caps it at two —
 *  the figures wrap onto a second row instead of being squeezed onto one.
 *
 *  Capping rather than ignoring: a caller asking for one column means one. */
export function Stats({ items, columns }: { items: Stat[]; columns?: number }) {
  const cols = Math.min(columns ?? items.length, 2);
  return (
    // A custom property, not `gridTemplateColumns` directly. `app.css` folds
    // any element carrying an inline `grid-template-columns` into a stacked
    // row, because a console table's columns cannot survive a 375px screen —
    // and headline figures are the one grid that should stay a grid. Passing
    // the count through `--cols` keeps this one out of that net.
    <div className="stats" style={{ '--cols': cols } as CSSProperties}>
      {items.map((s) => (
        <div className="stat" key={s.label}>
          <div className="stat__label">{s.label}</div>
          <div className="stat__value">{s.value}</div>
        </div>
      ))}
    </div>
  );
}

/** The label a `Select` inside this field should give its sheet. */
const FieldLabel = createContext<string>('');

export function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <FieldLabel.Provider value={label}>
      <label className="field">
        <span className="field__label">{label}</span>
        {children}
      </label>
    </FieldLabel.Provider>
  );
}

export function Select({
  value,
  onChange,
  options,
  label,
}: {
  value: string;
  onChange: (value: string) => void;
  options: readonly string[];
  /** How to say an option, when the value is a token rather than the wording.
   *
   *  Window pickers send `last30` to the engine and show "Last 30 days" or
   *  "آخر ٣٠ يومًا" depending on who is reading. Options that are already
   *  their own wording — a camera name, a group — need nothing here. */
  label?: (option: string) => string;
}) {
  // On a phone a native dropdown is a tiny list in a corner; the sheet is one
  // thumb-sized row per option (P13-FR-050). The props are the console's, so
  // every screen that uses `Select` gets the sheet without an edit.
  const [open, setOpen] = useState(false);
  const title = useContext(FieldLabel);
  const say = (o: string) => (label ? label(o) : o);
  return (
    <>
      <button
        type="button"
        className="input selectbtn"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={(e) => {
          // Inside a <label>, a click on the text would otherwise re-fire here.
          e.preventDefault();
          setOpen(true);
        }}
      >
        <span className="selectbtn__value">{options.includes(value) ? say(value) : value}</span>
        <svg width="16" height="16" viewBox="0 0 18 18" fill="none" aria-hidden="true">
          <path d="M5 7 L9 11 L13 7" stroke="currentColor" strokeWidth="2"
                strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      <Sheet open={open} title={title || say(value)} onClose={() => setOpen(false)}>
        {options.map((o) => (
          <SheetOption
            key={o}
            selected={o === value}
            onSelect={() => {
              onChange(o);
              setOpen(false);
            }}
          >
            {say(o)}
          </SheetOption>
        ))}
      </Sheet>
    </>
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
    >
      {/* The button is the 44 px target; the track inside it is what shows. */}
      <span className="toggle__track" style={{ background: on ? 'var(--ac)' : 'var(--toggle-off)' }}>
        <span className="toggle__knob" style={{ insetInlineStart: on ? 24 : 4 }} />
      </span>
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
  const t = useT();
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
        {t(demo ? 'state.demoData' : 'state.notAvailable')}
      </span>
      <span>
        {capability.reason
          ?? t('state.featureNotAvailable', { feature: capability.name })}
      </span>
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
  whatArgs,
}: {
  error: string | null;
  onRetry?: () => void;
  /** What could not be loaded, as a **key** — `'load.cameraList'`.
   *
   *  A key rather than the words, because it is dropped into the middle of
   *  `state.couldNotLoad`. Passing the English phrase would glue a sentence
   *  together in code, and Arabic does not put the pieces in that order.
   *  P11-FR-001. */
  what?: MessageKey;
  /** Facts the `what` wording needs — a person's name, a group. */
  whatArgs?: MessageArgs;
}) {
  const t = useT();
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
        {what
          ? t('state.couldNotLoad', { what: t(what, whatArgs) })
          : t('state.couldNotLoadThis')}
      </span>
      <span>{error}</span>
      {onRetry && (
        <button
          type="button"
          className="linkbtn"
          onClick={onRetry}
          style={{ color: 'inherit', fontWeight: 600, textDecoration: 'underline' }}
        >
          {t('state.tryAgain')}
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
