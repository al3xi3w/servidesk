import { api } from './http';
import type {
  ApiResponse,
  CommentListParams,
  CreateIncidentCommentRequest,
  CreateIncidentRequest,
  Incident,
  IncidentComment,
  IncidentListParams,
  PaginatedResponse,
  UpdateIncidentRequest,
  UpdateIncidentStatusRequest,
  UUID,
} from '../types/api';

/** ms-incidents: incidentes y comentarios. */
export const incidentService = {
  /** GET /incidents — para customer el backend devuelve solo los suyos. */
  async list(params: IncidentListParams = {}): Promise<PaginatedResponse<Incident>> {
    const { data } = await api.incidents.get<PaginatedResponse<Incident>>('/incidents', { params });
    return data;
  },

  /** POST /incidents — el backend fija key, status, priority, SLA, reporter_id y channel. */
  async create(body: CreateIncidentRequest): Promise<Incident> {
    const { data } = await api.incidents.post<ApiResponse<Incident>>('/incidents', body);
    return data.data;
  },

  /** GET /incidents/{id} */
  async get(id: UUID): Promise<Incident> {
    const { data } = await api.incidents.get<ApiResponse<Incident>>(`/incidents/${id}`);
    return data.data;
  },

  /** PATCH /incidents/{id} (agent, admin) */
  async update(id: UUID, body: UpdateIncidentRequest): Promise<Incident> {
    const { data } = await api.incidents.patch<ApiResponse<Incident>>(`/incidents/${id}`, body);
    return data.data;
  },

  /** PUT /incidents/{id}/status — "resolved" exige comment. */
  async changeStatus(id: UUID, body: UpdateIncidentStatusRequest): Promise<Incident> {
    const { data } = await api.incidents.put<ApiResponse<Incident>>(`/incidents/${id}/status`, body);
    return data.data;
  },

  /** GET /incidents/{id}/comments (orden ascendente por defecto) */
  async listComments(id: UUID, params: CommentListParams = {}): Promise<PaginatedResponse<IncidentComment>> {
    const { data } = await api.incidents.get<PaginatedResponse<IncidentComment>>(`/incidents/${id}/comments`, { params });
    return data;
  },

  /** POST /incidents/{id}/comments */
  async addComment(id: UUID, body: CreateIncidentCommentRequest): Promise<IncidentComment> {
    const { data } = await api.incidents.post<ApiResponse<IncidentComment>>(`/incidents/${id}/comments`, body);
    return data.data;
  },
};
