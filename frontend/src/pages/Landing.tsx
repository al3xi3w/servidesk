import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Icon, type IconName } from '../components/Icon';
import { Logo } from '../components/Logo';
import { CountOnView, Reveal } from '../components/motion';
import { TENANT_THEMES } from '../lib/tenant';

// ------------------------------------------------------------------ Contenido

/** Los 5 problemas del día a día y cómo los resuelve ServiDesk. */
interface Case {
  id: string;
  icon: IconName;
  problem: string;
  who: string;
  kind: string;
  title: string;
  text: string;
  steps: [string, string, string, 'info' | 'accent' | 'warning' | 'success'][];
}

const CASES: Case[] = [
  {
    id: 'correo',
    icon: 'bell',
    problem: 'Un trabajador no puede ingresar a su correo',
    who: 'Lo reporta el propio trabajador',
    kind: 'Falla',
    title: 'Reportarlo toma un minuto, y nadie se olvida del caso',
    text: 'El trabajador entra al portal, describe qué le pasa y a cuántas personas afecta. ServiDesk le da un número de seguimiento y calcula qué tan urgente es.',
    steps: [
      ['Reporte', 'Desde el portal, sin llamadas ni correos sueltos', 'Reportada', 'info'],
      ['Asignación', 'Llega a la Mesa de Ayuda con su prioridad', 'Asignada', 'accent'],
      ['Atención', 'El técnico restablece la contraseña', 'En curso', 'warning'],
      ['Aviso', 'El trabajador recibe una notificación y confirma', 'Resuelta', 'success'],
    ],
  },
  {
    id: 'impresora',
    icon: 'server',
    problem: 'La impresora de contabilidad dejó de funcionar',
    who: 'Afecta a toda un área',
    kind: 'Falla que se repite',
    title: 'Si la falla vuelve, se busca la causa de fondo',
    text: 'Se resuelve como cualquier falla, pero cuando la misma impresora falla varias veces, ServiDesk lo detecta y abre un problema recurrente para que no vuelva a pasar.',
    steps: [
      ['Reporte', 'Contabilidad avisa que no puede imprimir', 'Reportada', 'info'],
      ['Se repite', 'Tercera falla de la misma impresora esta semana', 'Recurrente', 'warning'],
      ['Causa de fondo', 'Se descubre un controlador desactualizado', 'En análisis', 'accent'],
      ['Solución', 'Se corrige y se cierran todas las fallas juntas', 'Resuelto', 'success'],
    ],
  },
  {
    id: 'servidor',
    icon: 'bolt',
    problem: 'El servidor de la empresa está caído',
    who: 'Afecta a todos',
    kind: 'Falla urgente',
    title: 'ServiDesk se entera antes que tus trabajadores',
    text: 'Cuando un equipo o sistema registrado deja de responder, ServiDesk abre el reporte solo, con prioridad alta, y avisa de inmediato al equipo de infraestructura.',
    steps: [
      ['Detección', 'El servidor deja de responder', 'Automático', 'info'],
      ['Urgencia', 'Prioridad alta y plazo de atención corto', 'Urgente', 'warning'],
      ['Aviso', 'Infraestructura recibe la alerta al instante', 'Asignada', 'accent'],
      ['Restablecido', 'Queda registrado qué pasó y cómo se resolvió', 'Resuelta', 'success'],
    ],
  },
  {
    id: 'programa',
    icon: 'request',
    problem: 'Un trabajador necesita instalar un programa',
    who: 'No es una falla: es un pedido',
    kind: 'Pedido',
    title: 'Un catálogo con todo lo que se puede pedir',
    text: 'Programas, accesos, equipos o licencias: el trabajador elige del catálogo, completa un formulario corto y, si hace falta, su jefatura lo aprueba antes de atenderlo.',
    steps: [
      ['Pedido', 'Elige “Instalación de programa” en el catálogo', 'Enviado', 'info'],
      ['Aprobación', 'La jefatura aprueba con un clic', 'Aprobado', 'accent'],
      ['Atención', 'Un técnico instala el programa', 'En atención', 'warning'],
      ['Listo', 'El trabajador recibe el aviso de entrega', 'Completado', 'success'],
    ],
  },
  {
    id: 'actualizacion',
    icon: 'change',
    problem: 'La empresa quiere actualizar su sistema informático',
    who: 'Una mejora planificada',
    kind: 'Mejora o actualización',
    title: 'Actualizar sin detener el trabajo',
    text: 'La actualización se planifica: se indica qué se cambia, qué riesgo tiene y cómo volver atrás si algo sale mal. Un comité la aprueba y queda en el calendario.',
    steps: [
      ['Plan', 'Qué se actualiza, cuándo y con qué riesgo', 'Borrador', 'info'],
      ['Aprobación', 'El comité revisa y aprueba', 'Aprobada', 'accent'],
      ['Calendario', 'Se agenda fuera del horario de trabajo', 'Programada', 'warning'],
      ['Hecho', 'El inventario de sistemas se actualiza solo', 'Implementada', 'success'],
    ],
  },
];

