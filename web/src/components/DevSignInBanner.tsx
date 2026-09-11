/** DEV-SIGNIN: TEMPORARY, development only. Goes when developer sign-in goes -
 *  see engine/vg/auth/dev_signin.py.
 *
 *  Rule 4: never show anything untrue. A console that opened without a
 *  password must not look like one somebody signed in to, so this sits on top
 *  of every page for as long as the built-in account is the one in use. */

import { useAccount } from '@/app/AuthContext';

export function DevSignInBanner() {
  const account = useAccount();
  if (!account.devSignIn) return null;

  return (
    <div
      role="status"
      style={{
        padding: '8px 40px',
        background: 'var(--rd-bg)',
        color: 'var(--rd)',
        borderBottom: '1px solid var(--rd)',
        fontSize: 13,
        fontWeight: 600,
      }}
    >
      Developer sign-in is on — anyone using this computer is signed in as Developer
      ({account.role === 'admin' ? 'admin' : 'IT'}) with no password. Development only:
      never run it at a school.
    </div>
  );
}
