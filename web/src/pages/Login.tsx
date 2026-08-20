import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/app/AuthContext';
import { Logo } from '@/components/Logo';
import { useSiteName } from '@/app/SiteContext';

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

export function Login() {
  const schoolName = useSiteName();
  const { signIn } = useAuth();
  const navigate = useNavigate();
  // Empty, not prefilled. A real address and password were typed into this
  // file - anyone opening the page or the repository had a working account.
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setError(null);
    setBusy(true);
    try {
      // The engine decides. This used to be `signIn('admin')` - the form
      // collected an email and password and threw them away, and the role was
      // an argument the page chose for itself.
      await signIn(email, password);
      navigate('/', { replace: true });
    } catch (caught) {
      // The engine's own message, not one invented here. It says the same
      // thing for a wrong password and an unknown account on purpose, so a
      // guessed school address cannot be confirmed from this form.
      setError(caught instanceof Error ? caught.message : 'Could not sign in.');
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
          <div style={{ fontWeight: 700, fontSize: 17 }}>Sign in</div>
          <div style={{ fontSize: 13.5, color: 'var(--tx2)', margin: '2px 0 22px' }}>
            {schoolName}
          </div>

          <label style={{ display: 'block', marginBottom: 14 }}>
            <span style={labelStyle}>Email</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={inputStyle}
            />
          </label>

          <label style={{ display: 'block', marginBottom: 18 }}>
            <span style={labelStyle}>Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={inputStyle}
            />
          </label>

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
            disabled={busy || !email || !password}
            style={{
              width: '100%',
              height: 48,
              border: 'none',
              borderRadius: 12,
              background: 'var(--ac)',
              color: 'var(--on-ac)',
              fontSize: 15,
              fontWeight: 600,
              cursor: busy || !email || !password ? 'not-allowed' : 'pointer',
              opacity: busy || !email || !password ? 0.6 : 1,
            }}
          >
            {busy ? 'Signing in…' : 'Sign in'}
          </button>

          <div style={{ fontSize: 12.5, color: 'var(--tx3)', textAlign: 'center', marginTop: 16 }}>
            Accounts are created on the engine by an administrator.
          </div>
        </form>
      </div>
    </div>
  );
}
