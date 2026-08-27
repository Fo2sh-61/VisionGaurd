import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/app/AuthContext';
import { Logo } from '@/components/Logo';
import { useSiteName } from '@/app/SiteContext';

/** Shortest password the engine will hash — `auth/passwords.MIN_LENGTH`.
 *
 *  Repeated here only so the form can say so before a round trip. The engine
 *  is still the authority: it re-checks, and its message is what gets shown
 *  if the two ever disagree. */
const MIN_PASSWORD = 12;

type Mode = 'in' | 'up';

const labelStyle = {
  display: 'block',
  fontSize: 12.5,
  fontWeight: 600,
  color: 'var(--tx2)',
  marginBottom: 6,
} as const;

const inputStyle = {
  width: '100%',
  height: 46,
  border: '1px solid var(--line)',
  borderRadius: 11,
  padding: '0 14px',
  fontSize: 14.5,
  background: 'var(--card)',
  color: 'var(--tx)',
  outline: 'none',
  boxSizing: 'border-box',
} as const;

const hintStyle = {
  fontSize: 12,
  color: 'var(--tx3)',
  marginTop: 6,
  lineHeight: 1.4,
} as const;

export function Login() {
  const siteName = useSiteName();
  const { signIn, register } = useAuth();
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
        setError('The two passwords are not the same.');
        return;
      }
      if (password.length < MIN_PASSWORD) {
        setError(`Password must be at least ${MIN_PASSWORD} characters.`);
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
          : signingUp
            ? 'Could not create the account.'
            : 'Could not sign in.',
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
        background: 'var(--bg)',
      }}
    >
      <div style={{ width: '100%', maxWidth: 410 }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 11,
            justifyContent: 'center',
            marginBottom: 26,
          }}
        >
          <Logo size={38} />
          <div
            style={{
              fontWeight: 800,
              fontSize: 22,
              letterSpacing: '-.02em',
              whiteSpace: 'nowrap',
            }}
          >
            VisionGuard <span style={{ fontWeight: 500, color: 'var(--tx3)' }}>AI</span>
          </div>
        </div>

        <form
          onSubmit={submit}
          style={{
            background: 'var(--card)',
            borderRadius: 18,
            padding: '34px 32px',
            boxShadow: 'var(--sh)',
          }}
        >
          <div style={{ fontWeight: 700, fontSize: 17, marginBottom: siteName ? 0 : 22 }}>
            {signingUp ? 'Create an account' : 'Sign in'}
          </div>
          {/* No site name until a deployment sets one. The product name is
              already above the card, so repeating it here says nothing. */}
          {siteName && (
            <div style={{ fontSize: 13.5, color: 'var(--tx2)', margin: '2px 0 22px' }}>
              {siteName}
            </div>
          )}

          {signingUp && (
            <label style={{ display: 'block', marginBottom: 14 }}>
              <span style={labelStyle}>Full name</span>
              <input
                type="text"
                autoComplete="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                style={inputStyle}
              />
            </label>
          )}

          <label style={{ display: 'block', marginBottom: 14 }}>
            <span style={labelStyle}>Email</span>
            <input
              type="email"
              autoComplete={signingUp ? 'email' : 'username'}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={inputStyle}
            />
          </label>

          <label style={{ display: 'block', marginBottom: signingUp ? 14 : 18 }}>
            <span style={labelStyle}>Password</span>
            <input
              type="password"
              autoComplete={signingUp ? 'new-password' : 'current-password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={inputStyle}
            />
            {signingUp && (
              <div style={hintStyle}>At least {MIN_PASSWORD} characters.</div>
            )}
          </label>

          {signingUp && (
            <label style={{ display: 'block', marginBottom: 18 }}>
              <span style={labelStyle}>Confirm password</span>
              <input
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                style={inputStyle}
              />
            </label>
          )}

          {error && (
            <div
              role="alert"
              style={{
                padding: '10px 13px', borderRadius: 10, marginBottom: 14,
                background: 'var(--rd-bg)', color: 'var(--rd)',
                fontSize: 13.5, lineHeight: 1.45,
              }}
            >
              {error}
            </div>
          )}

          <div style={{ height: 4 }} />

          <button
            type="submit"
            disabled={busy || !ready}
            style={{
              width: '100%',
              height: 48,
              border: 'none',
              borderRadius: 12,
              background: 'var(--ac)',
              color: 'var(--on-ac)',
              fontSize: 15,
              fontWeight: 600,
              cursor: busy || !ready ? 'not-allowed' : 'pointer',
              opacity: busy || !ready ? 0.6 : 1,
            }}
          >
            {signingUp
              ? (busy ? 'Creating account…' : 'Create account')
              : (busy ? 'Signing in…' : 'Sign in')}
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
                New accounts get limited access. Enrolling faces, adding cameras
                and managing accounts stay with an administrator.
                <div style={{ marginTop: 10 }}>
                  Already have an account?{' '}
                  <button
                    type="button"
                    className="linkbtn"
                    onClick={() => switchTo('in')}
                    disabled={busy}
                  >
                    Sign in
                  </button>
                </div>
              </>
            ) : (
              <>
                Don&rsquo;t have an account?{' '}
                <button
                  type="button"
                  className="linkbtn"
                  onClick={() => switchTo('up')}
                  disabled={busy}
                >
                  Create one
                </button>
              </>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}
