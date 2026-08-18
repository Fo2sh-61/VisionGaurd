import { Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from './AppShell';
import { useAuth } from './AuthContext';
import { Login } from '@/pages/Login';
import { Home } from '@/pages/Home';
import { Tools } from '@/pages/Tools';
import { ToolPage } from '@/pages/ToolPage';
import { People } from '@/pages/People';
import { PeopleGroup } from '@/pages/PeopleGroup';
import { PersonHistory } from '@/pages/PersonHistory';
import { SystemPage } from '@/pages/SystemPage';
import { Account } from '@/pages/Account';

export function AppRoutes() {
  const { account } = useAuth();

  return (
    <Routes>
      <Route path="/login" element={account ? <Navigate to="/" replace /> : <Login />} />

      <Route element={<AppShell />}>
        <Route index element={<Home />} />
        <Route path="tools" element={<Tools />} />
        <Route path="tool/:id" element={<ToolPage />} />
        <Route path="people" element={<People />} />
        <Route path="people/groups/:name" element={<PeopleGroup />} />
        <Route path="people/history/:name" element={<PersonHistory />} />
        <Route path="system" element={<SystemPage />} />
        <Route path="account" element={<Account />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
