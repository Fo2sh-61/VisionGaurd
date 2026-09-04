import { useNavigate } from 'react-router-dom';
import { PageHeader } from '@/components/ui';
import { toolEntries } from '@/app/tabs';
import { useT } from '@/app/LanguageContext';

/** The Tools tab.
 *
 *  A phone screen with no console equivalent, because the console does not
 *  need one: its sidebar carries the same list down the left of every page.
 *  This adds no capability — it is the same entries, the same order, the same
 *  wording, reached by a tab instead of by a sidebar.
 *
 *  The list comes from `NAV`, the table the console renders from. It is not
 *  retyped here: the fixture app retyped it, ended up with six tools instead
 *  of seven, and shipped a phone with no vehicle gate on it at all. */
export function Tools() {
  const navigate = useNavigate();
  const t = useT();
  const entries = toolEntries();

  return (
    <div className="screen">
      <PageHeader title={t('nav.tab.tools')} lead={t('mobile.tools.lead')} />

      <div className="card">
        {entries.map((entry) => (
          <button
            key={entry.id}
            type="button"
            className="list-row"
            onClick={() => navigate(entry.path)}
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
              <svg width="20" height="20" viewBox="0 0 18 18" fill="none" aria-hidden="true">
                <path
                  d={entry.icon}
                  stroke="var(--ac)"
                  strokeWidth={1.6}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              <span style={{ minWidth: 0 }}>
                <span className="row__name" style={{ display: 'block' }}>
                  {t(`nav.${entry.id}.label`)}
                </span>
                <span className="row__sub">{t(`nav.${entry.id}.blurb`)}</span>
              </span>
            </span>
            {/* The chevron points the way the language reads. */}
            <span className="row__chevron mirror-rtl" aria-hidden="true">›</span>
          </button>
        ))}
      </div>
    </div>
  );
}
