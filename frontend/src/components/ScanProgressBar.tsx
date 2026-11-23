import React from "react";
import { CheckCircle2, Coins, Filter, Loader2, AlertTriangle } from "lucide-react";
import type { FunnelStats } from "../types/radar";

interface Props {
  status: string;
  progressPercent: number;
  progressMessage: string;
  errorMessage?: string | null;
  stats?: FunnelStats;
}

const STAGES = [
  { key: "extracting_product", label: "产品基因解析" },
  { key: "collecting", label: "三平台采集(0 Token)" },
  { key: "filtering", label: "播放点赞过滤(0 Token)" },
  { key: "screening", label: "可替换性初筛" },
  { key: "analyzing", label: "原生视频精拆" },
];

export const ScanProgressBar: React.FC<Props> = ({
  status,
  progressPercent,
  progressMessage,
  errorMessage,
  stats,
}) => {
  const isDone = status === "completed";
  const isFailed = status === "failed";
  const currentIdx = STAGES.findIndex((s) => s.key === status);

  return (
    <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-4 sm:p-5 space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <div className="flex items-center gap-2.5 min-w-0">
          {isFailed ? (
            <AlertTriangle className="w-5 h-5 text-rose-400 shrink-0" />
          ) : isDone ? (
            <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
          ) : (
            <Loader2 className="w-5 h-5 text-sky-400 animate-spin shrink-0" />
          )}
          <span className="text-sm font-medium text-slate-100 break-words">
            {progressMessage}
          </span>
        </div>
        <span className="text-xs font-mono text-sky-400 shrink-0">
          {progressPercent}%
        </span>
      </div>

      {/* Progress Bar */}
      <div className="w-full h-2 rounded-full bg-slate-800 overflow-hidden">
        <div
          className={`h-full transition-all duration-500 ${
            isFailed
              ? "bg-rose-500"
              : isDone
              ? "bg-emerald-500"
              : "bg-gradient-to-r from-sky-500 to-cyan-400"
          }`}
          style={{ width: `${Math.min(100, Math.max(4, progressPercent))}%` }}
        />
      </div>

      {/* Stage Pills */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
        {STAGES.map((st, idx) => {
          const passed = isDone || (currentIdx > idx && currentIdx !== -1);
          const active = !isDone && !isFailed && currentIdx === idx;
          return (
            <div
              key={st.key}
              className={`px-2.5 py-1.5 rounded-lg text-[11px] font-medium text-center border ${
                passed
                  ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300"
                  : active
                  ? "bg-sky-500/15 border-sky-400/50 text-sky-200"
                  : "bg-slate-950/60 border-slate-800 text-slate-500"
              }`}
            >
              {idx + 1}. {st.label}
            </div>
          );
        })}
      </div>

      {/* Funnel Numbers & Cost */}
      {stats && (
        <div className="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-slate-800/80 text-xs text-slate-300">
          <div className="flex flex-wrap items-center gap-2">
            <Filter className="w-3.5 h-3.5 text-sky-400" />
            <span>
              漏斗：抓取 <b>{stats.collected ?? 0}</b> → 指标过滤{" "}
              <b>{stats.after_hard_filter ?? 0}</b> → 可替换初筛{" "}
              <b>{stats.after_screening ?? 0}</b> → 精拆收录{" "}
              <b className="text-emerald-400">{stats.analyzed ?? 0}</b>
            </span>
          </div>
          <div className="flex items-center gap-1.5 text-amber-300">
            <Coins className="w-3.5 h-3.5" />
            <span>
              Token: {((stats.input_tokens ?? 0) + (stats.output_tokens ?? 0)).toLocaleString()} ·
              预估 ¥{(stats.estimated_cost_cny ?? 0).toFixed(4)}
            </span>
          </div>
        </div>
      )}

      {stats?.warnings && stats.warnings.length > 0 && (
        <div className="text-xs text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded-xl px-3 py-2 space-y-1">
          {stats.warnings.map((w, i) => (
            <div key={i}>• {w}</div>
          ))}
        </div>
      )}

      {errorMessage && (
        <div className="text-xs text-rose-300 bg-rose-500/10 border border-rose-500/30 rounded-xl px-3 py-2">
          错误详情：{errorMessage}
        </div>
      )}
    </div>
  );
};
