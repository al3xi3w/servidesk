/**
 * Tipos compartidos de la API de ServiDesk.
 * Fuente de verdad: docs/openapi.yaml (v0.9). Si cambia el contrato, se actualizan ambos en el mismo PR.
 * Los nombres de campos siguen el JSON de la API (snake_case), igual que las columnas SQL.
 */

// ---------------------------------------------------------------- Comunes

/** UUID v4 en texto. */
export type UUID = string;
/** Fecha ISO 8601 en UTC, p. ej. "2026-11-05T19:20:25Z". */
export type ISODateTime = string;

export type Role = 'admin' | 'agent' | 'customer';
export type Priority = 'P1' | 'P2' | 'P3' | 'P4';
/** Impacto y urgencia (decisión D6). */
export type Level = 'high' | 'medium' | 'low';
export type SortOrder = 'asc' | 'desc';

/** Respuesta con un solo recurso o una lista sin paginar. */
export interface ApiResponse<T> {
  data: T;
}

export interface PaginationMeta {
  page: number;
  limit: number;
  total: number;
  total_pages: number;
}

export interface PaginatedResponse<T> {
  data: T[];
  meta: PaginationMeta;
}

/** Parámetros comunes de todo listado paginado. */
export interface ListParams<TSort extends string = string> {
  page?: number;
  limit?: number;
  search?: string;
  sort_by?: TSort;
  sort_order?: SortOrder;
}

/** Filtro que acepta uno o varios valores; se envía separado por comas. */
export type MultiValue<T extends string> = T | T[];

/** "me" = usuario del token, "none" = sin asignar. */
export type AssigneeFilter = 'me' | 'none' | UUID;

// ---------------------------------------------------------------- Errores

export type ErrorCode =
  | 'VALIDATION_ERROR'
  | 'INVALID_CREDENTIALS'
  | 'UNAUTHENTICATED'
  | 'FORBIDDEN'
  | 'NOT_FOUND'
  | 'CONFLICT'
  | 'EMAIL_ALREADY_EXISTS'
  | 'INVALID_STATUS_TRANSITION'
  | 'NOT_IMPLEMENTED'
  | 'INTERNAL_ERROR';

export interface FieldError {
  field: string;
  issue: string;
}

/** Body de error de los microservicios. */
export interface ApiErrorBody {
  error: {
    code: ErrorCode;
    message: string;
    details?: FieldError[];
    request_id?: string;
  };
}

/** Body de error de API Gateway (sin token: 401; token inválido o vencido: 403). */
export interface GatewayErrorBody {
  message: 'Unauthorized' | 'Forbidden';
}

/** Error normalizado que lanzan los servicios de src/api. */
export interface NormalizedApiError {
  status: number;
  code: ErrorCode | 'NETWORK_ERROR' | 'SESSION_EXPIRED';
  message: string;
  details: FieldError[];
  requestId?: string;
}

// ---------------------------------------------------------------- Auth / JWT

/** Payload del JWT. El frontend solo lo lee para la UI (expiración, rol); la autorización es del backend. */
export interface JwtPayload {
  sub: UUID;
  tenant_id: string;
  schema: string;
  role: Role;
  iat: number;
  exp: number;
}

export interface TenantSummary {
  /** Código del tenant: "andina", "pacifico", "unitec". */
  id: string;
  name: string;
}

export interface LoginRequest {
  tenant_code: string;
  email: string;
  password: string;
}

export interface AuthUser extends User {
  tenant: TenantSummary;
}

export interface LoginResponse {
  access_token: string;
  token_type: 'Bearer';
  expires_in: number;
  user: AuthUser;
}

// ---------------------------------------------------------------- Identity

export interface User {
  id: UUID;
  email: string;
  full_name: string;
  role: Role;
  active: boolean;
  created_at: ISODateTime;
}

export interface CreateUserRequest {
  email: string;
  full_name: string;
  role: Role;
  password: string;
  active?: boolean;
}

export interface UpdateUserRequest {
  full_name?: string;
  role?: Role;
  active?: boolean;
  password?: string;
}

export type UserSortField = 'created_at' | 'full_name' | 'email';

export interface UserListParams extends ListParams<UserSortField> {
  role?: MultiValue<Role>;
  active?: boolean;
  /** Hasta 100 UUID. */
  ids?: UUID[];
}

