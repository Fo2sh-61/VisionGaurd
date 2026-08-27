/** An Egyptian number plate, drawn as it appears on the car.
 *
 *  Extracted rather than inlined because the design file repeats this markup
 *  five times across three tabs, and five copies of a right-to-left rule are
 *  five chances for one of them to drift into rendering a plate backwards.
 *
 *  Three details that are not decoration:
 *
 *  - `direction: rtl` with `unicodeBidi: isolate`. The plate is Arabic letters
 *    beside Western-ordered digits, and without isolation the browser's
 *    bidirectional algorithm reorders them against surrounding English text —
 *    so the same plate renders differently depending on what sits next to it.
 *  - The `مصر · EGYPT` band, because that is what makes it read as a plate
 *    rather than a code. It carries no registration information.
 *  - Fixed dark-on-white colours, deliberately not theme tokens. A real plate
 *    is black on white in both light and dark mode; theming it would make the
 *    console's rendering disagree with the photograph beside it.
 */

import { plateLatin } from '@/services/format';

interface PlateProps {
  /** The display form — Arabic letters, Indic digits. From the engine. */
  display: string;
  /** Smaller variant for dense rows. */
  compact?: boolean;
  /** Show the Latin transliteration underneath.
   *
   *  Off by default and on only in the register table. The guard reads the
   *  Arabic; the Latin line is for an exported report and for searching from
   *  a keyboard that has no Arabic on it. On a dense live row it is noise. */
  latin?: boolean;
}

export function Plate({ display, compact = false, latin = false }: PlateProps) {
  if (!display) {
    // A pass whose plate could not be read still happened, and the row still
    // has to render. An em-dash says "not read" without implying a value.
    return <span style={{ color: 'var(--tx3)', fontSize: 13 }}>—</span>;
  }

  const chip = (
    <span
      style={{
        display: 'inline-flex',
        flexDirection: 'column',
        background: '#fff',
        border: '1.5px solid #2b2f2c',
        borderRadius: 4,
        overflow: 'hidden',
        flexShrink: 0,
      }}
    >
      <span
        style={{
          fontFamily: "'Noto Sans Arabic', sans-serif",
          fontSize: compact ? 6.5 : 7,
          fontWeight: 700,
          color: '#57655d',
          textAlign: 'center',
          lineHeight: 1.6,
          borderBottom: '1px solid #d6ded8',
          letterSpacing: '.05em',
          padding: '0 6px',
        }}
      >
        مصر · EGYPT
      </span>
      <span
        style={{
          fontFamily: "'Noto Sans Arabic', sans-serif",
          fontSize: compact ? 12 : 13.5,
          fontWeight: 700,
          color: '#1f2b26',
          textAlign: 'center',
          padding: compact ? '1px 7px 2px' : '1px 8px 2px',
          direction: 'rtl',
          unicodeBidi: 'isolate',
          letterSpacing: '.05em',
          whiteSpace: 'nowrap',
        }}
      >
        {display}
      </span>
    </span>
  );

  if (!latin) return chip;

  return (
    <span style={{ display: 'inline-block' }}>
      {chip}
      <span style={{
        display: 'block', fontSize: 11, color: 'var(--tx3)', marginTop: 2,
        fontFamily: 'ui-monospace, Menlo, monospace', letterSpacing: '.02em',
      }}>
        {plateLatin(display)}
      </span>
    </span>
  );
}
