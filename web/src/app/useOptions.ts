/** Dropdown options that come from the engine, not from copy.
 *
 *  Group names, people and place names are *data* — they change when the school
 *  changes, not when the wording does. These hooks fetch them once per mount
 *  and fall back to an empty list, so a select renders empty rather than
 *  showing a name that no longer exists.
 *
 *  Contrast with `services/content.ts`, which holds fixed vocabulary the
 *  interface owns (colours, time presets, explainer copy). */

import { useEffect, useState } from 'react';
import { useLanguage } from '@/app/LanguageContext';
import { getGroups, getPeople } from '@/services/api';
import { useSite } from './SiteContext';

/** ["Grade 7", "Grade 8", "All staff", …] */
export function useGroupNames(): string[] {
  const { language } = useLanguage();
  const [names, setNames] = useState<string[]>([]);
  useEffect(() => {
    let cancelled = false;
    void getGroups(language)
      .then((groups) => {
        if (!cancelled) setNames(groups.map((g) => g.name));
      })
      .catch(() => {
        /* the page's own error state covers this */
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return names;
}

/** Every person who can be looked up by name.
 *
 *  Names are the current key and they travel in URLs, which breaks the moment
 *  two students share one. The engine already returns a stable id; when the
 *  pages move to ids, this hook returns pairs instead. */
export function usePersonNames(type?: 'Student' | 'Staff' | 'Visitor'): string[] {
  const { language } = useLanguage();
  const [names, setNames] = useState<string[]>([]);
  useEffect(() => {
    let cancelled = false;
    void getPeople(language)
      .then((people) => {
        if (cancelled) return;
        setNames(people.filter((p) => !type || p.type === type).map((p) => p.name));
      })
      .catch(() => {
        /* as above */
      });
    return () => {
      cancelled = true;
    };
  }, [type]);
  return names;
}

/** Countable areas on the campus plan. Comes with the site info. */
export function usePlaces(): string[] {
  return useSite().site?.places ?? [];
}

/** Keeps a select valid while its options are still loading.
 *
 *  Returns the current choice if it is still available, otherwise the first
 *  option — so the control never sits on a value the engine does not know. */
export function useChoice(options: string[], chosen: string): string {
  return options.includes(chosen) ? chosen : (options[0] ?? '');
}