export interface Team {
  id: UUID;
  name: string;
  description: string | null;
}

export type TeamListParams = ListParams<'name'>;

// ---------------------------------------------------------------- CMDB

export type CIStatus = 'operational' | 'degraded' | 'down' | 'retired';
export type CIEnvironment = 'prod' | 'qa' | 'dev';
export type CIRelationType = 'depends_on' | 'runs_on' | 'connects_to';

export interface CIType {
  id: number;
  name: string;
}

export interface ConfigurationItem {
  id: UUID;
  type_id: number;
  /** Derivado (JOIN con ci_types). */
  type_name: string;
  name: string;
  status: CIStatus;
  environment: CIEnvironment;
  version: string | null;
  owner_team_id: UUID | null;
  attributes: Record<string, unknown>;
  /** Pendiente de agregar al ER (decisión D9). */
  created_at: ISODateTime;
  updated_at: ISODateTime;
}

export interface CreateConfigurationItemRequest {
  type_id: number;
  name: string;
  environment: CIEnvironment;
  version?: string | null;
  owner_team_id?: UUID | null;
  attributes?: Record<string, unknown>;
}

export type UpdateConfigurationItemRequest = Partial<CreateConfigurationItemRequest>;

export interface UpdateConfigurationItemStatusRequest {
  status: CIStatus;
}

export interface CIRelationView {
  id: UUID;
  relation: CIRelationType;
  direction: 'outgoing' | 'incoming';
  ci: Pick<ConfigurationItem, 'id' | 'name' | 'status' | 'type_name'>;
}

export type CISortField = 'created_at' | 'updated_at' | 'name' | 'status';

export interface CIListParams extends ListParams<CISortField> {
  status?: MultiValue<CIStatus>;
  environment?: MultiValue<CIEnvironment>;
  type_id?: number;
  owner_team_id?: UUID;
}

// ---------------------------------------------------------------- Incidents

export type IncidentStatus = 'new' | 'in_progress' | 'on_hold' | 'resolved' | 'closed';
export type IncidentChannel = 'portal' | 'email' | 'auto';

export interface Incident {
  id: UUID;
  key: string;
  title: string;
  description: string | null;
  status: IncidentStatus;
  impact: Level;
  urgency: Level;
  priority: Priority;
  sla_policy_id: number | null;
  sla_due_at: ISODateTime | null;
  sla_breached: boolean;
  reporter_id: UUID;
  assignee_id: UUID | null;
  team_id: UUID | null;
  ci_id: UUID | null;
  problem_id: UUID | null;
  channel: IncidentChannel;
  created_at: ISODateTime;
  resolved_at: ISODateTime | null;
}

export interface CreateIncidentRequest {
  title: string;
  description?: string | null;
  impact: Level;
  urgency: Level;
  ci_id?: UUID | null;
  /** Solo agent y admin. */
  team_id?: UUID | null;
  /** Solo agent y admin. */
  assignee_id?: UUID | null;
}

export interface UpdateIncidentRequest {
  title?: string;
  description?: string | null;
  impact?: Level;
  urgency?: Level;
  ci_id?: UUID | null;
  team_id?: UUID | null;
  assignee_id?: UUID | null;
  problem_id?: UUID | null;
}

export interface UpdateIncidentStatusRequest {
  status: IncidentStatus;
  /** Obligatorio al pasar a "resolved". */
  comment?: string;
}

export interface IncidentComment {
  id: UUID;
  incident_id: UUID;
  author_id: UUID;
  body: string;
  internal: boolean;
  created_at: ISODateTime;
}

export interface CreateIncidentCommentRequest {
  body: string;
  internal?: boolean;
}

export type IncidentSortField = 'created_at' | 'priority' | 'sla_due_at' | 'status' | 'key';

export interface IncidentListParams extends ListParams<IncidentSortField> {
  status?: MultiValue<IncidentStatus>;
  priority?: MultiValue<Priority>;
  impact?: MultiValue<Level>;
  urgency?: MultiValue<Level>;
  assignee_id?: AssigneeFilter;
  team_id?: UUID;
  ci_id?: UUID;
  problem_id?: UUID;
  channel?: IncidentChannel;
  sla_breached?: boolean;
}

export type CommentListParams = Omit<ListParams<'created_at'>, 'search'>;

// ---------------------------------------------------------------- Problems

export type ProblemStatus = 'new' | 'investigating' | 'known_error' | 'resolved' | 'closed';

