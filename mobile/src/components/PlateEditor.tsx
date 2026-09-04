import { useEffect, useRef, useState } from 'react';
import { getPlateAlphabet } from '@/services/api';
import type * as W from '@/services/wire';
import { useAsync } from '@/app/useAsync';

/** Arabic-Indic digits, as they appear on the car. */
const AR_DIGITS = '٠١٢٣٤٥٦٧٨٩';

const toArabicDigit = (ascii: string) =>
  /[0-9]/.test(ascii) ? AR_DIGITS[Number(ascii)] : ascii;

const toAsciiDigit = (ch: string) => {
  const i = AR_DIGITS.indexOf(ch);
  return i >= 0 ? String(i) : ch;
};

/** An Egyptian plate splits into letters and a number, and they are edited
 *  separately because they are different alphabets with different keyboards. */
function split(canonical: string): { letters: string[]; digits: string[] } {
  const [letters = '', digits = ''] = canonical.split(' ');
  return { letters: [...letters], digits: [...digits] };
}

const EMPTY_ALPHABET: W.PlateAlphabet = {
  letters: [], commonLetters: [], digits: [], confusions: {},
};

/** One character of the plate.
 *
 *  Typing replaces whatever was there and moves on, so fixing a plate is the
 *  same number of keystrokes as the number of wrong characters — usually one.
 *  Backspace on an empty box steps back, which is what every other
 *  character-at-a-time field on earth does.
 */
function Cell({ value, isDigit, focused, onChange, onStep, onRemove, inputRef }: {
  value: string;
  isDigit: boolean;
  focused: boolean;
  onChange: (next: string) => void;
  onStep: (delta: number) => void;
  onRemove: () => void;
  inputRef: (el: HTMLInputElement | null) => void;
}) {
  return (
    <input
      ref={inputRef}
      value={isDigit ? toArabicDigit(value) : value}
      inputMode={isDigit ? 'numeric' : 'text'}
      aria-label={isDigit ? 'digit' : 'letter'}
      onChange={(e) => {
        // Take the last character typed, not the whole field: overtyping a
        // filled box should replace it rather than refuse the keystroke.
        const typed = [...e.target.value].pop() ?? '';
        onChange(isDigit ? toAsciiDigit(typed) : typed);
      }}
      onKeyDown={(e) => {
        if (e.key === 'Backspace' && !value) { e.preventDefault(); onStep(-1); }
        else if (e.key === 'ArrowLeft') { e.preventDefault(); onStep(-1); }
        else if (e.key === 'ArrowRight') { e.preventDefault(); onStep(1); }
        else if (e.key === 'Delete') { e.preventDefault(); onRemove(); }
      }}
      onFocus={(e) => e.target.select()}
      style={{
        width: 30, height: 38, textAlign: 'center', padding: 0,
        // Fixed dark-on-white, like the plate itself and for the same reason:
        // this is a picture of what is on the car, not a themed control.
        background: '#fff', color: '#1f2b26',
        border: `2px solid ${focused ? 'var(--ac)' : '#b9c4cf'}`,
        borderRadius: 4, outline: 'none',
        fontFamily: "'Noto Sans Arabic', sans-serif",
        fontSize: 17, fontWeight: 700,
      }}
    />
  );
}

/** Type in a plate, one character at a time.
 *
 *  **Built around what actually goes wrong.** The reader is almost never
 *  wholly wrong — it gets the shape of the plate right and one character
 *  looks like another. So the boxes arrive pre-filled with exactly what was
 *  read, the count is already correct, and fixing it is one keystroke in one
 *  box. Nobody has to say how many letters or digits there are first.
 *
 *  **And the likely fixes are offered.** `confusions` comes from the engine
 *  and is measured: it is the list of characters this character model has
 *  actually been seen to return for one another — `ب` for `ت`, `٦` for `٥`,
 *  `ع` for `٤`. Focus a box and its genuine alternatives are one tap away.
 *  On a phone at a gate that is the difference between usable and not.
 *
 *  Adding or removing a character is possible but deliberately secondary: it
 *  is the rarer mistake, so it does not get the prominent controls.
 */
