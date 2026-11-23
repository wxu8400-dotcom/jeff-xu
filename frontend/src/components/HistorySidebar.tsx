import React from "react";
import {
  Clock,
  Plus,
  Search,
  Trash2,
  X,
  CheckCircle2,
  Loader2,
  AlertTriangle,
} from "lucide-react";
import type { ScanSessionSummary } from "../types/radar";

interface Props {
  items: ScanSessionSummary[];
  activeId: string | null;
  searchQuery: string;
  onSearchChange: (q: string) => void;
  onSelect: (id: string) => void;
  onNewScan: () => void;
  onDelete: (id: string) => void;
  mobileOpen: boolean;
  onCloseMobile: () => void;
}

export const HistorySidebar: React.FC<Props> = ({
  items,
  activeId,
  searchQuery,
  onSearchChange,
  onSelect,
  onNewScan,
  onDelete,
  mobileOpen,
  onCloseMobile,
}) => {
  const renderStatusIcon = (status: string) => {
    if (status === "completed")
      return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />;
    if (status === "failed")
      return <AlertTriangle className="w-3.5 h-3.5 text-rose-400 shrink-0" />;
    return <Loader2 className="w-3.5 h-3.5 text-sky-400 animate-spin shrink-0" />;
  };

  const content = (
    <div className="flex flex-col h-full bg-slate-900/95 border-r border-slate-800 w-72 sm:w-80">
      <div className="p-4 border-b border-slate-800 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Clock className="w-4 h-4 text-sky-400 shrink-0" />
          <span className="font-semibold text-sm text-white truncate">
            历史记录（时间 · 产品名）
          </span>
        </div>
        <button
          type="button"
          onClick={onCloseMobile}
          className="lg:hidden p-1.5 rounded-lg text-slate-400 hover:bg-slate-800 hover:text-white"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="p-3 space-y-2.5 border-b border-slate-800/80">
        <button
          type="button"
          onClick={() => {
            onNewScan();
            onCloseMobile();
          }}
          className="w-full py-2.5 px-3 rounded-xl bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold text-sm flex items-center justify-center gap-1.5 transition"
        >
          <Plus className="w-4 h-4" />
          新建产品雷达扫描
        </button>

        <div className="relative">
          <Search className="w-3.5 h-3.5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="按产品名或日期搜索历史..."
            className="w-full pl-8 pr-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-sky-500"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2.5 space-y-1.5">
        {items.length === 0 ? (
          <div className="text-center py-10 px-4 text-xs text-slate-500">
            暂无历史扫描记录
            <br />
            上传产品并启动扫描后会自动按「时间 · 产品名」归档
          </div>
        ) : (
          items.map((item) => {
            const isSelected = activeId === item.id;
            return (
              <div
                key={item.id}
                onClick={() => {
                  onSelect(item.id);
                  onCloseMobile();
                }}
                className={`group relative rounded-xl p-3 cursor-pointer border transition ${
                  isSelected
                    ? "bg-sky-500/15 border-sky-500/40"
                    : "bg-slate-950/40 border-transparent hover:bg-slate-800/60 hover:border-slate-700"
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-start gap-2 min-w-0">
                    <div className="mt-0.5">{renderStatusIcon(item.status)}</div>
                    <div className="min-w-0">
                      <div className="text-xs font-semibold text-slate-100 leading-snug break-words">
                        {item.history_title}
                      </div>
                      <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-400">
                        <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300">
                          收录 {item.video_count} 条
                        </span>
                        <span>
                          {item.mode === "direct_urls" ? "链接直拆" : "三平台雷达"}
                        </span>
                      </div>
                    </div>
                  </div>
                  <button
                    type="button"
                    title="删除历史记录"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDelete(item.id);
                    }}
                    className="p-1.5 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 opacity-100 lg:opacity-0 lg:group-hover:opacity-100 transition shrink-0"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop persistent sidebar */}
      <aside className="hidden lg:block shrink-0 h-full">{content}</aside>

      {/* Mobile slide-over drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden flex">
          <div
            className="fixed inset-0 bg-black/60 backdrop-blur-sm"
            onClick={onCloseMobile}
          />
          <div className="relative z-10 h-full">{content}</div>
        </div>
      )}
    </>
  );
};
