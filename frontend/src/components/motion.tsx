import { useEffect, useRef, useState, type ReactNode } from 'react';

const reduced = () => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

/** Anima un número desde su valor anterior hasta `value`. */
export function useCountUp(value: number, duration = 900): number {
  const [shown, setShown] = useState(reduced() ? value : 0);
  const from = useRef(0);
  useEffect(() => {
    if (reduced()) {
      setShown(value);
      return;
    }
    const start = performance.now();
    const a = from.current;
    let raf = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - start) / duration);
      const eased = 1 - Math.pow(1 - k, 3);
      setShown(Math.round(a + (value - a) * eased));
      if (k < 1) raf = requestAnimationFrame(tick);
      else from.current = value;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, duration]);
  return shown;
}

export function CountUp({ value, format = (n) => n.toLocaleString('es-PE') }: { value: number; format?: (n: number) => string }) {
  return <>{format(useCountUp(value))}</>;
}

/** true cuando el elemento entra en pantalla (una sola vez). */
export function useInView<T extends Element>(threshold = 0.15): [React.RefObject<T | null>, boolean] {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || seen) return;
    if (!('IntersectionObserver' in window)) return setSeen(true);
    const io = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) {
          setSeen(true);
          io.disconnect();
        }
      },
      { threshold, rootMargin: '0px 0px -40px 0px' },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [seen, threshold]);
  return [ref, seen];
}

/** Aparece con un desplazamiento suave al hacer scroll. */
export function Reveal({ children, delay = 0, className = '', as: Tag = 'div' }: { children: ReactNode; delay?: number; className?: string; as?: 'div' | 'section' | 'article' }) {
  const [ref, seen] = useInView<HTMLDivElement>();
  return (
    <Tag ref={ref} className={`reveal ${seen ? 'in' : ''} ${className}`} style={{ transitionDelay: `${delay}ms` }}>
      {children}
    </Tag>
  );
}

/** Número que cuenta solo cuando se ve. */
export function CountOnView({ value, suffix }: { value: number; suffix?: ReactNode }) {
  const [ref, seen] = useInView<HTMLSpanElement>();
  const n = useCountUp(seen ? value : 0, 1200);
  return (
    <span ref={ref}>
      {n.toLocaleString('es-PE')}
      {suffix}
    </span>
  );
}
