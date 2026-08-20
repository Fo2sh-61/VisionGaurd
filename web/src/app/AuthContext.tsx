/** Who is signed in — according to the engine, not according to this browser.
 *
 *  What this replaces, in full:
 *
 *      localStorage.setItem('vg.role', 'admin')
 *
 *  That was the whole authorisation system. Two accounts were hard-coded in
 *  this file, `signIn(role)` took the role as an argument, and the email and
 *  password on the sign-in form were collected and thrown away. Typing that
 *  one line into a browser console made you an administrator of a system
 *  holding face data for children.
 *
 *  Now the account comes from `/auth/me` and nowhere else. Nothing about it is
 *  stored in this browser, so there is nothing to edit: changing anything here
 *  changes what the console *draws*, and the engine still refuses the request.
 *  The role is a hint for the interface, never a permission.
 *
 *  The session survives a refresh through an HttpOnly cookie the engine sets.
 *  A script cannot read it, which is the point — the token this file holds is
 *  in memory only and is expected to be lost on reload.
 */

import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
  type ReactNode,
} from 'react';
import { getMe, signIn as apiSignIn, signOut as apiSignOut } from '@/services/api';
import { setUnauthorisedHandler } from '@/services/http';
import type { Role } from '@/types';

export interface Account {
  id: string;
  name: string;
  role: Role;
  initials: string;
  email: string;
}

interface AuthValue {
  account: Account | null;
  /** True until we have asked the engine whether a session exists. Rendering
   *  the sign-in form during this moment would flash it at somebody who is
   *  already signed in, on every refresh. */
  checking: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<Account | null>(null);
  const [checking, setChecking] = useState(true);

  // Ask the engine who we are. On a fresh load this is what turns the cookie
  // back into a session; a 401 simply means nobody is signed in, which is not
  // an error worth showing.
  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((me) => !cancelled && setAccount(me))
      .catch(() => !cancelled && setAccount(null))
      .finally(() => !cancelled && setChecking(false));
    return () => {
      cancelled = true;
    };
  }, []);

  // One place decides what a 401 means. Without this a session that expires
  // mid-shift leaves every page showing "could not load" and no way to guess
  // that signing in again is the fix.
  useEffect(() => {
    setUnauthorisedHandler(() => setAccount(null));
    return () => setUnauthorisedHandler(null);
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    // Throws on bad credentials; the form shows the engine's message rather
    // than inventing one, so "email or password is wrong" stays a single
    // answer and cannot become a way to test whether an account exists.
    const me = await apiSignIn(email, password);
    setAccount(me);
  }, []);

  const signOut = useCallback(async () => {
    // Clear locally first: if the network call fails, the operator has still
    // left the console, which is what they asked for. The server-side row is
    // what actually ends the session, and it is attempted regardless.
    setAccount(null);
    try {
      await apiSignOut();
    } catch {
      /* already gone, or unreachable — either way this browser is signed out */
    }
  }, []);

  const value = useMemo(
    () => ({ account, checking, signIn, signOut }),
    [account, checking, signIn, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
}

/** Inside the signed-in shell the account always exists — this saves the null checks. */
export function useAccount(): Account {
  const { account } = useAuth();
  if (!account) throw new Error('useAccount used outside a signed-in route');
  return account;
}
