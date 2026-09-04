/** Turning a key into a sentence.
 *
 *  Deliberately free of React, so `services/format.ts` can use it without
 *  dragging a hook into every formatter. The provider and the hooks live in
 *  `app/LanguageContext.tsx`.
 *
 *  Resolution order, and why:
 *
 *    approved Arabic  ->  drafted Arabic (development only)  ->  English
 *
 *  A release build never renders a wording nobody has read. It shows English
 *  instead, which is honest and obviously unfinished, rather than Arabic that
 *  might say the wrong thing on a security console (P11-FR-004). English is
 *  complete by construction — `en.ts` is typed `Record<MessageKey, string>` —
 *  so the last step can never fail (P11-FR-002). */

import { ar } from './ar';
import { arDraft } from './ar.draft';
import { en } from './en';
import type { Language, MessageKey } from './keys';

export type { Language, MessageKey, NoteCode } from './keys';
export { DIRECTION, LANGUAGES } from './keys';

/** Facts a wording needs — a name, a count, a number of minutes. Never a
 *  phrase: if it would be a phrase, it needs its own key. */
export type MessageArgs = Record<string, string | number>;

/** Drafted Arabic is visible while developing so it can be reviewed in place,
 *  and invisible in a release so it cannot reach a guard unread. */
const DRAFTS_VISIBLE = import.meta.env.DEV;

/** Unicode FIRST STRONG ISOLATE and POP DIRECTIONAL ISOLATE.
 *
 *  Every substituted value is wrapped in these. Without them a Latin value
 *  dropped into an Arabic sentence reorders on screen: a camera called
 *  `cam-hall`, an address like `192.168.1.0/24`, a filename, a plate, a bare
 *  number followed by a full stop. The browser has no way to know where the
 *  value ends and the sentence resumes, so it guesses, and it guesses wrong
 *  at exactly the boundaries that matter.
 *
 *  Isolating here rather than at each call site is the whole point: there are
 *  49 Arabic strings with a value in them and there will be more, and one
 *  forgotten `<bdi>` is a scrambled camera name in front of a guard. */
const FSI = '\u2068';
const PDI = '\u2069';

/** `{name}` -> the arg called `name`, isolated from the text around it.
 *
 *  A placeholder with no arg is left standing rather than blanked. A visible
 *  `{minutes}` reads as broken, which it is; "Arrived  minutes late" reads as
 *  a sentence, which is worse. */
function fill(template: string, args?: MessageArgs): string {
  if (!args) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in args ? `${FSI}${String(args[name])}${PDI}` : whole);
}

/** Is this a key the console knows how to say?
 *
 *  Needed because note codes arrive from the engine as plain strings at
 *  runtime, where the type system has already stopped helping. `en` is
 *  complete, so membership in it is the definition of "known". */
export function isKnownKey(key: string): key is MessageKey {
  return Object.prototype.hasOwnProperty.call(en, key);
}

export function translate(
  lang: Language,
  key: MessageKey,
  args?: MessageArgs,
): string {
  const wording =
    lang === 'ar'
      ? ar[key] ?? (DRAFTS_VISIBLE ? arDraft[key] : undefined) ?? en[key]
      : en[key];
  return fill(wording, args);
}

/** How much Arabic there is, for the card on Settings (P11-FR-003).
 *
 *  Counted from the catalogues themselves, so it cannot drift from reality.
 *  `missing` plus `draft` is how much of the console still reads English to an
 *  Arabic user; `draft` alone is the release gate (SC-005). */
export interface Coverage {
  total: number;
  approved: number;
  draft: number;
  missing: number;
}

export function arabicCoverage(): Coverage {
  const keys = Object.keys(en) as MessageKey[];
  let approved = 0;
  let draft = 0;
  for (const key of keys) {
    if (ar[key] !== undefined) approved += 1;
    else if (arDraft[key] !== undefined) draft += 1;
  }
  return {
    total: keys.length,
    approved,
    draft,
    missing: keys.length - approved - draft,
  };
}
