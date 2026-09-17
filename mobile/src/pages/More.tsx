import { useNavigate } from 'react-router-dom';
import { useAccount, useAuth } from '@/app/AuthContext';
import { useLanguage, useT } from '@/app/LanguageContext';
import { useSiteName } from '@/app/SiteContext';
import { useTheme } from '@/app/ThemeContext';
import { Icon } from '@/components/Icon';
import { Toggle } from '@/components/ui';
import { LANGUAGES } from '@/i18n';

/** The More tab (spec 015, P13-FR-042, P13-FR-049).
 *
 *  Everything the console reaches from the foot of its sidebar or by typing a
 *  URL — System health, Settings, Accounts, appearance and sign out — plus who
 *  is signed in, because a phone has no sidebar to show that permanently.
 *
 *  Adds no capability: every row opens a page both apps share (`/system`,
 *  `/settings`, `/users`), and dark mode / language are the same
 *  `useTheme`/`useLanguage` the console's own Settings page uses — the same
 *  toggle, the same two buttons, the same account-backed save. Accounts is
 *  hidden from a guard as a courtesy, exactly as the console hides it; the
 *  engine decides either way. */
export function More() {
  const navigate = useNavigate();
  const account = useAccount();
  const { signOut } = useAuth();
  const t = useT();
  const { language, setLanguage } = useLanguage();
  const { dark, toggle } = useTheme();
  const siteName = useSiteName();

  const isAdmin = account.role === 'admin';

  return (
    <>
      <h1 className="h1">{t('nav.tab.more')}</h1>

      <div className="card hstack">
        <span className="avatar avatar--lg" aria-hidden="true">{account.initials}</span>
        <div className="stack stack--tight" style={{ gap: 2, minWidth: 0 }}>
          <span className="li__title">{account.name}</span>
          <span className="li__sub">
            {t(account.role === 'admin' ? 'role.admin' : 'role.it')}
            {siteName ? ` · ${siteName}` : ''}
          </span>
        </div>
      </div>

      <div className="list">
        <button type="button" className="li" onClick={() => navigate('/system')}>
          <span className="icontile" aria-hidden="true"><Icon name="system" /></span>
          <span className="li__main">
            <span className="li__title">{t('health.title')}</span>
            <span className="li__sub">{t('phone.more.systemSub')}</span>
          </span>
          <span className="li__chev"><Icon name="chevron" size={18} mirror /></span>
        </button>

        <button type="button" className="li" onClick={() => navigate('/settings')}>
          <span className="icontile" aria-hidden="true"><Icon name="settings" /></span>
          <span className="li__main">
            <span className="li__title">{t('nav.settings.label')}</span>
            <span className="li__sub">{t('phone.more.settingsSub')}</span>
          </span>
          <span className="li__chev"><Icon name="chevron" size={18} mirror /></span>
        </button>

        {isAdmin && (
          <button type="button" className="li" onClick={() => navigate('/users')}>
            <span className="icontile" aria-hidden="true"><Icon name="user" /></span>
            <span className="li__main">
              <span className="li__title">{t('nav.users.label')}</span>
              <span className="li__sub">{t('phone.more.accountsSub')}</span>
            </span>
            <span className="li__chev"><Icon name="chevron" size={18} mirror /></span>
          </button>
        )}
      </div>

      <section className="stack" aria-labelledby="more-appearance">
        <div className="sechead">
          <h2 className="sechead__title" id="more-appearance" style={{ margin: 0 }}>
            {t('phone.more.appearance')}
          </h2>
        </div>
        <div className="list">
          <div className="li">
            <span className="icontile" aria-hidden="true"><Icon name="moon" /></span>
            <span className="li__main">
              <span className="li__title">{t('phone.more.dark')}</span>
              <span className="li__sub">{t('phone.more.darkSub')}</span>
            </span>
            <Toggle on={dark} onToggle={toggle} label={t('phone.more.dark')} />
          </div>

          <div className="li" style={{ flexWrap: 'wrap' }}>
            <span className="icontile" aria-hidden="true"><Icon name="globe" /></span>
            <span className="li__main">
              <span className="li__title">{t('settings.language')}</span>
              <span className="li__sub">{t('phone.more.languageSub')}</span>
            </span>
            <div className="seg" style={{ width: '100%' }}>
              {LANGUAGES.map((code) => (
                <button
                  key={code}
                  type="button"
                  className={language === code ? 'seg__btn seg__btn--on' : 'seg__btn'}
                  aria-pressed={language === code}
                  onClick={() => setLanguage(code)}
                >
                  {t(`settings.language.${code}`)}
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>

      <button
        type="button"
        className="btn btn--ghost btn--block"
        onClick={() => { void signOut(); }}
      >
        <Icon name="logout" />
        {t('action.signOut')}
      </button>
    </>
  );
}