export interface Problem {
  id: UUID;
  key: string;
  title: string;
  description: string | null;
  status: ProblemStatus;
  priority: Priority;
  root_cause: string | null;
  ci_id: UUID | null;
  owner_id: UUID | null;
  fix_change_id: UUID | null;
  created_at: ISODateTime;
}

export interface KnownError {
  id: UUID;
  problem_id: UUID;
  symptom: string;
  workaround: string;
  published_at: ISODateTime;
}

export interface ProblemDetail extends Problem {
  incident_ids: UUID[];
  known_error: KnownError | null;
}

export interface CreateProblemRequest {
  title: string;
  description?: string | null;
  priority: Priority;
  ci_id?: UUID | null;
  owner_id?: UUID | null;
  incident_ids?: UUID[];
}

export interface UpdateProblemRequest {
  title?: string;
  description?: string | null;
  priority?: Priority;
  root_cause?: string | null;
  ci_id?: UUID | null;
  owner_id?: UUID | null;
  fix_change_id?: UUID | null;
}

export interface UpdateProblemStatusRequest {
  /** "known_error" se publica con publishKnownError. */
  status: Extract<ProblemStatus, 'investigating' | 'resolved' | 'closed'>;
}

export interface PublishKnownErrorRequest {
  symptom: string;
  workaround: string;
}

export interface LinkIncidentsRequest {
  incident_ids: UUID[];
}

export type ProblemSortField = 'created_at' | 'priority' | 'status' | 'key';

export interface ProblemListParams extends ListParams<ProblemSortField> {
  status?: MultiValue<ProblemStatus>;
  priority?: MultiValue<Priority>;
  ci_id?: UUID;
  owner_id?: 'me' | UUID;
}

// ---------------------------------------------------------------- Changes

export type ChangeType = 'standard' | 'normal' | 'emergency';
export type ChangeRisk = 'low' | 'medium' | 'high';
export type ChangeStatus =
  | 'draft'
  | 'submitted'
  | 'approved'
  | 'rejected'
  | 'scheduled'
  | 'implemented'
  | 'failed';
export type ApprovalDecision = 'pending' | 'approved' | 'rejected';

export interface Change {
  id: UUID;
  key: string;
  title: string;
  description: string | null;
  type: ChangeType;
  risk: ChangeRisk;
  status: ChangeStatus;
  rollback_plan: string | null;
  planned_start: ISODateTime | null;
  planned_end: ISODateTime | null;
  requester_id: UUID;
  problem_id: UUID | null;
  created_at: ISODateTime;
}

export interface ChangeCI {
  ci_id: UUID;
  new_version?: string | null;
}

export interface ChangeApproval {
  id: UUID;
  change_id: UUID;
  approver_id: UUID;
  decision: ApprovalDecision;
  comment: string | null;
  decided_at: ISODateTime | null;
}

export interface ChangeDetail extends Change {
  cis: ChangeCI[];
  approvals: ChangeApproval[];
}

export interface CreateChangeRequest {
  title: string;
  description?: string | null;
  type: ChangeType;
  risk: ChangeRisk;
  rollback_plan?: string | null;
  planned_start?: ISODateTime | null;
  planned_end?: ISODateTime | null;
  problem_id?: UUID | null;
  cis?: ChangeCI[];
}

export type UpdateChangeRequest = Partial<CreateChangeRequest>;

export interface UpdateChangeStatusRequest {
  /** "approved" y "rejected" van por approveChange / rejectChange. */
  status: Extract<ChangeStatus, 'draft' | 'submitted' | 'scheduled' | 'implemented' | 'failed'>;
}

export interface ApproveChangeRequest {
  comment?: string;
}

export interface RejectChangeRequest {
  comment: string;
}

export type ChangeSortField = 'created_at' | 'planned_start' | 'risk' | 'status' | 'key';

export interface ChangeListParams extends ListParams<ChangeSortField> {
  status?: MultiValue<ChangeStatus>;
  type?: MultiValue<ChangeType>;
  risk?: MultiValue<ChangeRisk>;
  requester_id?: 'me' | UUID;
  planned_from?: ISODateTime;
  planned_to?: ISODateTime;
}

// ---------------------------------------------------------------- Requests

export type ServiceRequestStatus =
  | 'submitted'
  | 'pending_approval'
  | 'approved'
  | 'in_fulfillment'
  | 'fulfilled'
  | 'rejected';

