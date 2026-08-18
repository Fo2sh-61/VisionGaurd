/** The "ask in plain words" router — same pattern as the web console's
 *  services/ask.ts, trimmed to the tools the mobile Home screen offers. */

import type { ToolId } from '@/types';

export type AskOutcome = { kind: 'route'; tool: ToolId } | { kind: 'note'; message: string } | { kind: 'ignore' };

const INTENTS: { keywords: string[]; tool: ToolId }[] = [
  { keywords: ['absent', 'attendance', 'present', 'arrive', 'late'], tool: 'attend' },
  { keywords: ['how many', 'count', 'busy', 'crowd'], tool: 'count' },
  { keywords: ['intrusion', 'restricted', 'breach'], tool: 'intrude' },
  { keywords: ['weapon', 'knife', 'gun'], tool: 'weapon' },
  { keywords: ['lost', 'backpack', 'bag', 'phone', 'jacket', 'laptop', 'missing'], tool: 'lost' },
  { keywords: ['track', 'where did', 'went', 'path'], tool: 'track' },
];

export function ask(question: string): AskOutcome {
  const q = question.trim().toLowerCase();
  if (!q) return { kind: 'ignore' };

  for (const intent of INTENTS) {
    if (intent.keywords.some((k) => q.includes(k))) return { kind: 'route', tool: intent.tool };
  }

  return { kind: 'note', message: 'I didn’t catch that — try one of the suggestions, or pick a tool.' };
}
