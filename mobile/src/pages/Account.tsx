import { useNavigate } from 'react-router-dom';
import { Card, PageHeader } from '@/components/ui';
import { useAuth } from '@/app/AuthContext';
import { useT } from '@/app/LanguageContext';

/** The Account tab.
 *
 *  The console reaches Settings from its sidebar and Accounts by typing the
 *  URL. A phone has neither a sidebar nor an address bar worth typing into, so
 *  the last tab is a short list of the three things left: the settings screen,
 *  the accounts screen for somebody allowed it, and signing out.
 *
 *  It adds no capability. Every row opens a page both apps share, and the
 *  Accounts row is hidden from a guard the same way the console hides it — as
 *  a courtesy, not a boundary. The engine refuses the request either way. */
export function Account() {
  const navigate = useNavigate();
  const { account, signOut } = useAuth();
  const t = useT();

  const isAdmin = account?.role === 'admin';

  return (
    <div className="screen">
      <PageHeader title={t('nav.tab.account')} lead={t('mobile.account.lead')} />

      <Card>
        <button type="button" className="list-row" onClick={() => navigate('/settings')}>
          <span style={{ minWidth: 0 }}>
            <span className="row__name" style={{ display: 'block' }}>
              {t('nav.settings.label')}
            </span>
            <span className="row__sub">{t('nav.settings.blurb')}</span>
          </span>
          <span className="row__chevron mirror-rtl" aria-hidden="true">›</span>
        </button>

        {isAdmin && (
          <button type="button" className="list-row" onClick={() => navigate('/users')}>
            <span style={{ minWidth: 0 }}>
              <span className="row__name" style={{ display: 'block' }}>
                {t('nav.users.label')}
              </span>
              <span className="row__sub">{t('nav.users.blurb')}</span>
            </span>
            <span className="row__chevron mirror-rtl" aria-hidden="true">›</span>
          </button>
        )}
      </Card>

      <div style={{ marginTop: 18 }}>
        <button
          type="button"
          className="btn btn--ghost"
          onClick={() => { void signOut(); }}
        >
          {t('action.signOut')}
        </button>
      </div>
    </div>
  );
}