export function PlateEditor({ plate, onSave, onCancel, busy }: {
  /** Canonical, as the engine stores it: `"بجد 1234"`. */
  plate: string;
  onSave: (canonical: string) => void;
  onCancel: () => void;
  busy?: boolean;
}) {
  const initial = split(plate);
  const [letters, setLetters] = useState(initial.letters);
  const [digits, setDigits] = useState(initial.digits);
  const [at, setAt] = useState(0);

  const { data: alphabet } = useAsync(
    () => getPlateAlphabet(), [], EMPTY_ALPHABET);

  const cells = [...letters.map((c) => ({ c, digit: false })),
                 ...digits.map((c) => ({ c, digit: true }))];
  const boxes = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    boxes.current[at]?.focus();
  }, [at]);

  function setAtIndex(index: number, next: string) {
    if (index < letters.length) {
      const copy = [...letters];
      copy[index] = next;
      setLetters(copy);
    } else {
      const copy = [...digits];
      copy[index - letters.length] = next;
      setDigits(copy);
    }
  }

  function typeInto(index: number, next: string) {
    if (!next) return;
    setAtIndex(index, next);
    // Straight on to the next box: a plate is typed left to right whichever
    // alphabet it is in, and stopping to click each box is the thing that
    // makes character grids miserable.
    if (index + 1 < cells.length) setAt(index + 1);
  }

  function removeAt(index: number) {
    if (index < letters.length) {
      setLetters(letters.filter((_, i) => i !== index));
    } else {
      setDigits(digits.filter((_, i) => i !== index - letters.length));
    }
    setAt(Math.max(0, index - 1));
  }

  const current = cells[at];
  const suggestions = current
    ? (alphabet.confusions[current.c] ?? []).filter(
      (s) => /[0-9]/.test(s) === current.digit)
    : [];

  const canonical = `${letters.join('')} ${digits.join('')}`.trim();
  const usable = letters.length > 0 || digits.length > 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        {/* Letters, right to left as they read on the car. */}
        <div style={{ display: 'flex', gap: 4, direction: 'rtl', unicodeBidi: 'isolate' }}>
          {letters.map((c, i) => (
            <Cell
              key={`l${i}`}
              value={c}
              isDigit={false}
              focused={at === i}
              inputRef={(el) => { boxes.current[i] = el; }}
              onChange={(next) => typeInto(i, next)}
              onStep={(d) => setAt(Math.min(Math.max(at + d, 0), cells.length - 1))}
              onRemove={() => removeAt(i)}
            />
          ))}
          <button
            type="button"
            className="linkbtn"
            title="one more letter"
            onClick={() => { setLetters([...letters, '']); setAt(letters.length); }}
            style={{ fontSize: 18, color: 'var(--tx3)', padding: '0 4px' }}
          >
            +
          </button>
        </div>

        {/* The number, left to right, exactly as printed. */}
        <div style={{ display: 'flex', gap: 4 }}>
          {digits.map((c, i) => (
            <Cell
              key={`d${i}`}
              value={c}
              isDigit
              focused={at === letters.length + i}
              inputRef={(el) => { boxes.current[letters.length + i] = el; }}
              onChange={(next) => typeInto(letters.length + i, next)}
              onStep={(d) => setAt(Math.min(Math.max(at + d, 0), cells.length - 1))}
              onRemove={() => removeAt(letters.length + i)}
            />
          ))}
          <button
            type="button"
            className="linkbtn"
            title="one more digit"
            onClick={() => { setDigits([...digits, '']); setAt(cells.length); }}
            style={{ fontSize: 18, color: 'var(--tx3)', padding: '0 4px' }}
          >
            +
          </button>
        </div>
      </div>

      {/* The characters this reader is measured to confuse with the one being
          edited. Usually the fix is right here and is a single tap. */}
      {suggestions.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 11.5, color: 'var(--tx3)' }}>
            often confused with
          </span>
          {suggestions.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => typeInto(at, s)}
              style={{
                minWidth: 28, height: 28, borderRadius: 6, cursor: 'pointer',
                border: '1px solid var(--line)', background: 'var(--card)',
                color: 'var(--tx)', fontWeight: 700, fontSize: 15,
                fontFamily: "'Noto Sans Arabic', sans-serif",
              }}
            >
              {current?.digit ? toArabicDigit(s) : s}
            </button>
          ))}
        </div>
      )}

      <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
        <button
          type="button"
          className="chip-btn chip-btn--on"
          disabled={busy || !usable}
          onClick={() => onSave(canonical)}
          style={{ padding: '6px 14px', borderRadius: 8, fontSize: 13 }}
        >
          {busy ? 'Saving…' : 'Save'}
        </button>
        <button type="button" className="linkbtn" onClick={onCancel}>
          Cancel
        </button>
        {!usable && (
          <span style={{ fontSize: 12, color: 'var(--am)' }}>
            A plate needs at least one character.
          </span>
        )}
      </div>
    </div>
  );
}
