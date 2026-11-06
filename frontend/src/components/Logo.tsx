import { Link } from 'react-router-dom';

export function Logo({ to = '/', sub }: { to?: string; sub?: string }) {
  return (
    <Link to={to} className="logo" aria-label="ServiDesk">
      <span className="logo-mark">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 15c2.5 3 5.5 4 8 4s5.5-1 8-4M7 10.5a5 5 0 0 1 10 0" />
          <circle cx="12" cy="10.5" r="1.4" fill="currentColor" />
        </svg>
      </span>
      ServiDesk
      {sub && <small>{sub}</small>}
    </Link>
  );
}
