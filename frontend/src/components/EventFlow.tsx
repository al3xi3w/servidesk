/**
 * Diagrama animado de la arquitectura de eventos: 6 microservicios → SNS itsm-events → colas SQS → consumidores.
 * - mode "loop": animación continua de ejemplo (landing).
 * - mode "live": anima cada evento real que recibe (pulses), con el servicio de origen y las colas destino.
 */
import { useEffect, useRef } from 'react';
import type { ServiceKey } from '../mocks/events';

export const SERVICES: { key: ServiceKey; name: string; db: string; label: string }[] = [
  { key: 'identity', name: 'ms-identity', db: 'db_identity', label: 'Identidad' },
  { key: 'cmdb', name: 'ms-cmdb', db: 'db_cmdb', label: 'CMDB' },
  { key: 'incidents', name: 'ms-incidents', db: 'db_incidents', label: 'Incidentes' },
  { key: 'problems', name: 'ms-problems', db: 'db_problems', label: 'Problemas' },
  { key: 'changes', name: 'ms-changes', db: 'db_changes', label: 'Cambios' },
  { key: 'requests', name: 'ms-requests', db: 'db_requests', label: 'Solicitudes' },
];

export const QUEUES: { queue: string; service: ServiceKey }[] = [
  { queue: 'identity-notify-q', service: 'identity' },
  { queue: 'cmdb-changes-q', service: 'cmdb' },
  { queue: 'incidents-ci-q', service: 'incidents' },
  { queue: 'incidents-problem-q', service: 'incidents' },
  { queue: 'incidents-kedb-q', service: 'incidents' },
  { queue: 'problems-incidents-q', service: 'problems' },
  { queue: 'problems-changes-q', service: 'problems' },
  { queue: 'requests-fulfillment-q', service: 'requests' },
];

const SX = (i: number) => 95 + i * 162;
const QX = (i: number) => 66 + i * 124;
const pubPath = (i: number) => `M ${SX(i)} 112 C ${SX(i)} 165, 500 140, 500 188`;
const fanPath = (i: number) => `M 500 244 C 500 292, ${QX(i)} 290, ${QX(i)} 338`;

export interface Pulse {
  id: string;
  source: ServiceKey;
  queues: string[];
  label: string;
}

/** Punto que recorre un camino una vez, al montarse (SMIL con begin="indefinite"). */
function Dot({ path, delay = 0, dur = 0.7 }: { path: string; delay?: number; dur?: number }) {
  const ref = useRef<SVGAnimateMotionElement>(null);
  useEffect(() => {
    const t = setTimeout(() => ref.current?.beginElement(), delay * 1000);
    return () => clearTimeout(t);
  }, [delay]);
  return (
    <circle r="6" className="flow-dot once" style={{ animationDelay: `${delay}s`, animationDuration: `${dur}s` }}>
      <animateMotion ref={ref} begin="indefinite" dur={`${dur}s`} path={path} fill="freeze" />
    </circle>
  );
}

export function EventFlow({
  mode,
  pulses = [],
  counts,
  dark,
}: {
  mode: 'loop' | 'live';
  pulses?: Pulse[];
  counts?: Partial<Record<ServiceKey, number>>;
  dark?: boolean;
}) {
  const last = pulses[0];
  const activeSource = last?.source;
  const activeQueues = new Set(last?.queues ?? []);
  const activeConsumers = new Set(QUEUES.filter((q) => activeQueues.has(q.queue)).map((q) => q.service));

  return (
    <div className={`flow ${dark ? 'flow-dark' : ''}`}>
      <svg viewBox="0 0 1000 430" role="img" aria-label="Flujo de eventos entre los 6 microservicios mediante SNS y SQS">
        <defs>
          <linearGradient id="snsGrad" x1="0" x2="1">
            <stop offset="0" stopColor="var(--flow-a)" />
            <stop offset="1" stopColor="var(--flow-b)" />
          </linearGradient>
        </defs>

        {SERVICES.map((s, i) => (
          <path key={s.key} d={pubPath(i)} className={`flow-line ${activeSource === s.key ? 'on' : ''}`} />
        ))}
        {QUEUES.map((q, i) => (
          <path key={q.queue} d={fanPath(i)} className={`flow-line ${activeQueues.has(q.queue) ? 'on' : ''}`} />
        ))}

        {SERVICES.map((s, i) => (
          <g
            key={s.key}
            className={`flow-node ${activeSource === s.key ? 'pub' : ''} ${mode === 'live' && activeConsumers.has(s.key) ? 'sub' : ''}`}
            transform={`translate(${SX(i) - 72} 40)`}
          >
            <rect width="144" height="72" rx="14" />
            <text x="72" y="28" className="t1">
              {s.label}
            </text>
            <text x="72" y="46" className="t2">
              {s.name}
            </text>
            <text x="72" y="62" className="t3">
              {counts?.[s.key] !== undefined ? `${counts[s.key]!.toLocaleString('es-PE')} registros` : s.db}
            </text>
          </g>
        ))}

        <g className={`flow-sns ${last ? 'pulse' : ''}`} key={'sns-' + (last?.id ?? 'idle')} transform="translate(350 188)">
          <rect width="300" height="56" rx="28" fill="url(#snsGrad)" />
          <text x="150" y="25" className="s1">
            SNS · itsm-events
          </text>
          <text x="150" y="42" className="s2">
            {last ? last.label : 'fan-out con filtro por eventType'}
          </text>
        </g>

        {QUEUES.map((q, i) => (
          <g key={q.queue} className={`flow-queue ${activeQueues.has(q.queue) ? 'on' : ''}`} transform={`translate(${QX(i) - 58} 338)`}>
            <rect width="116" height="40" rx="9" />
            <text x="58" y="18" className="q1">
              {q.queue.replace(/-q$/, '')}
            </text>
            <text x="58" y="32" className="q2">
              SQS + DLQ
            </text>
            <text x="58" y="62" className="q3">
              → {SERVICES.find((s) => s.key === q.service)!.name}
            </text>
          </g>
        ))}

        {mode === 'loop' &&
          SERVICES.map((s, i) => (
            <circle key={'l' + s.key} r="5" className="flow-dot" opacity="0">
              <animateMotion dur="1.4s" begin={`${i * 0.9}s`} repeatCount="indefinite" path={pubPath(i)} />
              <animate attributeName="opacity" dur="1.4s" begin={`${i * 0.9}s`} repeatCount="indefinite" values="0;1;1;0" />
            </circle>
          ))}
        {mode === 'loop' &&
          QUEUES.map((q, i) => (
            <circle key={'f' + q.queue} r="5" className="flow-dot alt" opacity="0">
              <animateMotion dur="1.4s" begin={`${0.6 + i * 0.7}s`} repeatCount="indefinite" path={fanPath(i)} />
              <animate attributeName="opacity" dur="1.4s" begin={`${0.6 + i * 0.7}s`} repeatCount="indefinite" values="0;1;1;0" />
            </circle>
          ))}

        {mode === 'live' &&
          last && (
            <g key={'dots-' + last.id}>
              <Dot path={pubPath(SERVICES.findIndex((s) => s.key === last.source))} />
              {QUEUES.map((q, i) => (activeQueues.has(q.queue) ? <Dot key={q.queue} path={fanPath(i)} delay={0.65} /> : null))}
            </g>
          )}
      </svg>
    </div>
  );
}