const VERBS: [IconName, string, string][] = [
  ['plus', 'Registrar', 'Cada falla, pedido o mejora queda anotada con un número, quién la pidió y cuándo.'],
  ['layers', 'Organizar', 'Se clasifica y se ordena por urgencia: lo que detiene a toda la empresa va primero.'],
  ['users', 'Asignar', 'Llega al técnico o equipo correcto, sin pasar de mano en mano.'],
  ['clock', 'Hacer seguimiento', 'Todos ven en qué va su caso y cuánto falta para el plazo de atención.'],
  ['check', 'Resolver', 'Se documenta la solución y se avisa a quien lo reportó.'],
];

const FEATURES: [IconName, string, string][] = [
  ['incident', 'Reporte de fallas', 'Cuando algo deja de funcionar, se reporta en segundos y se atiende según su urgencia.'],
  ['request', 'Catálogo de pedidos', 'Programas, accesos y equipos con formularios simples y aprobación cuando hace falta.'],
  ['problem', 'Problemas recurrentes', 'Encuentra por qué una falla se repite y comparte una solución temporal mientras tanto.'],
  ['change', 'Mejoras y actualizaciones', 'Planifica cambios a los sistemas con aprobación y un calendario sin choques.'],
  ['cmdb', 'Inventario de equipos y sistemas', 'Computadoras, servidores, redes y aplicaciones, con quién es responsable de cada uno.'],
  ['clock', 'Plazos de atención', 'Cada caso tiene un plazo según su urgencia; ServiDesk avisa antes de que venza.'],
  ['bell', 'Avisos automáticos', 'Quien reporta, quien atiende y quien aprueba se enteran al momento de cada avance.'],
  ['chart', 'Tablero para la jefatura', 'Cuántos casos hay abiertos, cuáles son urgentes y cuántos se atienden a tiempo.'],
];

const ROLES: [IconName, string, string, string[]][] = [
  ['users', 'Trabajadores', 'Piden ayuda sin complicaciones', ['Reportan una falla en un minuto', 'Piden programas, accesos o equipos', 'Ven en qué va su caso']],
  ['bot', 'Técnicos de TI', 'Saben qué atender primero', ['Una lista ordenada por urgencia', 'Plazos visibles para cada caso', 'Notas internas y soluciones conocidas']],
  ['chart', 'Jefatura y administración', 'Tienen el control', ['Tablero con lo que está pasando', 'Aprueban pedidos y actualizaciones', 'Gestionan usuarios y equipos']],
];

