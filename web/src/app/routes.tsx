import { Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from './AppShell';
import { useAuth } from './AuthContext';
import { Login } from '@/pages/Login';
import { Home } from '@/pages/Home';
import { Attendance } from '@/pages/Attendance';
import { Counting } from '@/pages/Counting';
import { Intrusion } from '@/pages/Intrusion';
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

/** Roles are a product rule here, not a security boundary — the real check
 *  belongs on the API once there is one. */
function RequireRole({ role, children }: { role: Role; children: ReactElement }) {
  const { account } = useAuth();
  if (account && account.role !== role) return <Navigate to="/" replace />;
  return children;
}

export function AppRoutes() {
  const { account } = useAuth();

  return (
    <Routes>
      <Route path="/login" element={account ? <Navigate to="/" replace /> : <Login />} />

      <Route element={<AppShell />}>
        <Route index element={<Home />} />
        <Route path="attendance" element={<Attendance />} />
        <Route path="counting" element={<Counting />} />
        <Route path="intrusion" element={<Intrusion />} />
        <Route path="weapons" element={<Weapons />} />
        <Route path="lost-items" element={<LostItems />} />
        <Route path="track" element={<TrackPerson />} />
        <Route path="people" element={<People />} />
        <Route path="people/enrol" element={<Enrol />} />
        <Route path="people/groups/:name" element={<PeopleGroup />} />
        <Route path="people/history/:name" element={<PersonHistory />} />
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
