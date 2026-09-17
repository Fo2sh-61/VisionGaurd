import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/app/AuthContext';
import { useLanguage } from '@/app/LanguageContext';
import { Logo } from '@/components/Logo';
import { useSiteName } from '@/app/SiteContext';
import { Field } from '@/components/ui';
import { LANGUAGES } from '@/i18n';

/** Shortest password the engine will hash — `auth/passwords.MIN_LENGTH`.
 *
 *  Repeated here only so the form can say so before a round trip. The engine
 *  is still the authority: it re-checks, and its message is what gets shown
 *  if the two ever disagree. */
const MIN_PASSWORD = 12;

type Mode = 'in' | 'up';

/** Sign-in — a phone form, the console's behaviour (spec 015, contracts/
 *  phone-screens.md "Sign-in").
 *
 *  Built from `web/src/pages/Login.tsx`: the same two calls, the same typo
 *  guard on the confirm box, the same engine-owned error message, and the
 *  same pre-account language picker read before any account exists to hold
 *  one (P11-FR-016). Renders outside `AppShell` — there is no session yet
 *  for a tab bar to belong to — so it keeps its own full-height frame and
 *  16px gutter instead of the shell's `.screen`. */
export function Login() {
  const siteName = useSiteName();
  const { signIn, register } = useAuth();
  const { language, setLanguage, t } = useLanguage();
  const navigate = useNavigate();
  // Signing in is the common case, so it is the one the page opens on.
  const [mode, setMode] = useState<Mode>('in');
  // Empty, not prefilled. A real address and password were typed into this
  // file - anyone opening the page or the repository had a working account.
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const signingUp = mode === 'up';

  // Only the fields the current mode actually shows can block the button. A
  // disabled button with no visible reason reads as a broken page.
  const ready = signingUp
    ? Boolean(name.trim() && email && password && confirm)
    : Boolean(email && password);

  function switchTo(next: Mode) {
    setMode(next);
    // The error belonged to the other form. Carrying "email or password is
    // wrong" onto the sign-up card would be answering a question nobody asked.
    setError(null);
    setConfirm('');
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy || !ready) return;
    setError(null);

    if (signingUp) {
      // Checked here because the engine never sees the second box — it is a
      // typo guard for the person typing, not a rule the server enforces.
      if (password !== confirm) {
        setError(t('login.passwordsDiffer'));
        return;
      }
      if (password.length < MIN_PASSWORD) {
        setError(t('login.passwordTooShort', { min: MIN_PASSWORD }));
        return;
      }
    }

    setBusy(true);
    try {
      // The engine decides. This used to be `signIn('admin')` - the form
      // collected an email and password and threw them away, and the role was
      // an argument the page chose for itself.
      if (signingUp) {
        await register(name, email, password);
      } else {
        await signIn(email, password);
      }
      navigate('/', { replace: true });
    } catch (caught) {
      // The engine's own message, not one invented here. For sign-in it says
      // the same thing for a wrong password and an unknown account on purpose,
      // so a guessed school address cannot be confirmed from this form. For
      // sign-up it names the real reason - too short, already registered -
      // because a person who cannot get in has to be told why.
      setError(
        caught instanceof Error
          ? caught.message
          : t(signingUp ? 'login.couldNotCreate' : 'login.couldNotSignIn'),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      style={{
        minHeight: '100dvh',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        padding: 16,
        background: 'var(--bg)',
      }}
    >
      <div style={{ width: '100%', maxWidth: 400, margin: '0 auto' }}>
        {/* Before anybody signs in there is no account to hold a language, so
            this reads the browser copy instead. Without it an Arabic-reading
            guard would have to get through an English sign-in form to reach
            the setting that would have made it Arabic (P11-FR-016). */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'center',
            gap: 8,
            marginBottom: 18,
          }}
        >
          {LANGUAGES.map((k) => (
            <button
              key={k}
              type="button"
              className={`chip-btn ${language === k ? 'chip-btn--on' : 'chip-btn--off'}`}
              onClick={() => setLanguage(k)}
            >
              {t(`settings.language.${k}`)}
            </button>
          ))}
        </div>

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            justifyContent: 'center',
            marginBottom: 24,
          }}
        >
          <Logo size={36} />
          <div style={{ fontWeight: 800, fontSize: 20, letterSpacing: '-.02em' }}>
            VisionGuard
          </div>
        </div>

        <form onSubmit={submit} className="card" style={{ padding: '26px 20px' }}>
          <div style={{ fontWeight: 700, fontSize: 17, marginBottom: siteName ? 0 : 18 }}>
            {t(signingUp ? 'login.createAccountTitle' : 'login.signIn')}
          </div>
          {/* No site name until a deployment sets one. The product name is
              already above the card, so repeating it here says nothing. */}
          {siteName && (
            <div style={{ fontSize: 13.5, color: 'var(--tx2)', margin: '2px 0 18px' }}>
              {siteName}
            </div>
          )}

          <div className="stack">
            {signingUp && (
              <Field label={t('login.fullName')}>
                <input
                  className="input"
                  type="text"
                  autoComplete="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </Field>
            )}

            <Field label={t('login.email')}>
              <input
                className="input"
                type="email"
                autoComplete={signingUp ? 'email' : 'username'}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </Field>

            <Field label={t('login.password')}>
              <input
                className="input"
                type="password"
                autoComplete={signingUp ? 'new-password' : 'current-password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              {signingUp && (
                <div className="note" style={{ marginTop: 2 }}>
                  At least {MIN_PASSWORD} characters.
                </div>
              )}
            </Field>

            {signingUp && (
              <Field label={t('login.confirmPassword')}>
                <input
                  className="input"
                  type="password"
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                />
              </Field>
            )}
          </div>

          {error && (
            <div role="alert" className="notice notice--bad" style={{ marginTop: 14 }}>
              {error}
            </div>
          )}

          <button
            type="submit"
            className="btn btn--block"
            disabled={busy || !ready}
            style={{ marginTop: 18 }}
          >
            {signingUp
              ? t(busy ? 'login.creating' : 'login.createAccount')
              : t(busy ? 'login.signingIn' : 'login.signIn')}
          </button>

          <div
            style={{
              fontSize: 12.5, color: 'var(--tx3)', textAlign: 'center',
              marginTop: 16, lineHeight: 1.5,
            }}
          >
            {signingUp ? (
              <>
                {/* Said plainly, because it is what the new account will
                    actually find: the read-only half of the product. Enrolment,
                    cameras and accounts stay with an administrator, and the
                    engine enforces that whatever this page draws. */}
                {t('login.limitedAccess')}
                <div style={{ marginTop: 10 }}>
                  {t('login.haveAccount')}{' '}
                  <button
                    type="button"
                    className="linkbtn"
                    onClick={() => switchTo('in')}
                    disabled={busy}
                  >
                    {t('login.signIn')}
                  </button>
                </div>
              </>
            ) : (
              <>
                {t('login.noAccount')}{' '}
                <button
                  type="button"
                  className="linkbtn"
                  onClick={() => switchTo('up')}
                  disabled={busy}
                >
                  {t('login.createOne')}
                </button>
              </>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
