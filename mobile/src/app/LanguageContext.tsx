/** Which language the console is speaking, and which way it reads.
 *
 *  Shaped like `ThemeContext`, with one deliberate difference: theme is a
 *  property of the browser, language is a property of the **account**. The
 *  gate station is shared, and per-browser storage would show one guard the
 *  language the previous guard chose (P11-FR-014).
 *
 *  `localStorage` still holds a copy, for exactly one job: the sign-in page,
 *  which has to be readable before there is an account to ask (P11-FR-016).
 *  `services/http.ts` explains at length why the *session token* is not kept
 *  there; a display preference carries none of that risk. */

import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
  type ReactNode,
} from 'react';
import { useAuth } from '@/app/AuthContext';
import { DIRECTION, translate, type Language, type MessageArgs, type MessageKey }
  from '@/i18n';
import { setAccountLanguage } from '@/services/api';

const STORAGE_KEY = 'vg.lang';

/** A `t` already bound to the active language, so a component never has to
 *  pass it. `services/format.ts` takes the language explicitly instead — it is
 *  not a component and must stay testable without React. */
export type Translate = (key: MessageKey, args?: MessageArgs) => string;

interface LanguageValue {
  language: Language;
  t: Translate;
  /** Optimistic: the console changes immediately and the account catches up.
   *  A failed write leaves the choice applied locally and unsaved, which is
   *  the same thing every other preference does and is visible next sign-in. */
  setLanguage: (next: Language) => void;
}

const LanguageContext = createContext<LanguageValue | null>(null);

function remembered(): Language {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'ar' || saved === 'en') return saved;
  } catch {
    // Private windows and locked-down browsers throw on access rather than
    // returning null. A missing preference is not an error.
  }
  return navigator.language?.startsWith('ar') ? 'ar' : 'en';
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const { account } = useAuth();
  const [language, setState] = useState<Language>(remembered);

  // The account is the authority. Signing in adopts that account's language,
  // including when a second guard signs in at the same station.
  useEffect(() => {
    if (account?.language) setState(account.language);
  }, [account?.language]);

  useEffect(() => {
    document.documentElement.lang = language;
    document.documentElement.dir = DIRECTION[language];
  }, [language]);

  const setLanguage = useCallback((next: Language) => {
    setState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // See `remembered` — storage can refuse. The choice still applies to
      // this session; only the sign-in page's guess is lost.
    }
    if (account) void setAccountLanguage(next).catch(() => undefined);
  }, [account]);

  const value = useMemo<LanguageValue>(() => ({
    language,
    t: (key, args) => translate(language, key, args),
    setLanguage,
  }), [language, setLanguage]);

  return (
    <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>
  );
}

export function useLanguage(): LanguageValue {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error('useLanguage must be used inside <LanguageProvider>');
  return ctx;
}

/** The common case: a component that only wants to say things. */
export function useT(): Translate {
  return useLanguage().t;
}
