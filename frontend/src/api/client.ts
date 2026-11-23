import type {
  AuthStatus,
  ConfigCheck,
  ScanProgressEvent,
  ScanSessionDetail,
  ScanSessionSummary,
} from "../types/radar";

async function apiFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(url, {
    credentials: "include",
    ...init,
  });
  if (!resp.ok) {
    let msg = `请求失败 (${resp.status})`;
    try {
      const err = await resp.json();
      if (err?.detail) msg = String(err.detail);
    } catch {
      // ignore
    }
    throw new Error(msg);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  authStatus: () => apiFetch<AuthStatus>("/api/auth/status"),

  login: (password: string) =>
    apiFetch<{ ok: boolean; token: string }>("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    }),

  logout: () =>
    apiFetch<{ ok: boolean }>("/api/auth/logout", {
      method: "POST",
    }),

  configCheck: () => apiFetch<ConfigCheck>("/api/system/config-check"),

  listHistory: (q = "") =>
    apiFetch<ScanSessionSummary[]>(
      `/api/scans${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ""}`
    ),

  getScanDetail: (id: string) =>
    apiFetch<ScanSessionDetail>(`/api/scans/${encodeURIComponent(id)}`),

  deleteScan: (id: string) =>
    apiFetch<{ ok: boolean }>(`/api/scans/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),

  startRadarScan: (formData: FormData) =>
    apiFetch<{ session_id: string; history_title: string }>("/api/scans", {
      method: "POST",
      body: formData,
    }),

  startDirectUrlScan: (formData: FormData) =>
    apiFetch<{ session_id: string; history_title: string }>(
      "/api/scans/analyze-urls",
      {
        method: "POST",
        body: formData,
      }
    ),

  exportUrl: (id: string, format: "md" | "json") =>
    `/api/scans/${encodeURIComponent(id)}/export?format=${format}`,

  subscribeEvents: (
    sessionId: string,
    onEvent: (ev: ScanProgressEvent) => void,
    onDone?: () => void
  ): (() => void) => {
    const es = new EventSource(`/api/scans/${encodeURIComponent(sessionId)}/events`, {
      withCredentials: true,
    });
    es.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data) as ScanProgressEvent;
        onEvent(parsed);
        if (parsed.status === "completed" || parsed.status === "failed") {
          es.close();
          onDone?.();
        }
      } catch {
        // ignore keepalive
      }
    };
    es.onerror = () => {
      es.close();
      onDone?.();
    };
    return () => es.close();
  },
};
