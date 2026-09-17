import { useNavigate } from 'react-router-dom';
import { useCapabilities } from '@/app/CapabilityContext';
import { useT } from '@/app/LanguageContext';
import { toolEntries } from '@/app/tabs';
import { Icon } from '@/components/Icon';
import type { NavEntry, NavSection } from '@/app/navigation';

/** The Tools tab (spec 015, P13-FR-048).
 *
 *  Built from the phone's original Tools tab, which already drew the console's
 *  `NAV` table rather than retyping it (the fixture app retyped it and shipped
 *  a phone with no vehicle gate at all). What changes here is the row itself:
 *  the console's `list-row` markup becomes the phone's `li` idiom, an
 *  `icontile` replaces the bare stroked icon, and each row now says when its
 *  tool is not measuring the real thing.
 *
 *  A tool's state, not its count (R11): a live number per row would be seven
 *  extra polls on a screen nobody watches continuously, and the four figures
 *  that matter are on Home already. Instead each row shows the engine's own
 *  capability state — demo data, or not running — exactly as `DataNotice`
 *  would word it, so a paused tool never reads as a working one. */

/** Tool id → the capability key that tool's own page checks. Kept here, not
 *  in `navigation.ts`, because it is a phone-only reading of a console table:
 *  the console asks each page for its own capability, one at a time. */
const CAPABILITY_KEY: Partial<Record<NavEntry['id'], string>> = {
  attendance: 'attendance',
  counting: 'count',
  'lost-items': 'search_lost',
  track: 'track',
  intrusion: 'breaches',
  weapons: 'weapons',
  vehicles: 'vehicles',
};

const SECTIONS: NavSection[] = ['ask', 'watch'];

export function Tools() {
  const navigate = useNavigate();
  const t = useT();
  const { of } = useCapabilities();
  const entries = toolEntries();

  return (
    <>
      <div>
        <h1 className="h1">{t('nav.tab.tools')}</h1>
        <p className="lead">{t('mobile.tools.lead')}</p>
      </div>

      {SECTIONS.map((section) => {
        const items = entries.filter((entry) => entry.section === section);
        if (items.length === 0) return null;
        return (
          <section key={section} className="stack" aria-labelledby={`tools-${section}`}>
            <div className="sechead">
              <h2 className="sechead__title" id={`tools-${section}`} style={{ margin: 0 }}>
                {t(`nav.section.${section}`)}
              </h2>
            </div>
            <div className="list">
              {items.map((entry) => {
                const key = CAPABILITY_KEY[entry.id];
                const capability = key ? of(key) : null;
                const notLive = !!capability && capability.state !== 'live';
                return (
                  <button
                    key={entry.id}
                    type="button"
                    className="li"
                    onClick={() => navigate(entry.path)}
                  >
                    <span
                      className={notLive ? 'icontile icontile--warn' : 'icontile'}
                      aria-hidden="true"
                    >
                      <Icon tool={entry.id} />
                    </span>
                    <span className="li__main">
                      <span className="li__title">{t(`nav.${entry.id}.label`)}</span>
                      <span className="li__sub">{t(`nav.${entry.id}.blurb`)}</span>
                      {notLive && (
                        <span className="li__sub" style={{ color: 'var(--am)' }}>
                          <span style={{ fontWeight: 600 }}>
                            {t(capability!.state === 'demo' ? 'state.demoData' : 'state.notAvailable')}
                          </span>
                          {': '}
                          {capability!.reason
                            ?? t('state.featureNotAvailable', { feature: capability!.name })}
                        </span>
                      )}
                    </span>
                    <span className="li__chev"><Icon name="chevron" size={18} mirror /></span>
                  </button>
                );
              })}
            </div>
          </section>
        );
      })}
    </>
  );
}
