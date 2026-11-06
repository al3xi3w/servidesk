import { useEffect, useState } from 'react';
import { Navigate, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { MOCKED_SERVICES } from '../api';
import { useAuth } from '../auth/AuthContext';
import { ROLE } from '../lib/format';
import { tenantStyle, tenantTheme } from '../lib/tenant';
import { NotificationBell } from './NotificationBell';
import type { Role } from '../types/api';
import { Icon, type IconName } from './Icon';
import { Logo } from './Logo';
import { Avatar, Spinner } from './ui';

interface NavItem {
  to: string;
  label: string;
  icon: IconName;
  roles: Role[];
  end?: boolean;
}

const NAV: { group: string; items: NavItem[] }[] = [
  {
    group: '',
    items: [
      { to: '/app', label: 'Inicio', icon: 'dashboard', roles: ['admin', 'agent'], end: true },
      { to: '/app', label: 'Inicio', icon: 'home', roles: ['customer'], end: true },
    ],
  },
  {
    group: 'Atención',
    items: [
      { to: '/app/incidents', label: 'Fallas', icon: 'incident', roles: ['admin', 'agent'] },
      { to: '/app/problems', label: 'Problemas recurrentes', icon: 'problem', roles: ['admin', 'agent'] },
      { to: '/app/changes', label: 'Actualizaciones', icon: 'change', roles: ['admin', 'agent'], end: true },
      { to: '/app/changes/calendar', label: 'Calendario', icon: 'calendar', roles: ['admin', 'agent'] },
    ],
  },
  {
    group: 'Servicios',
    items: [
      { to: '/app/requests', label: 'Pedidos', icon: 'request', roles: ['admin', 'agent'] },
      { to: '/app/catalog', label: '¿Qué puedo pedir?', icon: 'catalog', roles: ['admin', 'agent', 'customer'] },
      { to: '/app/incidents', label: 'Mis fallas reportadas', icon: 'incident', roles: ['customer'] },
      { to: '/app/requests', label: 'Mis pedidos', icon: 'request', roles: ['customer'] },
    ],
  },
  {
    group: 'Administración',
    items: [
      { to: '/app/cmdb', label: 'Equipos y sistemas', icon: 'cmdb', roles: ['admin', 'agent'] },
      { to: '/app/users', label: 'Personas y áreas', icon: 'users', roles: ['admin', 'agent'] },
    ],
  },
];


export default function AppLayout() {
  const { user, booting, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  const nav = useNavigate();

  useEffect(() => setOpen(false), [loc.pathname]);

  if (booting) return <Spinner label="Restaurando sesión…" />;
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname)}`} replace />;

  const theme = tenantTheme(user.tenant.id);

  return (
    <div className={`shell ${open ? 'nav-open' : ''}`} style={tenantStyle(user.tenant.id)}>
      <aside className="sidebar">
        <Logo to="/app" />
        {NAV.map((g) => {
          const items = g.items.filter((i) => i.roles.includes(user.role));
          if (!items.length) return null;
          return (
            <div key={g.group || 'root'}>
              {g.group && <div className="nav-group">{g.group}</div>}
              {items.map((i) => (
                <NavLink key={i.to + i.label} to={i.to} end={i.end} className="nav-link">
                  <Icon name={i.icon} />
                  {i.label}
                </NavLink>
              ))}
            </div>
          );
        })}
        <div className="sidebar-foot">
          <span className="tenant-mark">
            <Icon name={theme.icon} size={18} />
          </span>
          <div>
            <strong>{user.tenant.name}</strong>
            <span>{theme.tagline || 'Organización'}</span>
          </div>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <button className="icon-btn menu-toggle" onClick={() => setOpen((o) => !o)} aria-label="Abrir menú">
            <Icon name="menu" />
          </button>
          <span className="tenant-pill" title="Organización activa">
            <i>
              <Icon name={theme.icon} size={13} />
            </i>
            <span>{user.tenant.name}</span>
            {theme.tagline && <small>{theme.tagline}</small>}
          </span>
          <span className="grow" />
          <NotificationBell />
          <div className="user-chip">
            <Avatar name={user.full_name} size={32} />
            <div className="who">
              <strong>{user.full_name}</strong>
              <small>{ROLE[user.role]}</small>
            </div>
          </div>
          <button
            className="icon-btn"
            title="Cerrar sesión"
            aria-label="Cerrar sesión"
            onClick={() => {
              logout();
              nav('/login');
            }}
          >
            <Icon name="logout" />
          </button>
        </header>
        {MOCKED_SERVICES.length > 0 && (
          <div className="demo-banner">
            <Icon name="sparkle" size={14} />
            Versión de demostración con datos de ejemplo.
          </div>
        )}
        <main className="content page-enter" key={loc.pathname}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export function RoleGate({ roles, children }: { roles: Role[]; children: React.ReactNode }) {
  const { user } = useAuth();
  if (!user || !roles.includes(user.role)) return <Navigate to="/app" replace />;
  return <>{children}</>;
}
