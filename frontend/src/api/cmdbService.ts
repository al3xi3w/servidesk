import { api } from './http';
import type {
  ApiResponse,
  CIListParams,
  CIRelationView,
  CIType,
  ConfigurationItem,
  CreateConfigurationItemRequest,
  PaginatedResponse,
  UpdateConfigurationItemRequest,
  UpdateConfigurationItemStatusRequest,
  UUID,
} from '../types/api';

/** ms-cmdb: elementos de configuración. */
export const cmdbService = {
  /** GET /cis */
  async list(params: CIListParams = {}): Promise<PaginatedResponse<ConfigurationItem>> {
    const { data } = await api.cmdb.get<PaginatedResponse<ConfigurationItem>>('/cis', { params });
    return data;
  },

  /** POST /cis */
  async create(body: CreateConfigurationItemRequest): Promise<ConfigurationItem> {
    const { data } = await api.cmdb.post<ApiResponse<ConfigurationItem>>('/cis', body);
    return data.data;
  },

  /** GET /cis/{id} */
  async get(id: UUID): Promise<ConfigurationItem> {
    const { data } = await api.cmdb.get<ApiResponse<ConfigurationItem>>(`/cis/${id}`);
    return data.data;
  },

  /** PATCH /cis/{id} */
  async update(id: UUID, body: UpdateConfigurationItemRequest): Promise<ConfigurationItem> {
    const { data } = await api.cmdb.patch<ApiResponse<ConfigurationItem>>(`/cis/${id}`, body);
    return data.data;
  },

  /** PUT /cis/{id}/status — "down" genera un incidente automático. */
  async changeStatus(id: UUID, body: UpdateConfigurationItemStatusRequest): Promise<ConfigurationItem> {
    const { data } = await api.cmdb.put<ApiResponse<ConfigurationItem>>(`/cis/${id}/status`, body);
    return data.data;
  },

  /** DELETE /cis/{id} (admin): baja lógica a "retired". */
  async remove(id: UUID): Promise<void> {
    await api.cmdb.delete(`/cis/${id}`);
  },

  /** GET /cis/{id}/relations */
  async relations(id: UUID): Promise<CIRelationView[]> {
    const { data } = await api.cmdb.get<ApiResponse<CIRelationView[]>>(`/cis/${id}/relations`);
    return data.data;
  },

  /** GET /ci-types */
  async types(): Promise<CIType[]> {
    const { data } = await api.cmdb.get<ApiResponse<CIType[]>>('/ci-types');
    return data.data;
  },
};
