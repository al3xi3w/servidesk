import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { requestService } from '../../api';
import { Icon, type IconName } from '../../components/Icon';
import { Badge, Empty, ErrorBox, Field, fieldErrors, Modal, PageHeader, Spinner, useToast } from '../../components/ui';
import { useAsync } from '../../lib/hooks';
import type { CatalogFormField, CatalogItem, RequestFormData } from '../../types/api';

const CATEGORY_ICON: Record<string, IconName> = {
  Hardware: 'server',
  Software: 'layers',
  Accesos: 'shield',
  Colaboración: 'users',
  Personas: 'users',
};

export default function Catalog() {
  const nav = useNavigate();
  const catalog = useAsync(() => requestService.catalog(), []);
  const [category, setCategory] = useState<number | null>(null);
  const [search, setSearch] = useState('');
  const [ordering, setOrdering] = useState<CatalogItem | null>(null);

  const categories = useMemo(() => {
    const m = new Map<number, string>();
    catalog.data?.forEach((c) => m.set(c.category_id, c.category_name));
    return [...m.entries()];
  }, [catalog.data]);

  const items = (catalog.data ?? []).filter(
    (c) => (category === null || c.category_id === category) && (!search || c.name.toLowerCase().includes(search.toLowerCase()) || c.category_name.toLowerCase().includes(search.toLowerCase())),
  );

  return (
    <>
      <PageHeader title="¿Qué necesitas?" subtitle="Elige del catálogo: cada pedido llega al área correcta con toda la información." />
      <div className="row gap wrap">
        <div className="search" style={{ width: 300, maxWidth: '100%' }}>
          <Icon name="search" size={16} />
          <input className="input" placeholder="Buscar: laptop, VPN, programa…" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <div className="chips">
          <button className={`chip ${category === null ? 'on' : ''}`} onClick={() => setCategory(null)}>
            Todo
          </button>
          {categories.map(([id, name]) => (
            <button key={id} className={`chip ${category === id ? 'on' : ''}`} onClick={() => setCategory(id)}>
              {name}
            </button>
          ))}
        </div>
      </div>

      {catalog.error ? (
        <ErrorBox error={catalog.error} onRetry={catalog.reload} />
      ) : !catalog.data ? (
        <Spinner />
      ) : items.length === 0 ? (
        <Empty title="No encontramos ese servicio" />
      ) : (
        <div className="catalog-grid">
          {items.map((c) => (
            <button key={c.id} className="catalog-item" onClick={() => setOrdering(c)}>
              <span className="ic">
                <Icon name={CATEGORY_ICON[c.category_name] ?? 'catalog'} size={20} />
              </span>
              <span className="muted" style={{ fontSize: 12, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.04em' }}>
                {c.category_name}
              </span>
              <h3>{c.name}</h3>
              <span className="meta">
                {c.needs_approval ? <Badge tone="warning">Requiere aprobación</Badge> : <Badge tone="success">Sin aprobación</Badge>}
                {c.sla_hours && <Badge>Entrega ~{c.sla_hours < 24 ? `${c.sla_hours} h` : `${Math.round(c.sla_hours / 24)} d`}</Badge>}
              </span>
            </button>
          ))}
        </div>
      )}

      {ordering && <OrderModal item={ordering} onClose={() => setOrdering(null)} onDone={(id) => nav(`/app/requests/${id}`)} />}
    </>
  );
}

function emptyValue(f: CatalogFormField): string | number | boolean | null {
  return f.type === 'boolean' ? false : f.type === 'number' ? null : '';
}

export function DynamicForm({ fields, value, onChange, errors }: { fields: CatalogFormField[]; value: RequestFormData; onChange: (v: RequestFormData) => void; errors: Record<string, string> }) {
  const set = (name: string, v: string | number | boolean | null) => onChange({ ...value, [name]: v });
  return (
    <div className="form-grid">
      {fields.map((f) => {
        const err = errors[`form_data.${f.name}`];
        const label = f.required ? `${f.label} *` : f.label;
        const v = value[f.name];
        if (f.type === 'boolean')
          return (
            <label key={f.name} className="check field-full">
              <input type="checkbox" checked={Boolean(v)} onChange={(e) => set(f.name, e.target.checked)} /> {f.label}
            </label>
          );
        return (
          <Field key={f.name} label={label} error={err} full={f.type === 'textarea'}>
            {f.type === 'select' ? (
              <select className="select" value={String(v ?? '')} onChange={(e) => set(f.name, e.target.value)}>
                <option value="">Selecciona…</option>
                {f.options?.map((o) => (
                  <option key={o}>{o}</option>
                ))}
              </select>
            ) : f.type === 'textarea' ? (
              <textarea className="textarea" value={String(v ?? '')} onChange={(e) => set(f.name, e.target.value)} />
            ) : (
              <input
                className="input"
                type={f.type === 'number' ? 'number' : f.type === 'date' ? 'date' : 'text'}
                min={f.type === 'number' ? 1 : undefined}
                value={v === null || v === undefined ? '' : String(v)}
                onChange={(e) => set(f.name, f.type === 'number' ? (e.target.value === '' ? null : Number(e.target.value)) : e.target.value)}
              />
            )}
          </Field>
        );
      })}
    </div>
  );
}

function OrderModal({ item, onClose, onDone }: { item: CatalogItem; onClose: () => void; onDone: (id: string) => void }) {
  const toast = useToast();
  const [data, setData] = useState<RequestFormData>(() => Object.fromEntries(item.form_schema.fields.map((f) => [f.name, emptyValue(f)])));
  const [errs, setErrs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const missing = item.form_schema.fields.some((f) => f.required && (data[f.name] === '' || data[f.name] === null || data[f.name] === undefined));

  async function submit() {
    setBusy(true);
    setErrs({});
    try {
      const req = await requestService.create({ catalog_item_id: item.id, form_data: data });
      toast(`Pedido ${req.key} enviado${req.status === 'pending_approval' ? ' · pendiente de aprobación' : ''}`);
      onDone(req.id);
    } catch (e) {
      setErrs(fieldErrors(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title={item.name}
      onClose={onClose}
      wide
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" disabled={busy || missing} onClick={submit}>
            {busy ? 'Enviando…' : 'Enviar pedido'}
          </button>
        </>
      }
    >
      <div className="row gap-sm wrap">
        <Badge>{item.category_name}</Badge>
        {item.needs_approval ? <Badge tone="warning">Pasará por aprobación</Badge> : <Badge tone="success">Va directo a atención</Badge>}
        {item.sla_hours && <Badge>Tiempo objetivo: {item.sla_hours} h</Badge>}
      </div>
      <DynamicForm fields={item.form_schema.fields} value={data} onChange={setData} errors={errs} />
    </Modal>
  );
}
