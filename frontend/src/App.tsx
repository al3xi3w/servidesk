import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider } from './auth/AuthContext';
import AppLayout, { RoleGate } from './components/AppLayout';
import { ToastProvider } from './components/ui';
import Users from './pages/admin/Users';
import ChangeCalendar from './pages/changes/ChangeCalendar';
import ChangeDetail from './pages/changes/ChangeDetail';
import ChangeList from './pages/changes/ChangeList';
import CiDetail from './pages/cmdb/CiDetail';
import CiList from './pages/cmdb/CiList';
import Dashboard from './pages/Dashboard';
import IncidentDetail from './pages/incidents/IncidentDetail';
import IncidentList from './pages/incidents/IncidentList';
import Landing from './pages/Landing';
import Login from './pages/Login';
import Platform from './pages/Platform';
import ProblemDetail from './pages/problems/ProblemDetail';
import ProblemList from './pages/problems/ProblemList';
import Catalog from './pages/requests/Catalog';
import RequestDetail from './pages/requests/RequestDetail';
import RequestList from './pages/requests/RequestList';

const STAFF = ['admin', 'agent'] as const;
const staff = (el: React.ReactNode) => <RoleGate roles={[...STAFF]}>{el}</RoleGate>;

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/login" element={<Login />} />
            <Route path="/app" element={<AppLayout />}>
              <Route index element={<Dashboard />} />
              <Route path="incidents" element={<IncidentList />} />
              <Route path="incidents/:id" element={<IncidentDetail />} />
              <Route path="catalog" element={<Catalog />} />
              <Route path="requests" element={<RequestList />} />
              <Route path="requests/:id" element={<RequestDetail />} />
              <Route path="problems" element={staff(<ProblemList />)} />
              <Route path="problems/:id" element={staff(<ProblemDetail />)} />
              <Route path="changes" element={staff(<ChangeList />)} />
              <Route path="changes/calendar" element={staff(<ChangeCalendar />)} />
              <Route path="changes/:id" element={staff(<ChangeDetail />)} />
              <Route path="cmdb" element={staff(<CiList />)} />
              <Route path="cmdb/:id" element={staff(<CiDetail />)} />
              <Route path="users" element={staff(<Users />)} />
              <Route path="*" element={<Navigate to="/app" replace />} />
            </Route>
            {/* Vista técnica (microservicios y eventos) solo para la presentación del curso: no aparece en el menú. */}
            <Route path="/demo" element={<AppLayout />}>
              <Route path="plataforma" element={staff(<Platform />)} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
