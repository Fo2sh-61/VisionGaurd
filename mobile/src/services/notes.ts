/** Turning the engine's `Note` into a sentence.
 *
 *  The engine sends `{ code, args }` and nothing else. Every word comes from
 *  `web/src/i18n/`, which is what lets the same explanation appear in Arabic
 *  without the engine knowing a language exists.
 *
 *  This lives in `services/` rather than `i18n/` on purpose: rendering a wire
 *  type is a service concern, and putting it in `i18n/` would invite the
 *  catalogue to start importing wire types. */

import { isKnownKey, type MessageKey } from '@/i18n';
import type { Translate } from '@/app/LanguageContext';
import type { Note } from '@/services/wire';

/** A note the console does not recognise still has to say something.
 *
 *  Rendering nothing would be worse than useless: a blank claims there is
 *  nothing to explain, when in fact the engine explained and we failed to
 *  listen. So the code itself is shown — an operator can quote it, and it is
 *  visibly a fault in the console rather than in the camera (P11-FR-007). */
export function noteSentence(
  t: Translate,
  note: Note | null | undefined,
): string | null {
  if (!note) return null;
  const key = `note.${note.code}`;
  if (!isKnownKey(key)) return t('notes.unknownCode', { code: note.code });
  return t(key as MessageKey, note.args);
}

/** The same, for the places that want an empty string rather than a null. */
export function noteText(t: Translate, note: Note | null | undefined): string {
  return noteSentence(t, note) ?? '';
}
