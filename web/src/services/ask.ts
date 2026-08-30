/** The "ask in plain words" router.
 *
 *  **This was keyword matching, and it is now the engine's `/ask`.** Its own
 *  note said so: *"Later: this is the natural home for an LLM intent call —
 *  keep the signature (`string -> AskOutcome`) and the Home page needs no
 *  changes."* The signature is kept and the Home page changed only in what it
 *  does with a route: it now carries the parameters.
 *
 *  The difference that matters is not the model. Keywords could tell you the
 *  question was about tracking; nothing could tell you it was about **Mohamed**,
 *  so the bar opened Track a Person empty and left you to type the name you had
 *  just typed. The engine resolves the person, the day and the place, and the
 *  page opens with the query already run.
 *
 *  Everything the engine sends is a code or a value. No sentence crosses this
 *  file — `Home` words the outcome through `i18n`, in whichever language is on. */

import { ask as askEngine } from '@/services/api';
import type * as W from '@/services/wire';
import type { MessageKey } from '@/i18n';
import type { Role } from '@/types';

export type AskOutcome =
  /** Go here, with these parameters already applied, and run it. */
  | { kind: 'route'; to: string; answer: W.AskAnswer }
  /** A key, not a sentence — Home says it in whichever language is active. */
  | { kind: 'note'; message: MessageKey; args?: Record<string, string | number> }
  | { kind: 'ignore' };

/** `role` is unused: the engine decides what this account may read, from the
 *  session, and the menu is restricted to what the weakest role can already
 *  see. Deciding it here would be a second place where a role is decided. */
export async function ask(question: string, role: Role): Promise<AskOutcome> {
  void role;
  if (!question.trim()) return { kind: 'ignore' };

  let answer: W.AskAnswer;
  try {
    answer = await askEngine(question);
  } catch {
    // The endpoint answers 200 for every degradation it knows about, so
    // reaching here means the engine itself is unreachable — a different
    // thing from "Ask is unavailable", and it must not be dressed up as one.
    return { kind: 'note', message: 'ask.engineUnreachable' };
  }

  // A note always wins the message slot: it is the engine explaining itself,
  // and it is more specific than anything this file could say.
  if (answer.note) {
    return {
      kind: 'note',
      message: `note.${answer.note.code}` as MessageKey,
      args: answer.note.args,
    };
  }

  if (answer.outcome === 'answered' && answer.deepLink) {
    return { kind: 'route', to: answer.deepLink, answer };
  }

  return { kind: 'note', message: 'ask.noMatch' };
}
