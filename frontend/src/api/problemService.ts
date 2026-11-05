import { api } from './http';
import type {
  ApiResponse,
  CreateProblemRequest,
  LinkIncidentsRequest,
  PaginatedResponse,
  Problem,
  ProblemDetail,
  ProblemListParams,
  PublishKnownErrorRequest,
  UpdateProblemRequest,
  UpdateProblemStatusRequest,
  UUID,
} from '../types/api';

/** ms-problems: problemas y errores conocidos. */
export const problemService = {
  /** GET /problems */
  async list(params: ProblemListParams = {}): Promise<PaginatedResponse<Problem>> {
    const { data } = await api.problems.get<PaginatedResponse<Problem>>('/problems', { params });
    return data;
  },

  /** POST /problems */
  async create(body: CreateProblemRequest): Promise<ProblemDetail> {
    const { data } = await api.problems.post<ApiResponse<ProblemDetail>>('/problems', body);
    return data.data;
  },

  /** GET /problems/{id} */
  async get(id: UUID): Promise<ProblemDetail> {
    const { data } = await api.problems.get<ApiResponse<ProblemDetail>>(`/problems/${id}`);
    return data.data;
  },

  /** PATCH /problems/{id} */
  async update(id: UUID, body: UpdateProblemRequest): Promise<ProblemDetail> {
    const { data } = await api.problems.patch<ApiResponse<ProblemDetail>>(`/problems/${id}`, body);
    return data.data;
  },

  /** PUT /problems/{id}/status */
  async changeStatus(id: UUID, body: UpdateProblemStatusRequest): Promise<ProblemDetail> {
    const { data } = await api.problems.put<ApiResponse<ProblemDetail>>(`/problems/${id}/status`, body);
    return data.data;
  },

  /** POST /problems/{id}/known-error */
  async publishKnownError(id: UUID, body: PublishKnownErrorRequest): Promise<ProblemDetail> {
    const { data } = await api.problems.post<ApiResponse<ProblemDetail>>(`/problems/${id}/known-error`, body);
    return data.data;
  },

  /** POST /problems/{id}/incidents */
  async linkIncidents(id: UUID, body: LinkIncidentsRequest): Promise<ProblemDetail> {
    const { data } = await api.problems.post<ApiResponse<ProblemDetail>>(`/problems/${id}/incidents`, body);
    return data.data;
  },
};
