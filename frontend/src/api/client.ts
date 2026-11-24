import type {
  AuthStatus,
  ConfigCheck,
  GeneratedAsset,
  ScanProgressEvent,
  ScanSessionDetail,
  ScanSessionSummary,
  StudioState,
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

  // V2.0 One-Click Replication Studio APIs
  getStudioState: (videoId: string) =>
    apiFetch<StudioState>(`/api/studio/videos/${encodeURIComponent(videoId)}/assets`),

  uploadProductReference: (videoId: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return apiFetch<{ ok: boolean; product_reference_preview: string }>(
      `/api/studio/videos/${encodeURIComponent(videoId)}/product-reference`,
      { method: "POST", body: fd }
    );
  },

  generateStudioImage: (
    videoId: string,
    payload: {
      slot_index: number;
      shot_no?: number | null;
      scene_title: string;
      prompt: string;
      provider: "gemini" | "openai";
      aspect_ratio?: string;
    }
  ) =>
    apiFetch<GeneratedAsset>(
      `/api/studio/videos/${encodeURIComponent(videoId)}/generate-image`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }
    ),

  generateAllStudioImages: (
    videoId: string,
    payload: {
      provider: "gemini" | "openai";
      only_missing?: boolean;
      include_real_shoot_shots?: boolean;
      include_poster?: boolean;
    }
  ) =>
    apiFetch<GeneratedAsset[]>(
      `/api/studio/videos/${encodeURIComponent(videoId)}/generate-all-images`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }
    ),

  generateStudioVideoClip: (
    videoId: string,
    payload: {
      slot_index: number;
      shot_no: number;
      scene_title: string;
      source_image_asset_id: string;
      prompt: string;
      negative_prompt?: string;
      duration_sec?: number;
    }
  ) =>
    apiFetch<GeneratedAsset>(
      `/api/studio/videos/${encodeURIComponent(videoId)}/generate-video-clip`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }
    ),

  generateAllStudioVideos: (
    videoId: string,
    payload: {
      only_missing?: boolean;
      duration_sec?: number;
      include_real_shoot_shots?: boolean;
    }
  ) =>
    apiFetch<GeneratedAsset[]>(
      `/api/studio/videos/${encodeURIComponent(videoId)}/generate-all-videos`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }
    ),

  uploadRealShootClip: (
    videoId: string,
    shotNo: number,
    file: File,
    sceneTitle = ""
  ) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("shot_no", String(shotNo));
    fd.append("scene_title", sceneTitle);
    return apiFetch<GeneratedAsset>(
      `/api/studio/videos/${encodeURIComponent(videoId)}/upload-real-clip`,
      { method: "POST", body: fd }
    );
  },

  stitchFinalVideo: (
    videoId: string,
    payload: {
      asset_ids?: string[];
      include_images_as_motion?: boolean;
      image_clip_duration?: number;
    }
  ) =>
    apiFetch<GeneratedAsset>(
      `/api/studio/videos/${encodeURIComponent(videoId)}/stitch-final`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }
    ),

  deleteStudioAsset: (assetId: string) =>
    apiFetch<{ ok: boolean }>(`/api/studio/assets/${encodeURIComponent(assetId)}`, {
      method: "DELETE",
    }),

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
