import { api } from './http';
import type {
  ApiResponse,
  ApproveChangeRequest,
  Change,
  ChangeDetail,
  ChangeListParams,
  CreateChangeRequest,
  ISODateTime,
  PaginatedResponse,
  RejectChangeRequest,
  UpdateChangeRequest,
  UpdateChangeStatusRequest,
  UUID,
} from '../types/api';

/** ms-changes: RFC, CAB y calendario. */
export const changeService = {
  /** GET /changes */
  async list(params: ChangeListParams = {}): Promise<PaginatedResponse<Change>> {
    const { data } = await api.changes.get<PaginatedResponse<Change>>('/changes', { params });
    return data;
  },

  /** Calendario: GET /changes con planned_from/planned_to (decisión D13). */
  async calendar(from: ISODateTime, to: ISODateTime): Promise<Change[]> {
    const page = await changeService.list({
      planned_from: from,
      planned_to: to,
      status: ['approved', 'scheduled', 'implemented'],
      sort_by: 'planned_start',
      sort_order: 'asc',
      limit: 100,
    });
    return page.data;
  },

  /** POST /changes — se crea en "draft". */
  async create(body: CreateChangeRequest): Promise<ChangeDetail> {
    const { data } = await api.changes.post<ApiResponse<ChangeDetail>>('/changes', body);
    return data.data;
  },

  /** GET /changes/{id} */
  async get(id: UUID): Promise<ChangeDetail> {
    const { data } = await api.changes.get<ApiResponse<ChangeDetail>>(`/changes/${id}`);
    return data.data;
  },

  /** PATCH /changes/{id} — solo en "draft". */
  async update(id: UUID, body: UpdateChangeRequest): Promise<ChangeDetail> {
    const { data } = await api.changes.patch<ApiResponse<ChangeDetail>>(`/changes/${id}`, body);
    return data.data;
  },

  /** PUT /changes/{id}/status */
  async changeStatus(id: UUID, body: UpdateChangeStatusRequest): Promise<ChangeDetail> {
    const { data } = await api.changes.put<ApiResponse<ChangeDetail>>(`/changes/${id}/status`, body);
    return data.data;
  },

  /** POST /changes/{id}/approve (admin) */
  async approve(id: UUID, body: ApproveChangeRequest = {}): Promise<ChangeDetail> {
    const { data } = await api.changes.post<ApiResponse<ChangeDetail>>(`/changes/${id}/approve`, body);
    return data.data;
  },

  /** POST /changes/{id}/reject (admin, comment obligatorio) */
  async reject(id: UUID, body: RejectChangeRequest): Promise<ChangeDetail> {
    const { data } = await api.changes.post<ApiResponse<ChangeDetail>>(`/changes/${id}/reject`, body);
    return data.data;
  },
};
