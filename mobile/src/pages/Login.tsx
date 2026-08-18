import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/app/AuthContext';
import { Logo } from '@/components/Logo';
import { SCHOOL_NAME } from '@/services/mockData';

export function Login() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('mohamed61fouad@gmail.com');
  const [password, setPassword] = useState('demo1234');

  function doSignIn() {
    signIn('admin');
    navigate('/', { replace: true });
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    doSignIn();
  }

  return (
    <div className="app" style={{ justifyContent: 'center' }}>
      <form
        onSubmit={submit}
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          padding: '62px 24px 40px',
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12, marginBottom: 34 }}>
          <Logo size={52} />
          <div style={{ fontWeight: 800, fontSize: 21, letterSpacing: '-.02em' }}>
            VisionGuard <span style={{ fontWeight: 500, color: 'var(--tx3)' }}>AI</span>
          </div>
          <div style={{ fontSize: 13, color: 'var(--tx3)', textAlign: 'center' }}>{SCHOOL_NAME}</div>
        </div>

        <div className="stack">
          <label className="field">
            <span className="field__label">Email</span>
            <input
              className="input"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={{ height: 50, borderRadius: 14, border: 'none', boxShadow: 'var(--sh)' }}
            />
          </label>

          <label className="field">
            <span className="field__label">Password</span>
            <input
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={{ height: 50, borderRadius: 14, border: 'none', boxShadow: 'var(--sh)' }}
            />
          </label>

          <button type="submit" className="btn" style={{ height: 52, marginTop: 6 }}>
            Sign in
          </button>

          <button
            type="button"
            onClick={doSignIn}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 8,
              background: 'var(--chip)',
              border: 'none',
              borderRadius: 13,
              padding: '12px 14px',
              marginTop: 6,
              minHeight: 44,
              cursor: 'pointer',
            }}
          >
            <span style={{ fontSize: 13, color: 'var(--ac2)', fontWeight: 600 }}>Use Face ID instead</span>
          </button>

          <div style={{ fontSize: 12.5, color: 'var(--tx3)', textAlign: 'center', marginTop: 10, lineHeight: 1.4 }}>
            Demo build — any password is accepted.
          </div>
        </div>
      </form>
    </div>
  );
}
