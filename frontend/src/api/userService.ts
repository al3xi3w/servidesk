import { api } from './http';
import type {
  ApiResponse,
  CreateUserRequest,
  PaginatedResponse,
  Team,
  TeamListParams,
  UpdateUserRequest,
  User,
  UserListParams,
  UUID,
} from '../types/api';

/** ms-identity: usuarios y equipos. */
export const userService = {
  /** GET /users */
  async list(params: UserListParams = {}): Promise<PaginatedResponse<User>> {
    const { data } = await api.identity.get<PaginatedResponse<User>>('/users', { params });
    return data;
  },

  /** GET /users?ids=…: resuelve nombres de reportantes y asignados (hasta 100 por llamada). */
  async byIds(ids: UUID[]): Promise<User[]> {
    if (!ids.length) return [];
    const unique = [...new Set(ids)].slice(0, 100);
    const { data } = await api.identity.get<PaginatedResponse<User>>('/users', { params: { ids: unique, limit: 100 } });
    return data.data;
  },

  /** GET /users/{id} */
  async get(id: UUID): Promise<User> {
    const { data } = await api.identity.get<ApiResponse<User>>(`/users/${id}`);
    return data.data;
  },

  /** POST /users (admin) */
  async create(body: CreateUserRequest): Promise<User> {
    const { data } = await api.identity.post<ApiResponse<User>>('/users', body);
    return data.data;
  },

  /** PATCH /users/{id} (admin) */
  async update(id: UUID, body: UpdateUserRequest): Promise<User> {
    const { data } = await api.identity.patch<ApiResponse<User>>(`/users/${id}`, body);
    return data.data;
  },

  /** GET /teams */
  async listTeams(params: TeamListParams = {}): Promise<PaginatedResponse<Team>> {
    const { data } = await api.identity.get<PaginatedResponse<Team>>('/teams', { params });
    return data;
  },
};
