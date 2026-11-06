import type { IconName } from '../components/Icon';

/** Tema por tenant: el diseño pide que al entrar se note a simple vista en qué organización estás. */
export interface TenantTheme {
  color: string;
  hover: string;
  soft: string;
  icon: IconName;
  tagline: string;
}

export const TENANT_THEMES: Record<string, TenantTheme> = {
  andina: { color: '#c2410c', hover: '#9a3412', soft: '#fff1e8', icon: 'bag', tagline: 'Cadena de tiendas' },
  pacifico: { color: '#0369a1', hover: '#075985', soft: '#e6f3fb', icon: 'cross', tagline: 'Salud' },
  unitec: { color: '#6d28d9', hover: '#5b21b6', soft: '#f1ebfd', icon: 'cap', tagline: 'Universidad' },
};

const DEFAULT: TenantTheme = { color: '#0e8a72', hover: '#0b6e5c', soft: '#e3f6f0', icon: 'layers', tagline: '' };

export function tenantTheme(id: string | undefined): TenantTheme {
  return (id && TENANT_THEMES[id]) || DEFAULT;
}

/** Variables CSS que reemplazan el color primario de la consola. */
export function tenantStyle(id: string | undefined): Record<string, string> {
  const t = tenantTheme(id);
  return { '--tenant': t.color, '--primary': t.color, '--primary-hover': t.hover, '--primary-soft': t.soft };
}
