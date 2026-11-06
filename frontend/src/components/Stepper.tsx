import { Fragment } from 'react';

/** Flujo lineal de estados; marca como completados los anteriores al actual. */
export function Stepper<K extends string>({ steps, current, failed }: { steps: [K, string][]; current: K; failed?: boolean }) {
  const idx = steps.findIndex(([k]) => k === current);
  return (
    <div className="stepper">
      {steps.map(([k, label], n) => {
        const state = n < idx ? 'done' : n === idx ? 'current' : '';
        return (
          <Fragment key={k}>
            {n > 0 && <span className={`ln ${n <= idx ? 'done' : ''}`} />}
            <span className={`st ${state}`} style={failed && n === idx ? { color: 'var(--danger)' } : undefined}>
              <i>{n < idx ? '✓' : n + 1}</i>
              {label}
            </span>
          </Fragment>
        );
      })}
    </div>
  );
}
