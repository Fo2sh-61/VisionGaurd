import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';

/** Home hands off with `{ autoRun: true }` so a question like "who was absent
 *  today?" lands on a page that has already run itself, not an empty form.
 *
 *  Fires once per arrival; after that the page's own Show/Search button drives it. */
export function useAutoRun(run: () => void) {
  const location = useLocation();
  const requested = (location.state as { autoRun?: boolean } | null)?.autoRun === true;
  const done = useRef(false);

  useEffect(() => {
    if (requested && !done.current) {
      done.current = true;
      run();
    }
  }, [requested, run]);
}
