import { HOME_ICON, iconFor } from '@/app/navigation';
import type { ToolId } from '@/types';

/** The phone's stroked icons, 18 x 18, in the console's hand.
 *
 *  Tool icons are not repeated here: they come from `NAV` in the shared
 *  `app/navigation.ts`, so the phone and the console cannot draw a tool with
 *  two different pictures. These are only the phone's own chrome. */
const PATHS = {
  home: HOME_ICON,
  camera: 'M2.5 5.5 H11.5 V12.5 H2.5 Z M11.5 7.8 L15.5 5.5 V12.5 L11.5 10.2',
  tools: 'M3 3 H8 V8 H3 Z M10 3 H15 V8 H10 Z M3 10 H8 V15 H3 Z M10 10 H15 V15 H10 Z',
  people:
    'M6.2 3.5 a2.3 2.3 0 1 0 0.01 0 M2.8 14.5 c0-2.6 1.7-4 3.4-4 s3.4 1.4 3.4 4 M12.3 5.5 a2 2 0 1 0 0.01 0 M11.5 11.3 c1.9 .3 3.4 1.5 3.4 3.2',
  more: 'M4 9 a.9 .9 0 1 0 .01 0 M9 9 a.9 .9 0 1 0 .01 0 M14 9 a.9 .9 0 1 0 .01 0',
  bell:
    'M9 2.9c-2.5 0-4.3 1.9-4.3 4.4v3.1l-1.4 2.2h11.4l-1.4-2.2V7.3c0-2.5-1.8-4.4-4.3-4.4z M7.4 14.7c.3.8.9 1.2 1.6 1.2s1.3-.4 1.6-1.2',
  back: 'M11 3.5 L5.5 9 L11 14.5',
  chevron: 'M7 4 L12 9 L7 14',
  down: 'M5 7 L9 11 L13 7',
  search: 'M7.5 3 a4.5 4.5 0 1 0 0.01 0 M11 11 L15 15',
  plus: 'M9 3.5 V14.5 M3.5 9 H14.5',
  export: 'M9 3 V11 M5.5 7.5 L9 11 L12.5 7.5 M3.5 13 V15 H14.5 V13',
  check: 'M3.5 9.5 L7.5 13.5 L14.5 5',
  warn: 'M9 2.8 L16 15 H2 Z M9 7.5 V10.5 M9 12.6 V12.7',
  clock: 'M9 2.5 a6.5 6.5 0 1 0 .01 0 M9 5.5 V9 L11.5 10.5',
  shield: 'M9 2.5 L14.5 4.5 V9 C14.5 12.5 12 14.8 9 15.5 C6 14.8 3.5 12.5 3.5 9 V4.5 Z',
  logout: 'M7 3.5 H3.5 V14.5 H7 M10.5 5.5 L14 9 L10.5 12.5 M14 9 H6.5',
  user: 'M9 3.5 a2.5 2.5 0 1 0 .01 0 M4 15 c0-3 2.2-4.5 5-4.5 s5 1.5 5 4.5',
  globe:
    'M9 2.5 a6.5 6.5 0 1 0 .01 0 M2.5 9 H15.5 M9 2.5 C6.5 5 6.5 13 9 15.5 C11.5 13 11.5 5 9 2.5',
  moon: 'M13.5 11 A5.5 5.5 0 0 1 7 4.5 A5.5 5.5 0 1 0 13.5 11 Z',
  system: 'M2.5 9.5 H6 L8 5 L10.5 13 L12.5 9.5 H15.5',
  settings:
    'M3 6.2 H15 M3 11.8 H15 M7 4.6 a1.6 1.6 0 1 0 0.01 0 M11.5 10.2 a1.6 1.6 0 1 0 0.01 0',
  play: 'M5.5 3.5 L14 9 L5.5 14.5 Z',
  close: 'M4.5 4.5 L13.5 13.5 M13.5 4.5 L4.5 13.5',
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({
  name,
  tool,
  size = 20,
  strokeWidth = 1.7,
  mirror = false,
}: {
  name?: IconName;
  /** A tool's own icon, from the shared navigation table. */
  tool?: ToolId;
  size?: number;
  strokeWidth?: number;
  /** Arrows that mean "back" or "forward" point the other way in Arabic. */
  mirror?: boolean;
}) {
  const d = tool ? iconFor(tool) : name ? PATHS[name] : '';
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 18 18"
      fill="none"
      aria-hidden="true"
      className={mirror ? 'mirror-rtl' : undefined}
      style={{ flexShrink: 0 }}
    >
      <path d={d} stroke="currentColor" strokeWidth={strokeWidth}
            strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
