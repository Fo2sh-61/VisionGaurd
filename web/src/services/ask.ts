/** The "ask in plain words" router.
 *
 *  Today: keyword matching, exactly as the design prototype did.
 *  Later: this is the natural home for an LLM intent call — keep the signature
 *  (`string -> AskOutcome`) and the Home page needs no changes. */

import type { Role, ToolId } from '@/types';

export type AskOutcome =
  | { kind: 'route'; tool: ToolId }
  | { kind: 'note'; message: string }
  | { kind: 'ignore' };

const INTENTS: { keywords: string[]; tool: ToolId }[] = [
  {
    keywords: ['absent', 'attendance', 'present', 'arrive', 'late', 'who came'],
    tool: 'attendance',
  },
  { keywords: ['how many', 'count', 'busy', 'crowd', 'occupancy'], tool: 'counting' },
  { keywords: ['intrusion', 'restricted', 'breach', 'entered', 'forbidden'], tool: 'intrusion' },
  { keywords: ['weapon', 'gun', 'knife', 'armed'], tool: 'weapons' },
  {
    keywords: ['lost', 'missing', 'left behind', 'backpack', 'bag', 'phone', 'jacket', 'laptop'],
    tool: 'lost-items',
  },
  { keywords: ['track', 'where did', 'path', 'follow', 'went', 'movement'], tool: 'track' },
  { keywords: ['camera offline', 'server', 'gpu', 'system', 'recorder'], tool: 'system' },
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

  return {
    kind: 'note',
    message: 'I could not match that to a tool yet — try one of the examples below.',
  };
}
