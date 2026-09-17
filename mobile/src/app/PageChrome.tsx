import {
  createContext, useContext, useEffect, useMemo, useState, type ReactNode,
} from 'react';

/** What a screen may put in the phone's back header: its own title (a camera's
 *  name, a person's name) and a small action on the far side (Export, Enrol).
 *
 *  The header belongs to `AppShell`, above the scrolling content, so it stays
 *  put while the screen scrolls. A screen reaches it through these two hooks
 *  rather than drawing a header of its own - one header per screen, always in
 *  the same place. Both clear themselves when the screen unmounts. */

interface Chrome {
  title: string | null;
  action: ReactNode;
  setTitle: (title: string | null) => void;
  setAction: (action: ReactNode) => void;
}

const PageChromeContext = createContext<Chrome | null>(null);

export function PageChromeProvider({ children }: { children: ReactNode }) {
  const [title, setTitle] = useState<string | null>(null);
  const [action, setAction] = useState<ReactNode>(null);
  const value = useMemo(() => ({ title, action, setTitle, setAction }), [title, action]);
  return <PageChromeContext.Provider value={value}>{children}</PageChromeContext.Provider>;
}

export function usePageChrome(): Chrome {
  const chrome = useContext(PageChromeContext);
  if (!chrome) throw new Error('usePageChrome must be used inside <PageChromeProvider>');
  return chrome;
}

/** Replace the header's title while this screen is showing. `null` or an empty
 *  string keeps the route's own title. */
export function usePageTitle(title: string | null | undefined): void {
  const { setTitle } = usePageChrome();
  useEffect(() => {
    setTitle(title || null);
    return () => setTitle(null);
  }, [title, setTitle]);
}

/** Put one action in the header while this screen is showing.
 *
 *  Pass the dependencies the node is built from: the header re-renders only
 *  when they change, not on every render of the screen. */
export function usePageAction(action: ReactNode, deps: readonly unknown[]): void {
  const { setAction } = usePageChrome();
  useEffect(() => {
    setAction(action);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => () => setAction(null), [setAction]);
}
