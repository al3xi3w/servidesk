import { useState, type FormEvent } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { ApiError, MOCKED_SERVICES } from '../api';
import { useAuth } from '../auth/AuthContext';
import { Icon } from '../components/Icon';
import { Logo } from '../components/Logo';
import { Field, fieldErrors } from '../components/ui';
import { ROLE } from '../lib/format';
import { demoAccounts, resetDemoData, TENANTS } from '../mocks/db';
import { TENANT_THEMES } from '../lib/tenant';

export default function Login() {
  const { user, login } = useAuth();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const [tenant, setTenant] = useState('andina');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(params.get('expired') ? 'Tu sesión expiró. Inicia sesión de nuevo.' : null);
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [resetDone, setResetDone] = useState(false);
  const showDemo = MOCKED_SERVICES.includes('identity');

  if (user) return <Navigate to="/app" replace />;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setErrs({});
    try {
      await login({ tenant_code: tenant, email, password });
      nav(params.get('next') ?? '/app', { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.code === 'INVALID_CREDENTIALS') setError('Organización, email o contraseña incorrectos');
      else if (err instanceof ApiError && err.code === 'VALIDATION_ERROR') setErrs(fieldErrors(err));
      else setError(err instanceof ApiError ? err.message : 'No se pudo iniciar sesión');
    } finally {
      setBusy(false);
    }
  }

  function fill(t: (typeof TENANTS)[number], mail: string) {
    setTenant(t.id);
    setEmail(mail);
    setPassword(t.password);
  }

  const demoTenant = TENANTS.find((t) => t.id === tenant) ?? TENANTS[0];

  return (
    <div className="auth-page">
      <aside className="auth-aside">
        <Logo />
        <div>
          <h2>Todos los problemas tecnológicos de tu empresa, en un solo lugar.</h2>
          <p>Ingresa con el código de tu empresa. Solo verás la información de tu organización.</p>
        </div>
        <small style={{ color: 'rgba(255,255,255,.5)' }}>ServiDesk · Mesa de ayuda de TI</small>
      </aside>

      <main className="auth-main">
        <form className="auth-card" onSubmit={onSubmit} noValidate>
          <div>
            <h1>Iniciar sesión</h1>
            <p className="muted" style={{ marginTop: 6 }}>
              Entra para reportar, pedir o atender casos de TI.
            </p>
          </div>

          {error && <div className="form-error">{error}</div>}

          <Field label="Código de tu empresa" error={errs.tenant_code} hint="Por ejemplo: andina, pacifico o unitec">
            <input className="input" value={tenant} onChange={(e) => setTenant(e.target.value.toLowerCase())} autoComplete="organization" required />
          </Field>
          <Field label="Correo electrónico" error={errs.email}>
            <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required />
          </Field>
          <Field label="Contraseña" error={errs.password}>
            <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
          </Field>

          <button className="btn btn-primary btn-lg" disabled={busy || !email || !password || !tenant}>
            {busy ? 'Ingresando…' : 'Ingresar'}
          </button>

          {showDemo && (
            <div className="demo-box">
              <h3>
                <Icon name="sparkle" size={14} /> Cuentas de demostración
              </h3>
              <div className="demo-tenants">
                {TENANTS.map((t) => (
                  <button type="button" key={t.id} className={tenant === t.id ? 'on' : ''} style={{ ['--tc' as string]: TENANT_THEMES[t.id].color }} onClick={() => fill(t, demoAccounts(t)[1].email)}>
                    <span className="tl-mark">
                      <Icon name={TENANT_THEMES[t.id].icon} size={13} />
                    </span>
                    <strong>{t.name}</strong>
                    <span className="muted mono">{t.id}</span>
                  </button>
                ))}
              </div>
              <div className="demo-roles">
                {demoAccounts(demoTenant).map((a) => (
                  <button type="button" key={a.role} className={`chip ${email === a.email ? 'on' : ''}`} onClick={() => fill(demoTenant, a.email)}>
                    {ROLE[a.role]}
                  </button>
                ))}
              </div>
              <div className="row between" style={{ fontSize: 12, marginTop: 8 }}>
                <span className="muted">
                  Contraseña: <span className="mono">{demoTenant.password}</span>
                </span>
                <button
                  type="button"
                  className="link-btn"
                  style={{ fontSize: 12 }}
                  onClick={() => {
                    resetDemoData();
                    setError(null);
                    setResetDone(true);
                  }}
                >
                  {resetDone ? 'Datos restablecidos ✓' : 'Restablecer datos de demo'}
                </button>
              </div>
            </div>
          )}
        </form>
      </main>
    </div>
  );
}
