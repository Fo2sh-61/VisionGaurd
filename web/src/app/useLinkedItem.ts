/** The one item a link asked a page to show - `/weapons?entry=…`, from the
 *  alert bell or Home's list.
 *
 *  A page puts `ref` on the element that shows the named item and draws it
 *  with `LINKED_STYLE`. The first time that element appears it is scrolled
 *  into view - once per visit, so a list that refreshes every few seconds
 *  does not keep dragging the reader back while they read further down. A
 *  second click on the same alert is a new visit, so it scrolls again.
 *
 *  When the item is not there once the list has loaded, the page says so in
 *  its own words. A link that lands on nothing, silently, reads as broken. */

import { useCallback, useRef, type CSSProperties } from 'react';
import { useLocation, useSearchParams } from 'react-router-dom';

export interface LinkedItem {
  /** The id the link named, or null when the page was opened plainly. */
  id: string | null;
  /** Put on the element that shows the named item. */
  ref: (element: HTMLElement | null) => void;
}

/** The accent outline CamGrid already gives its chosen camera, so "this one"
 *  looks the same wherever it is drawn. Set well clear of the row: table rows
 *  have no side padding, and an outline on the box would touch the text. An
 *  outline takes no space, so the rows around it do not move. */
export const LINKED_STYLE: CSSProperties = {
  outline: '2px solid var(--ac)',
  outlineOffset: 6,
  borderRadius: 'var(--radius-md)',
};

/** How long the item is kept in view while the page finishes arriving. */
const SETTLE_MS = 3_000;

/** Centre the element, and keep it centred while the page is still loading
 *  around it. Scrolling once is not enough: on System Health the camera list
 *  above the grid lands after the grid does and pushed the linked camera
 *  800px back off the screen, and the browser's own scroll anchoring does not
 *  help when what grows is the section at the top of the view.
 *
 *  Stops after a few seconds, and at once when the reader scrolls, presses a
 *  key or clicks - after that, where they are is their choice. Instant rather
 *  than smooth, so it never aims at where the row used to be. */
function holdInView(element: HTMLElement): void {
  const centre = () => {
    if (element.isConnected) element.scrollIntoView({ block: 'center' });
  };
  const observer = new ResizeObserver(centre);
  const stop = () => {
    observer.disconnect();
    window.clearTimeout(timer);
    for (const type of ['wheel', 'touchmove', 'keydown', 'pointerdown'] as const) {
      window.removeEventListener(type, stop);
    }
  };
  const timer = window.setTimeout(stop, SETTLE_MS);
  for (const type of ['wheel', 'touchmove', 'keydown', 'pointerdown'] as const) {
    window.addEventListener(type, stop, { passive: true });
  }
  centre();
  // The page grows as each of its lists arrives; every growth re-centres.
  observer.observe(document.body);
}

export function useLinkedItem(param: string): LinkedItem {
  const [params] = useSearchParams();
  const { key } = useLocation();
  const id = params.get(param);
  const scrolledFor = useRef<string | null>(null);

  const ref = useCallback((element: HTMLElement | null) => {
    if (!element || !id || scrolledFor.current === key) return;
    scrolledFor.current = key;
    holdInView(element);
  }, [id, key]);

  return { id, ref };
}
