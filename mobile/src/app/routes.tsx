import { Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from './AppShell';
import { useAuth } from './AuthContext';
import { Login } from '@/pages/Login';
import { Home } from '@/pages/Home';
import { Attendance } from '@/pages/Attendance';
import { Counting } from '@/pages/Counting';
import { Intrusion } from '@/pages/Intrusion';
import { VehicleGate } from '@/pages/VehicleGate';
import { Weapons } from '@/pages/Weapons';
import { LostItems } from '@/pages/LostItems';
import { TrackPerson } from '@/pages/TrackPerson';
import { SystemHealth } from '@/pages/SystemHealth';
import { Users } from '@/pages/Users';
import { People } from '@/pages/People';
import { Enrol } from '@/pages/Enrol';
import { PeopleGroup } from '@/pages/PeopleGroup';
import { PersonHistory } from '@/pages/PersonHistory';
import { Settings } from '@/pages/Settings';
import { Tools } from '@/pages/Tools';
import { Account } from '@/pages/Account';
import type { Role } from '@/types';
import type { ReactElement } from 'react';

/*  The same routes as the console, at the same paths.
 *
 *  **The paths are a contract, not a preference.** Ask answers deep-link into
 *  them carrying query parameters — "any knife alerts this week" opens
 *  `/weapons?window=last7` with the question already applied. Renaming a path
 *  here would not break the build; it would quietly turn every Ask answer on
 *  the phone into a redirect to Home.
 *
 *  Two paths exist here and not on the console — `/tools` and `/account`.
 *  They are the two tabs that are lists: the console shows its tools down the
 *  left of every screen and has no need of a page for them, and a phone has
 *  no room for a permanent sidebar. They add no capability.
 *
 *  `RequireRole` and `RequireSignIn` are copied from the console rather than
 *  rewritten, comments included, because what they do and do not promise is
 *  the easiest thing in this app to get subtly wrong.
 */

/** Hiding a page the account cannot use. **Not** the security boundary.
 *
 *  The engine enforces roles server-side and would refuse the request anyway;
 *  this only avoids showing somebody a screen whose every action will be
 *  refused. Editing anything in this browser changes what is drawn and
 *  nothing about what is allowed. */
function RequireRole({ role, children }: { role: Role; children: ReactElement }) {
  const { account } = useAuth();
  if (account && account.role !== role) return <Navigate to="/" replace />;
  return children;
}

/** No session, no console. */
function RequireSignIn({ children }: { children: ReactElement }) {
  const { account, checking } = useAuth();

  // `checking` is the moment between loading the page and hearing back from
  // /auth/me. Redirecting during it would bounce a signed-in guard to the
  // sign-in form on every refresh — and a phone reloads far more often than a
  // desktop, because the browser discards a backgrounded tab.
  if (checking) return <SigningIn />;
  if (!account) return <Navigate to="/login" replace />;
  return children;
}

function SigningIn() {
  return (
    <div style={{
      minHeight: '100dvh', display: 'flex', alignItems: 'center',
      justifyContent: 'center', color: 'var(--tx2)', fontSize: 14,
    }}>
      Checking your session…
    </div>
  );
}

export function AppRoutes() {
  const { account, checking } = useAuth();

  return (
    <Routes>
      <Route
        path="/login"
        element={checking ? <SigningIn /> : account ? <Navigate to="/" replace /> : <Login />}
      />

      <Route element={<RequireSignIn><AppShell /></RequireSignIn>}>
        <Route index element={<Home />} />

        {/* The Tools tab, and the seven screens behind it. */}
        <Route path="tools" element={<Tools />} />
        <Route path="attendance" element={<Attendance />} />
        <Route path="counting" element={<Counting />} />
        <Route path="intrusion" element={<Intrusion />} />
        <Route path="weapons" element={<Weapons />} />
        <Route path="vehicles" element={<VehicleGate />} />
        <Route path="lost-items" element={<LostItems />} />
        <Route path="track" element={<TrackPerson />} />

        {/* The People tab. Enrolment is admin-only, matching the console. */}
        <Route path="people" element={<People />} />
        <Route
          path="people/enrol"
          element={<RequireRole role="admin"><Enrol /></RequireRole>}
        />
        <Route path="people/groups/:name" element={<PeopleGroup />} />
        <Route path="people/history/:name" element={<PersonHistory />} />

        {/* The System tab. Camera setup is inside this page, not beside it. */}
        <Route path="system" element={<SystemHealth />} />

        {/* The Account tab. */}
        <Route path="account" element={<Account />} />
        <Route path="settings" element={<Settings />} />
        <Route
          path="users"
          element={<RequireRole role="admin"><Users /></RequireRole>}
        />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
