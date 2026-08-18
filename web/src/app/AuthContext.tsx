import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import type { Role } from '@/types';

export interface Account {
  name: string;
  role: Role;
  initials: string;
  email: string;
}

const ACCOUNTS: Record<Role, Account> = {
  admin: {
    name: 'Mohamed Fouad',
    role: 'admin',
    initials: 'MF',
    email: 'mohamed61fouad@gmail.com',
  },
  it: { name: 'Tarek Nassar', role: 'it', initials: 'TN', email: 'tarek.n@school.edu' },
};

interface AuthValue {
  account: Account | null;
  signIn: (role: Role) => void;
  signOut: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

const STORAGE_KEY = 'vg.role';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<Account | null>(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    return saved === 'admin' || saved === 'it' ? ACCOUNTS[saved] : null;
  });

  const signIn = useCallback((role: Role) => {
    localStorage.setItem(STORAGE_KEY, role);
    setAccount(ACCOUNTS[role]);
  }, []);

  const signOut = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setAccount(null);
  }, []);

  const value = useMemo(() => ({ account, signIn, signOut }), [account, signIn, signOut]);
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
