import { useState } from 'react';
import { changeService, problemService } from '../../api';
import { CiSelect } from '../../components/pickers';
import { Field, fieldErrors, Modal, useToast } from '../../components/ui';
import { CHANGE_TYPE, fromLocalInput, toLocalInput } from '../../lib/format';
import type { ChangeDetail, ChangeRisk, ChangeType } from '../../types/api';

/** Crear (sin `change`) o editar un cambio en borrador. */
export function ChangeForm({ change, problemId, onClose, onSaved }: { change?: ChangeDetail; problemId?: string | null; onClose: () => void; onSaved: (c: ChangeDetail) => void }) {
  const toast = useToast();
  const [title, setTitle] = useState(change?.title ?? '');
  const [description, setDescription] = useState(change?.description ?? '');
  const [type, setType] = useState<ChangeType>(change?.type ?? 'normal');
  const [risk, setRisk] = useState<ChangeRisk>(change?.risk ?? 'medium');
  const [rollback, setRollback] = useState(change?.rollback_plan ?? '');
  const [start, setStart] = useState(toLocalInput(change?.planned_start));
  const [end, setEnd] = useState(toLocalInput(change?.planned_end));
  const [cis, setCis] = useState<{ ci_id: string | null; new_version: string }[]>(change?.cis.map((c) => ({ ci_id: c.ci_id, new_version: c.new_version ?? '' })) ?? [{ ci_id: null, new_version: '' }]);
  const [busy, setBusy] = useState(false);
  const [errs, setErrs] = useState<Record<string, string>>({});

  async function submit() {
    setBusy(true);
    setErrs({});
    const body = {
      title,
      description: description || null,
      type,
      risk,
      rollback_plan: rollback || null,
      planned_start: fromLocalInput(start),
      planned_end: fromLocalInput(end),
      cis: cis
        .filter((c, i, all) => c.ci_id && all.findIndex((x) => x.ci_id === c.ci_id) === i)
        .map((c) => ({ ci_id: c.ci_id as string, new_version: c.new_version.trim() || null })),
      ...(!change && problemId ? { problem_id: problemId } : {}),
    };
    try {
      const saved = change ? await changeService.update(change.id, body) : await changeService.create(body);
      if (!change && problemId) await problemService.update(problemId, { fix_change_id: saved.id }).catch(() => {});
      toast(change ? 'Actualización guardada' : `Actualización ${saved.key} guardada como borrador`);
      onSaved(saved);
    } catch (e) {
      const fe = fieldErrors(e);
      setErrs(Object.keys(fe).length ? fe : { _: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title={change ? `Editar ${change.key}` : 'Planificar una actualización'}
      onClose={onClose}
      wide
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" disabled={busy || title.trim().length < 5} onClick={submit}>
            {change ? 'Guardar' : 'Crear borrador'}
          </button>
        </>
      }
    >
      {errs._ && <div className="form-error">{errs._}</div>}
      <div className="form-grid">
        <Field label="Título" error={errs.title} full>
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} autoFocus placeholder="Ej.: Actualizar el sistema de ventas a la versión 7.2" />
        </Field>
        <Field label="¿Qué se va a hacer y por qué?" error={errs.description} full>
          <textarea className="textarea" value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        <Field label="Tipo" error={errs.type} hint={type === 'standard' ? 'Tarea de rutina: se aprueba sola' : type === 'emergency' ? 'Urgente: el comité la revisa de inmediato' : 'La revisa y aprueba el comité'}>
          <select className="select" value={type} onChange={(e) => setType(e.target.value as ChangeType)}>
            {(Object.keys(CHANGE_TYPE) as ChangeType[]).map((t) => (
              <option key={t} value={t}>
                {CHANGE_TYPE[t]}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Riesgo de que algo salga mal" error={errs.risk}>
          <select className="select" value={risk} onChange={(e) => setRisk(e.target.value as ChangeRisk)}>
            <option value="low">Bajo</option>
            <option value="medium">Medio</option>
            <option value="high">Alto</option>
          </select>
        </Field>
        <Field label="Empieza" error={errs.planned_start}>
          <input className="input" type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} />
        </Field>
        <Field label="Termina" error={errs.planned_end}>
          <input className="input" type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} />
        </Field>
        <Field label="Plan B: cómo volver atrás" error={errs.rollback_plan} hint={type !== 'standard' ? 'Obligatorio para enviarla al comité' : 'Opcional en tareas de rutina'} full>
          <textarea className="textarea" value={rollback} onChange={(e) => setRollback(e.target.value)} placeholder="¿Cómo se vuelve al estado anterior si algo falla?" />
        </Field>
        <div className="field field-full">
          <span className="field-label">Equipos o sistemas que se actualizan</span>
          {cis.map((ci, n) => (
            <div key={n} className="row gap-sm wrap" style={{ alignItems: 'flex-start' }}>
              <div className="grow" style={{ minWidth: 220 }}>
                <CiSelect value={ci.ci_id} onChange={(v) => setCis(cis.map((x, k) => (k === n ? { ...x, ci_id: v } : x)))} />
              </div>
              <input
                className="input mono"
                style={{ width: 130 }}
                placeholder="Nueva versión"
                aria-label="Nueva versión"
                value={ci.new_version}
                onChange={(e) => setCis(cis.map((x, k) => (k === n ? { ...x, new_version: e.target.value } : x)))}
              />
              {cis.length > 1 && (
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setCis(cis.filter((_, k) => k !== n))}>
                  Quitar
                </button>
              )}
            </div>
          ))}
          <span className="field-hint">Cuando la actualización se marque como implementada, el inventario se actualiza solo con la nueva versión.</span>
          <button type="button" className="link-btn" style={{ alignSelf: 'flex-start' }} onClick={() => setCis([...cis, { ci_id: null, new_version: '' }])}>
            + Agregar equipo o sistema
          </button>
        </div>
      </div>
    </Modal>
  );
}
