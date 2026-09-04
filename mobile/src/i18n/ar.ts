/** Arabic wording that a native speaker has read and approved.
 *
 *  This file is the only Arabic a **release build** will render. Anything not
 *  in here falls back to English, which is honest; rendering Arabic nobody has
 *  checked into a security console is not (P11-FR-004).
 *
 *  Drafts live in `ar.draft.ts` and are reviewed in a development build, then
 *  moved here. Settings shows how many are left.
 *
 *  `Partial` on purpose — an incomplete file is the designed state during
 *  review, not an error. */

import type { MessageKey } from './keys';

export const ar: Partial<Record<MessageKey, string>> = {
  // Nothing approved yet. Move entries here from ar.draft.ts once read.
};
