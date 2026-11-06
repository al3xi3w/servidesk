import type { SortOrder } from '../types/api';

/** Encabezado de tabla que alterna el orden del campo. */
export function SortHeader<F extends string>({ field, label, sort, onSort }: { field: F; label: string; sort: [F, SortOrder]; onSort: (s: [F, SortOrder]) => void }) {
  const active = sort[0] === field;
  return (
    <th aria-sort={active ? (sort[1] === 'asc' ? 'ascending' : 'descending') : undefined}>
      <button onClick={() => onSort([field, active && sort[1] === 'desc' ? 'asc' : 'desc'])}>
        {label}
        <span style={{ opacity: active ? 1 : 0.25 }}>{active && sort[1] === 'asc' ? '↑' : '↓'}</span>
      </button>
    </th>
  );
}