export type CatalogFieldType = 'text' | 'textarea' | 'number' | 'date' | 'select' | 'boolean';

export interface CatalogFormField {
  name: string;
  label: string;
  type: CatalogFieldType;
  required: boolean;
  /** Solo para type = "select". */
  options?: string[];
}

export interface CatalogItem {
  id: UUID;
  category_id: number;
  /** Derivado (JOIN con catalog_categories). */
  category_name: string;
  name: string;
  form_schema: { fields: CatalogFormField[] };
  needs_approval: boolean;
  sla_hours: number | null;
}

export interface CatalogParams {
  category_id?: number;
  search?: string;
}

export type RequestFormData = Record<string, string | number | boolean | null>;

export interface ServiceRequest {
  id: UUID;
  key: string;
  catalog_item_id: UUID;
  /** Derivado (JOIN con catalog_items). */
  catalog_item_name: string;
  form_data: RequestFormData;
  status: ServiceRequestStatus;
  requester_id: UUID;
  assignee_id: UUID | null;
  created_at: ISODateTime;
  fulfilled_at: ISODateTime | null;
}

export interface RequestApproval {
  id: UUID;
  request_id: UUID;
  approver_id: UUID;
  decision: ApprovalDecision;
  decided_at: ISODateTime | null;
}

export interface ServiceRequestDetail extends ServiceRequest {
  approvals: RequestApproval[];
}

export interface CreateServiceRequestRequest {
  catalog_item_id: UUID;
  form_data: RequestFormData;
}

export interface UpdateServiceRequestRequest {
  /** Solo agent y admin. */
  assignee_id?: UUID | null;
  /** Solo el solicitante, mientras esté submitted o pending_approval. */
  form_data?: RequestFormData;
}

export interface UpdateServiceRequestStatusRequest {
  status: Extract<ServiceRequestStatus, 'approved' | 'rejected' | 'in_fulfillment' | 'fulfilled'>;
}

export type ServiceRequestSortField = 'created_at' | 'status' | 'key';

export interface ServiceRequestListParams extends ListParams<ServiceRequestSortField> {
  status?: MultiValue<ServiceRequestStatus>;
  catalog_item_id?: UUID;
  requester_id?: 'me' | UUID;
  assignee_id?: AssigneeFilter;
}

// ---------------------------------------------------------------- Eventos (solo lectura, para depurar o mostrar)

export type EventType =
  | 'TenantCreated'
  | 'UserCreated'
  | 'CIStatusChanged'
  | 'IncidentCreated'
  | 'IncidentUpdated'
  | 'IncidentResolved'
  | 'IncidentSlaBreached'
  | 'ProblemCreated'
  | 'ProblemIncidentsLinked'
  | 'KnownErrorPublished'
  | 'ChangeSubmitted'
  | 'ChangeApproved'
  | 'ChangeRejected'
  | 'ChangeImplemented'
  | 'RequestSubmitted'
  | 'RequestApproved'
  | 'RequestRejected'
  | 'RequestFulfilled';

/** Sobre de los eventos SNS/SQS (docs/EVENT_CONTRACTS.md). El frontend no los consume directamente. */
export interface EventEnvelope<TData = Record<string, unknown>> {
  eventId: UUID;
  eventType: EventType;
  tenantId: string;
  occurredAt: ISODateTime;
  source: string;
  data: TData;
}

// ---------------------------------------------------------------- Notificaciones (PROPUESTO v1.0, fuera de v0.9 por D16)
// Tabla notifications de ms-identity (ER del diseño). Rutas propuestas: GET /notifications, POST /notifications/read.
// Hasta que se aprueben en openapi.yaml, solo las responde el simulador de src/mocks.

export interface Notification {
  id: UUID;
  user_id: UUID;
  event_type: EventType;
  title: string;
  body: string;
  read: boolean;
  created_at: ISODateTime;
  /** Propuesto: recurso relacionado para navegar desde la campana. */
  resource_type: 'incident' | 'problem' | 'change' | 'request' | 'ci' | null;
  resource_id: UUID | null;
}

export interface NotificationListResponse {
  data: Notification[];
  meta: { unread: number };
}

export interface MarkNotificationsReadRequest {
  /** Sin ids = marcar todas. */
  ids?: UUID[];
}
