import { Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from './AppShell';
import { useAuth } from './AuthContext';
import { Login } from '@/pages/Login';
import { Home } from '@/pages/Home';
import { Attendance } from '@/pages/Attendance';
import { Counting } from '@/pages/Counting';
import { Intrusion } from '@/pages/Intrusion';
import { Stations } from '@/pages/Stations';
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
import type { Role } from '@/types';
import type { ReactElement } from 'react';

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

/** No session, no console.
 *
 *  The shell used to render for anyone who loaded the page. With the engine
 *  now refusing unauthenticated calls, that would have meant a full console
 *  of "could not load" boxes and no hint that signing in was the answer. */
function RequireSignIn({ children }: { children: ReactElement }) {
  const { account, checking } = useAuth();

  // `checking` is the moment between loading the page and hearing back from
  // /auth/me. Redirecting during it would bounce a signed-in operator to the
  // sign-in form on every refresh.
  if (checking) return <SigningIn />;
  if (!account) return <Navigate to="/login" replace />;
  return children;
}

function SigningIn() {
  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center',
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
        {/* Attendance and People are admin-only (spec 022). The engine refuses
            an IT account on these paths; this only stops it landing on a page
            whose every call would fail. */}
        <Route path="attendance" element={<RequireRole role="admin"><Attendance /></RequireRole>} />
        <Route path="counting" element={<Counting />} />
        <Route path="intrusion" element={<Intrusion />} />
        <Route path="stations" element={<Stations />} />
        {/* Weapons, lost-items and track: out of the navigation (spec 022),
            code kept, still reachable by address. */}
        <Route path="weapons" element={<Weapons />} />
        <Route path="vehicles" element={<VehicleGate />} />
        <Route path="lost-items" element={<LostItems />} />
        <Route path="track" element={<TrackPerson />} />
        <Route path="people" element={<RequireRole role="admin"><People /></RequireRole>} />
        <Route path="people/enrol" element={<RequireRole role="admin"><Enrol /></RequireRole>} />
        <Route path="people/groups/:name" element={<RequireRole role="admin"><PeopleGroup /></RequireRole>} />
        <Route path="people/history/:name" element={<RequireRole role="admin"><PersonHistory /></RequireRole>} />
        <Route path="settings" element={<Settings />} />
        {/* System health is open to both roles, matching the design's nav —
            IT owns it, but an admin needs to be able to see what's down. */}
        <Route path="system" element={<SystemHealth />} />

        {/* Not in the sidebar (the design replaced it with People), but kept
            reachable by URL so sign-in accounts are still manageable. */}
        <Route
          path="users"
          element={
            <RequireRole role="admin">
              <Users />
            </RequireRole>
          }
        />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
