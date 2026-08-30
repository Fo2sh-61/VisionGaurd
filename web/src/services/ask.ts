/** The "ask in plain words" router.
 *
 *  Today: keyword matching, exactly as the design prototype did.
 *  Later: this is the natural home for an LLM intent call — keep the signature
 *  (`string -> AskOutcome`) and the Home page needs no changes.
 *
 *  Both languages, because a bar that only understands English is not usable
 *  by the people this console is for. The Arabic keywords below are **drafted
 *  and not yet reviewed** — they are matching data rather than wording, so
 *  they do not live in `i18n/ar.draft.ts` and are not counted by the coverage
 *  card. They need the same read-through by a native speaker before release. */

import type { MessageKey } from '@/i18n';
import type { Role, ToolId } from '@/types';

export type AskOutcome =
  | { kind: 'route'; tool: ToolId }
  /** A key, not a sentence — Home says it in whichever language is active. */
  | { kind: 'note'; message: MessageKey }
  | { kind: 'ignore' };

const INTENTS: { keywords: string[]; tool: ToolId }[] = [
  {
    keywords: [
      'absent', 'attendance', 'present', 'arrive', 'late', 'who came',
      'غائب', 'غياب', 'الحضور', 'حضر', 'متأخر', 'تأخر',
    ],
    tool: 'attendance',
  },
  {
    keywords: [
      'how many', 'count', 'busy', 'crowd', 'occupancy',
      'كم', 'عدد', 'ازدحام', 'مزدحم', 'مكتظ',
    ],
    tool: 'counting',
  },
  {
    keywords: [
      'intrusion', 'restricted', 'breach', 'entered', 'forbidden',
      'محظور', 'ممنوع', 'اقتحام', 'تسلل', 'دخل',
    ],
    tool: 'intrusion',
  },
  {
    keywords: ['weapon', 'gun', 'knife', 'armed', 'سكين', 'سلاح', 'مسدس'],
    tool: 'weapons',
  },
  {
    keywords: [
      'lost', 'missing', 'left behind', 'backpack', 'bag', 'phone', 'jacket', 'laptop',
      'مفقود', 'ضاع', 'حقيبة', 'شنطة', 'هاتف', 'جاكيت', 'لابتوب',
    ],
    tool: 'lost-items',
  },
  {
    keywords: [
      'track', 'where did', 'path', 'follow', 'went', 'movement',
      'تتبع', 'أين', 'اين', 'مسار', 'ذهب', 'تحرك',
    ],
    tool: 'track',
  },
  {
    keywords: [
      'camera offline', 'server', 'gpu', 'system', 'recorder',
      'كاميرا', 'الخادم', 'النظام', 'مسجل',
    ],
    tool: 'system',
  },
];

/** `role` is unused today — every tool in the design is open to both roles —
 *  but it stays in the signature because an LLM intent call will want it. */
export async function ask(question: string, role: Role): Promise<AskOutcome> {
  void role;
  const q = question.trim().toLowerCase();
  if (!q) return { kind: 'ignore' };

  for (const intent of INTENTS) {
    if (intent.keywords.some((k) => q.includes(k))) return { kind: 'route', tool: intent.tool };
  }

  return { kind: 'note', message: 'ask.noMatch' };
}
