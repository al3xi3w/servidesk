/** Iconos de línea propios (24×24, trazo 1.8) para no depender de librerías externas. */
const PATHS: Record<string, string> = {
  dashboard: 'M3 13h8V3H3zM13 21h8v-6h-8zM13 3v8h8V3zM3 21h8v-4H3z',
  incident: 'M12 3 2 20h20L12 3zM12 10v4M12 17.5v.01',
  problem: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-5-5M11 8v3l2 2',
  change: 'M4 7h13l-3-3M20 17H7l3 3',
  calendar: 'M4 5h16v16H4zM4 10h16M9 3v4M15 3v4',
  catalog: 'M3 7l9-4 9 4-9 4-9-4zM3 12l9 4 9-4M3 17l9 4 9-4',
  request: 'M6 3h9l4 4v14H6zM14 3v5h5M9 13h7M9 17h5',
  cmdb: 'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6',
  users: 'M16 20v-1.5a3.5 3.5 0 0 0-3.5-3.5h-5A3.5 3.5 0 0 0 4 18.5V20M10 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM20 20v-1.5a3.5 3.5 0 0 0-2.5-3.35M15.5 4.15a3.5 3.5 0 0 1 0 6.7',
  home: 'M3 11l9-8 9 8M5 9.5V21h14V9.5',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-4.35-4.35',
  plus: 'M12 5v14M5 12h14',
  logout: 'M15 4h4v16h-4M10 8l-4 4 4 4M6 12h11',
  arrow: 'M5 12h14M13 6l6 6-6 6',
  back: 'M19 12H5M11 18l-6-6 6-6',
  check: 'M5 12.5l4.5 4.5L19 7',
  x: 'M6 6l12 12M18 6 6 18',
  clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 2',
  bolt: 'M13 2 4 14h7l-1 8 9-12h-7z',
  shield: 'M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z',
  layers: 'M12 3 2 8l10 5 10-5-10-5zM2 16l10 5 10-5',
  chart: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  bell: 'M6 9a6 6 0 1 1 12 0c0 6 2.5 8 2.5 8h-17S6 15 6 9zM10 21h4',
  cloud: 'M7 18a4.5 4.5 0 0 1-.5-9A6 6 0 0 1 18 8.5a4.75 4.75 0 0 1-.5 9.5z',
  book: 'M4 4h6a3 3 0 0 1 3 3v13a2 2 0 0 0-2-2H4zM20 4h-6a3 3 0 0 0-3 3v13a2 2 0 0 1 2-2h7z',
  bot: 'M5 9h14v10H5zM12 5v4M9 14h.01M15 14h.01M2 13v3M22 13v3M12 3.5v.01',
  link: 'M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1',
  menu: 'M4 6h16M4 12h16M4 18h16',
  chevron: 'M9 6l6 6-6 6',
  server: 'M4 4h16v6H4zM4 14h16v6H4zM8 7h.01M8 17h.01',
  bag: 'M5 8h14l-1 12H6zM9 8V6a3 3 0 0 1 6 0v2',
  cross: 'M9 3h6v6h6v6h-6v6H9v-6H3V9h6z',
  cap: 'M2 9l10-5 10 5-10 5zM6 11v5c3 2 9 2 12 0v-5M22 9v6',
  queue: 'M3 6h18M3 12h18M3 18h12',
  sparkle: 'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7z',
};

export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 18, className }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
