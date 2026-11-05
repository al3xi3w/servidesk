import { api } from './http';
import type {
  ApiResponse,
  CatalogItem,
  CatalogParams,
  CreateServiceRequestRequest,
  PaginatedResponse,
  ServiceRequest,
  ServiceRequestDetail,
  ServiceRequestListParams,
  UpdateServiceRequestRequest,
  UpdateServiceRequestStatusRequest,
  UUID,
} from '../types/api';

/** ms-requests: catálogo y solicitudes de servicio. */
export const requestService = {
  /** GET /catalog (sin paginar) */
  async catalog(params: CatalogParams = {}): Promise<CatalogItem[]> {
    const { data } = await api.requests.get<ApiResponse<CatalogItem[]>>('/catalog', { params });
    return data.data;
  },

  /** GET /requests — para customer el backend devuelve solo las suyas. */
  async list(params: ServiceRequestListParams = {}): Promise<PaginatedResponse<ServiceRequest>> {
    const { data } = await api.requests.get<PaginatedResponse<ServiceRequest>>('/requests', { params });
    return data;
  },

  /** POST /requests */
  async create(body: CreateServiceRequestRequest): Promise<ServiceRequestDetail> {
    const { data } = await api.requests.post<ApiResponse<ServiceRequestDetail>>('/requests', body);
    return data.data;
  },

  /** GET /requests/{id} */
  async get(id: UUID): Promise<ServiceRequestDetail> {
    const { data } = await api.requests.get<ApiResponse<ServiceRequestDetail>>(`/requests/${id}`);
    return data.data;
  },

  /** PATCH /requests/{id} */
  async update(id: UUID, body: UpdateServiceRequestRequest): Promise<ServiceRequestDetail> {
    const { data } = await api.requests.patch<ApiResponse<ServiceRequestDetail>>(`/requests/${id}`, body);
    return data.data;
  },

  /** PUT /requests/{id}/status — aprobar/rechazar desde pending_approval solo admin. */
  async changeStatus(id: UUID, body: UpdateServiceRequestStatusRequest): Promise<ServiceRequestDetail> {
    const { data } = await api.requests.put<ApiResponse<ServiceRequestDetail>>(`/requests/${id}/status`, body);
    return data.data;
  },
};
