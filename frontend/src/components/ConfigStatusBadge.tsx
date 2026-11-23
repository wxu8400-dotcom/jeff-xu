import React, { useState } from "react";
import { Activity, CheckCircle2, AlertCircle, X } from "lucide-react";
import type { ConfigCheck } from "../types/radar";

interface Props {
  config: ConfigCheck | null;
}

export const ConfigStatusBadge: React.FC<Props> = ({ config }) => {
  const [open, setOpen] = useState(false);

  if (!config) return null;

  const allReady =
    (config.mock_mode || (config.tikhub_configured && config.ai_configured)) &&
    config.ffmpeg_available;

  const rows = [
    {
      label: "三平台采集源 (TikHub)",
      ok: config.tikhub_configured || config.mock_mode,
      detail: config.tikhub_configured
        ? "已就绪"
        : config.mock_mode
        ? "Mock 演示模式"
        : "未配置 TIKHUB_API_KEY",
    },
    {
      label: "YouTube 官方免费接口 (可选)",
      ok: config.youtube_api_configured,
      detail: config.youtube_api_configured ? "已配置（优先走免费通道）" : "未配（自动走 TikHub）",
      optional: true,
    },
    {
      label: `AI 拆解引擎 (${config.ai_provider})`,
      ok: config.ai_configured,
      detail: config.ai_configured
        ? `${config.ai_fast_model} / ${config.ai_deep_model}${
            config.ai_custom_base_url ? " · 自定义中转" : ""
          }`
        : "未配置 AI API Key",
    },
    {
      label: "云端历史数据库",
      ok: true,
      detail:
        config.database_kind === "postgresql"
          ? "PostgreSQL（云端永久保存）"
          : "SQLite（本地模式）",
    },
    {
      label: "FFmpeg 视频省 Token 压缩",
      ok: config.ffmpeg_available,
      detail: config.ffmpeg_available ? "可用（360p/1fps 低耗流）" : "未检测到 FFmpeg",
    },
    {
      label: "公网访问密码锁",
      ok: config.password_protected,
      detail: config.password_protected ? "已开启保护" : "未设密码（建议上线前设置）",
      optional: true,
    },
  ];

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border transition ${
          config.mock_mode
            ? "bg-amber-500/15 border-amber-500/40 text-amber-300"
            : allReady
            ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300"
            : "bg-rose-500/15 border-rose-500/40 text-rose-300"
        }`}
      >
        <Activity className="w-3.5 h-3.5" />
        <span>
          {config.mock_mode ? "演示模式" : allReady ? "系统就绪" : "待配置 Key"}
        </span>
      </button>

      {open && (
        <div className="fixed inset-x-3 top-16 sm:absolute sm:inset-x-auto sm:right-0 sm:top-10 z-50 sm:w-80 bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-white">运行环境与 Key 自检</h3>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="p-1 text-slate-400 hover:text-white"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="space-y-2.5">
            {rows.map((r) => (
              <div key={r.label} className="flex items-start gap-2 text-xs">
                {r.ok ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                ) : (
                  <AlertCircle
                    className={`w-4 h-4 shrink-0 mt-0.5 ${
                      r.optional ? "text-amber-400" : "text-rose-400"
                    }`}
                  />
                )}
                <div className="min-w-0">
                  <div className="text-slate-200 font-medium">{r.label}</div>
                  <div className="text-slate-400 break-words">{r.detail}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
