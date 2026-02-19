/**
 * Shared API DTO types for backend response mapping.
 */

// ── Live Notifications (raw notification from API) ───────────────────

export interface RawNotification {
  id?: string;
  type?: string;
  severity?: string;
  title?: string;
  message?: string;
  timestamp?: string;
  read?: boolean;
}