const FAQ: [string, string][] = [
  ['¿Qué es ServiDesk?', 'Un sistema web para que las empresas administren y solucionen sus problemas tecnológicos: registrar lo que pasa, organizarlo, asignarlo a quien corresponde, hacerle seguimiento y resolverlo, todo desde una sola plataforma.'],
  ['¿Cuál es la diferencia entre una falla y un pedido?', 'Una falla es algo que dejó de funcionar (el correo, la impresora, el servidor). Un pedido es algo nuevo que alguien necesita (instalar un programa, un acceso, una laptop). ServiDesk atiende ambos, pero cada uno sigue su propio camino.'],
  ['¿Qué es un problema recurrente?', 'Es una falla que se repite. En vez de arreglarla una y otra vez, ServiDesk ayuda a encontrar la causa de fondo para que deje de pasar.'],
  ['¿Otras empresas pueden ver nuestra información?', 'No. Cada empresa ingresa con su propio código y solo ve sus datos. La información de cada organización está separada de la de las demás.'],
  ['¿Hay que instalar algo?', 'No. ServiDesk funciona en el navegador, desde cualquier computadora o celular, y está en la nube.'],
];

// ------------------------------------------------------------------ Página

export default function Landing() {
  const [caseId, setCaseId] = useState(CASES[0].id);
  const [menu, setMenu] = useState(false);
  const active = CASES.find((c) => c.id === caseId)!;

  return (
    <div className="lp">
      <nav className={`lp-nav ${menu ? 'open' : ''}`}>
        <div className="lp-container lp-nav-inner">
          <Logo />
          <div className="lp-nav-links" onClick={() => setMenu(false)}>
            <a href="#casos">Casos reales</a>
            <a href="#como-funciona">Cómo funciona</a>
            <a href="#que-incluye">Qué incluye</a>
            <a href="#faq">Preguntas</a>
          </div>
          <span className="grow" />
          <Link to="/login" className="hide-sm">
            Iniciar sesión
          </Link>
          <Link to="/login" className="btn btn-mint btn-sm hide-sm">
            Probar la demo
          </Link>
          <button className="icon-btn lp-menu-btn" onClick={() => setMenu((m) => !m)} aria-label="Menú">
            <Icon name={menu ? 'x' : 'menu'} />
          </button>
        </div>
      </nav>

      <header className="lp-hero">
        <div className="lp-container lp-hero-inner">
          <div>
            <span className="eyebrow hero-fade" style={{ animationDelay: '60ms' }}>
              <Icon name="sparkle" size={15} /> Mesa de ayuda de TI para empresas
            </span>
            <h1 className="hero-title">
              {['Todos', 'los', 'problemas', 'tecnológicos', 'de', 'tu', 'empresa,'].map((w, i) => (
                <span className="w" key={i} style={{ animationDelay: `${120 + i * 70}ms` }}>
                  {w}
                </span>
              ))}
              {['en', 'un', 'solo'].map((w, i) => (
                <span className="w" key={'b' + i} style={{ animationDelay: `${620 + i * 70}ms` }}>
                  {w}
                </span>
              ))}
              <span className="w" style={{ animationDelay: '830ms' }}>
                <em>lugar.</em>
              </span>
            </h1>
            <p className="lead hero-fade" style={{ animationDelay: '1000ms' }}>
              Correos que no abren, impresoras que fallan, servidores caídos, programas por instalar. ServiDesk te permite{' '}
              <b>registrar, organizar, asignar, hacer seguimiento y resolver</b> cada caso desde una sola plataforma.
            </p>
            <div className="cta-row hero-fade" style={{ animationDelay: '1150ms' }}>
              <Link to="/login" className="btn btn-mint btn-lg">
                Probar la demo <Icon name="arrow" />
              </Link>
              <a href="#casos" className="btn btn-outline-light btn-lg">
                Ver un ejemplo
              </a>
            </div>
            <div className="trust hero-fade" style={{ animationDelay: '1300ms' }}>
              <span>
                <Icon name="check" size={15} /> Sin instalar nada
              </span>
              <span>
                <Icon name="check" size={15} /> Cada empresa ve solo sus datos
              </span>
              <span>
                <Icon name="check" size={15} /> Avisos automáticos
              </span>
            </div>
          </div>
          <DayBoard />
        </div>
      </header>

      <div className="lp-logos">
        <div className="lp-container">
          <small>Empresas que ya lo usan</small>
          {[
            ['andina', 'Andina Retail'],
            ['pacifico', 'Clínica Pacífico'],
            ['unitec', 'UniTec Campus'],
          ].map(([id, name], i) => (
            <strong key={id} className="tenant-logo" style={{ animationDelay: `${i * 120}ms`, ['--tc' as string]: TENANT_THEMES[id].color }}>
              <span className="tl-mark">
                <Icon name={TENANT_THEMES[id].icon} size={14} />
              </span>
              {name}
            </strong>
          ))}
        </div>
      </div>

      <section className="lp-section">
        <div className="lp-container story">
          <Reveal className="section-head">
            <span className="eyebrow dark-text">Imagina tu empresa</span>
            <h2>200 trabajadores. Computadoras, impresoras, servidores, redes y aplicaciones.</h2>
            <p>Un día cualquiera, todo esto pasa al mismo tiempo. Sin un sistema, los casos llegan por WhatsApp, correo o pasillo, y algunos se pierden.</p>
          </Reveal>
          <div className="problem-list">
            {CASES.map((c, i) => (
              <Reveal key={c.id} className="problem-item" delay={i * 90}>
                <span className="pi-ic">
                  <Icon name={c.icon} size={20} />
                </span>
                <div>
                  <strong>{c.problem}</strong>
                  <small>{c.who}</small>
                </div>
                <a href="#casos" className="pi-kind" onClick={() => setCaseId(c.id)}>
                  {c.kind} <Icon name="arrow" size={14} />
                </a>
              </Reveal>
            ))}
          </div>
          <Reveal className="story-q" delay={200}>
            <h3>¿Cómo administra la empresa todos esos problemas?</h3>
            <p>
              Aquí aparece <b>ServiDesk</b>.
            </p>
          </Reveal>
        </div>
      </section>

      <section className="lp-section dark" id="casos">
        <div className="lp-container">
          <Reveal className="section-head">
            <span className="eyebrow">Casos reales</span>
            <h2>Así resuelve ServiDesk cada uno</h2>
            <p>Elige un caso y mira el camino que sigue, desde que alguien lo reporta hasta que queda resuelto.</p>
          </Reveal>
          <div className="tabs-bar" role="tablist">
            {CASES.map((c) => (
              <button key={c.id} role="tab" aria-selected={caseId === c.id} className={caseId === c.id ? 'on' : ''} onClick={() => setCaseId(c.id)}>
                <Icon name={c.icon} size={15} /> {c.kind}
              </button>
            ))}
          </div>
          <div className="tab-panel" role="tabpanel" key={active.id}>
            <div>
              <span className="case-problem">“{active.problem}”</span>
              <h3>{active.title}</h3>
              <p>{active.text}</p>
              <Link to="/login" className="btn btn-mint">
                Probarlo en la demo <Icon name="arrow" />
              </Link>
            </div>
            <div className="tab-visual">
              {active.steps.map(([title, sub, badge, tone], i) => (
                <div className="flow-step" key={title} style={{ animationDelay: `${i * 110}ms` }}>
                  <span className="n">{i + 1}</span>
                  <div>
                    {title}
                    <small>{sub}</small>
                  </div>
                  <span className={`badge tone-${tone}`}>
                    <span className="dot" />
                    {badge}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="lp-section" id="como-funciona">
        <div className="lp-container">
          <Reveal className="section-head center">
            <span className="eyebrow dark-text">Cómo funciona</span>
            <h2>Cinco pasos, siempre los mismos</h2>
            <p>No importa si es una falla, un pedido o una actualización: todo sigue un camino claro.</p>
          </Reveal>
          <div className="verbs">
            {VERBS.map(([icon, title, text], i) => (
              <Reveal key={title} className="verb" delay={i * 110}>
                <span className="verb-ic">
                  <Icon name={icon} size={22} />
                </span>
                <span className="verb-n">0{i + 1}</span>
                <h3>{title}</h3>
                <p>{text}</p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="lp-section alt" id="que-incluye">
        <div className="lp-container">
          <Reveal className="section-head center">
            <span className="eyebrow dark-text">Qué incluye</span>
            <h2>Todo lo que necesita el área de TI</h2>
          </Reveal>
          <div className="cap-grid">
            {FEATURES.map(([icon, title, text], i) => (
              <Reveal as="article" className="cap" key={title} delay={(i % 4) * 80}>
                <span className="ic">
                  <Icon name={icon} size={20} />
                </span>
                <h3>{title}</h3>
                <p>{text}</p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="lp-section">
        <div className="lp-container">
          <Reveal className="section-head center">
            <span className="eyebrow dark-text">Para cada persona</span>
            <h2>Cada quien ve lo que necesita</h2>
          </Reveal>
          <div className="roles-grid">
            {ROLES.map(([icon, title, sub, items], i) => (
              <Reveal key={title} className="role-card" delay={i * 100}>
                <span className="ic">
                  <Icon name={icon} size={22} />
                </span>
                <h3>{title}</h3>
                <p className="muted">{sub}</p>
                <ul className="role-list">
                  {items.map((it) => (
                    <li key={it}>
                      <Icon name="check" size={16} /> {it}
                    </li>
                  ))}
                </ul>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="lp-section dark">
        <div className="lp-container">
          <Reveal className="section-head">
            <span className="eyebrow">Resultados</span>
            <h2>Cuando cada caso tiene dueño y plazo, los números cambian</h2>
          </Reveal>
          <Reveal className="stats stats-dark">
            <div className="stat">
              <strong>
                −<CountOnView value={38} suffix={<span>%</span>} />
              </strong>
              <p>de tiempo para resolver una falla</p>
            </div>
            <div className="stat">
              <strong>
                <CountOnView value={94} suffix={<span>%</span>} />
              </strong>
              <p>de casos atendidos dentro del plazo</p>
            </div>
            <div className="stat">
              <strong>
                <CountOnView value={0} />
              </strong>
              <p>casos perdidos entre correos y mensajes</p>
            </div>
            <div className="stat">
              <strong>
                <CountOnView value={24} suffix={<span>/7</span>} />
              </strong>
              <p>portal disponible para los trabajadores</p>
            </div>
          </Reveal>
        </div>
      </section>

      <section className="lp-section">
        <div className="lp-container quote">
          <Reveal>
            <blockquote>“Antes los pedidos llegaban por WhatsApp y se perdían. Ahora cada trabajador sabe en qué va su caso, y nosotros sabemos qué atender primero.”</blockquote>
            <cite>Jefatura de Sistemas · Andina Retail</cite>
          </Reveal>
          <div className="quote-stats">
            <Reveal delay={100}>
              <strong>
                <CountOnView value={200} />
              </strong>
              <span>trabajadores atendidos desde un solo lugar</span>
            </Reveal>
            <Reveal delay={200}>
              <strong>
                <CountOnView value={5} />
              </strong>
              <span>tipos de caso, un mismo proceso</span>
            </Reveal>
            <Reveal delay={300}>
              <strong>1 minuto</strong>
              <span>para reportar una falla</span>
            </Reveal>
          </div>
        </div>
      </section>

      <section className="lp-section alt" id="faq">
        <div className="lp-container">
          <Reveal className="section-head center">
            <span className="eyebrow dark-text">Preguntas frecuentes</span>
            <h2>Lo que suelen preguntarnos</h2>
          </Reveal>
          <div className="faq">
            {FAQ.map(([q, a]) => (
              <details key={q}>
                <summary>
                  {q} <Icon name="chevron" />
                </summary>
                <p>{a}</p>
              </details>
            ))}
          </div>
        </div>
      </section>

      <section className="lp-section">
        <div className="lp-container">
          <Reveal className="cta-band">
            <div>
              <h2>Deja de perseguir los problemas por correo y WhatsApp.</h2>
              <p>Entra a la demo como trabajador, técnico o jefatura y recorre los casos de ejemplo.</p>
            </div>
            <Link to="/login" className="btn btn-mint btn-lg">
              Abrir la demo <Icon name="arrow" />
            </Link>
          </Reveal>
        </div>
      </section>

      <footer className="lp-footer">
        <div className="lp-container">
          <div className="lp-footer-grid">
            <div>
              <Logo />
              <p style={{ marginTop: 14, maxWidth: 320 }}>Para que las empresas administren y solucionen sus problemas tecnológicos desde una sola plataforma.</p>
            </div>
            <div>
              <h4>Qué resuelve</h4>
              <ul>
                <li><a href="#casos">Fallas</a></li>
                <li><a href="#casos">Pedidos</a></li>
                <li><a href="#casos">Actualizaciones</a></li>
              </ul>
            </div>
            <div>
              <h4>Conoce más</h4>
              <ul>
                <li><a href="#como-funciona">Cómo funciona</a></li>
                <li><a href="#que-incluye">Qué incluye</a></li>
                <li><a href="#faq">Preguntas frecuentes</a></li>
              </ul>
            </div>
            <div>
              <h4>Acceso</h4>
              <ul>
                <li><Link to="/login">Iniciar sesión</Link></li>
              </ul>
            </div>
          </div>
          <div className="bottom">
            <span>© {new Date().getFullYear()} ServiDesk</span>
            <span>Mesa de ayuda de TI para empresas</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

// ------------------------------------------------------------------ Tablero animado del hero

const DAY: [IconName, string, string][] = [
  ['bell', 'No puedo ingresar a mi correo', 'Ventas · Rosa M.'],
  ['server', 'La impresora de contabilidad no imprime', 'Contabilidad'],
  ['bolt', 'Servidor principal sin respuesta', 'Detectado automáticamente'],
  ['request', 'Instalar Excel avanzado', 'Finanzas · Luis T.'],
  ['change', 'Actualizar el sistema de ventas', 'Jefatura de TI'],
];
const STAGES: [string, string][] = [
  ['Reportado', 'info'],
  ['Asignado', 'accent'],
  ['En curso', 'warning'],
  ['Resuelto', 'success'],
];

/** "Un día cualquiera": los 5 casos avanzan de reportado a resuelto. */
function DayBoard() {
  const reduced = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  const [tick, setTick] = useState(reduced ? 99 : 0);
  useEffect(() => {
    if (reduced) return;
    const t = setInterval(() => setTick((n) => (n >= DAY.length + STAGES.length + 2 ? 0 : n + 1)), 1100);
    return () => clearInterval(t);
  }, [reduced]);
  const done = DAY.filter((_, i) => tick - i >= STAGES.length - 1).length;

  return (
    <div className="hero-visual" aria-hidden="true">
      <div className="day-board">
        <div className="day-head">
          <div>
            <small>Hoy en tu empresa</small>
            <strong>5 casos · {done} resueltos</strong>
          </div>
          <span className="day-ring" style={{ ['--p' as string]: `${(done / DAY.length) * 100}%` }}>
            {Math.round((done / DAY.length) * 100)}%
          </span>
        </div>
        {DAY.map(([icon, title, who], i) => {
          const stage = Math.max(0, Math.min(STAGES.length - 1, tick - i));
          const [label, tone] = STAGES[stage];
          return (
            <div className={`day-row ${stage === STAGES.length - 1 ? 'done' : ''}`} key={title}>
              <span className="day-ic">
                <Icon name={icon} size={16} />
              </span>
              <div className="day-main">
                <span className="t">{title}</span>
                <small>{who}</small>
                <span className="day-bar">
                  <span style={{ width: `${((stage + 1) / STAGES.length) * 100}%` }} />
                </span>
              </div>
              <span className={`badge tone-${tone}`} key={label}>
                <span className="dot" />
                {label}
              </span>
            </div>
          );
        })}
      </div>
      <div className="mock-float">
        <span className="ic">
          <Icon name="bell" />
        </span>
        <div>
          <strong>“Tu caso fue resuelto”</strong>
          <div className="muted" style={{ fontSize: 12 }}>
            Aviso enviado a Rosa M. · hace 2 s
          </div>
        </div>
      </div>
    </div>
  );
}
