import { api } from './http';
import type { MarkNotificationsReadRequest, NotificationListResponse } from '../types/api';

/**
 * ms-identity: bandeja de notificaciones que llena el consumidor identity-notify-q.
 * PROPUESTO (D16): estas rutas aún no están en docs/openapi.yaml; hoy solo las responde el modo demo.
 */
export const notificationService = {
  /** GET /notifications?limit= (las más recientes primero) */
  async list(limit = 20): Promise<NotificationListResponse> {
    const { data } = await api.identity.get<NotificationListResponse>('/notifications', { params: { limit } });
    return data;
  },

  /** POST /notifications/read */
  async markRead(body: MarkNotificationsReadRequest = {}): Promise<void> {
    await api.identity.post('/notifications/read', body);
  },
};
