import React from "react";
import { Bot, Camera, ExternalLink, Eye, Heart, Sparkles } from "lucide-react";
import type { VideoRecord } from "../types/radar";
import { formatCompactNumber } from "../utils/copy";

interface Props {
  video: VideoRecord;
  onOpenDetail: (video: VideoRecord) => void;
}

const PLATFORM_STYLE: Record<string, { label: string; cls: string }> = {
  tiktok: {
    label: "TikTok",
    cls: "bg-cyan-500/20 text-cyan-300 border-cyan-500/40",
  },
  instagram: {
    label: "Instagram",
    cls: "bg-pink-500/20 text-pink-300 border-pink-500/40",
  },
  youtube: {
    label: "YouTube",
    cls: "bg-rose-500/20 text-rose-300 border-rose-500/40",
  },
};

export const VideoCard: React.FC<Props> = ({ video, onOpenDetail }) => {
  const plat = PLATFORM_STYLE[video.platform] || {
    label: video.platform.toUpperCase(),
    cls: "bg-slate-700 text-slate-200 border-slate-600",
  };
  const scoreColor =
    video.replaceability_score >= 85
      ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
      : "bg-sky-500/20 text-sky-300 border-sky-500/40";

  return (
    <div className="bg-slate-900/90 border border-slate-800 hover:border-sky-500/50 rounded-2xl overflow-hidden flex flex-col transition shadow-lg">
      {/* Cover */}
      <div
        onClick={() => onOpenDetail(video)}
        className="relative aspect-[16/10] bg-slate-950 overflow-hidden cursor-pointer group"
      >
        {video.cover_url ? (
          <img
            src={video.cover_url}
            alt={video.title}
            className="w-full h-full object-cover group-hover:scale-105 transition duration-300"
            loading="lazy"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-slate-600 text-xs">
            暂无封面预览
          </div>
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-slate-950/90 via-transparent to-slate-950/40" />

        <div className="absolute top-2.5 left-2.5 flex flex-wrap gap-1.5">
          <span className={`px-2 py-0.5 rounded-md text-[11px] font-semibold border ${plat.cls}`}>
            {plat.label}
          </span>
          <span
            className={`px-2 py-0.5 rounded-md text-[11px] font-semibold border inline-flex items-center gap-1 ${
              video.is_ai_generated
                ? "bg-purple-500/25 text-purple-200 border-purple-400/50"
                : "bg-slate-900/80 text-slate-200 border-slate-600"
            }`}
          >
            {video.is_ai_generated ? (
              <>
                <Bot className="w-3 h-3" /> AI 制作
              </>
            ) : (
              <>
                <Camera className="w-3 h-3" /> 实拍 + AI复刻
              </>
            )}
          </span>
        </div>

        <div className="absolute top-2.5 right-2.5">
          <span
            className={`px-2.5 py-0.5 rounded-full text-xs font-bold border ${scoreColor}`}
          >
            可替换 {video.replaceability_score}分
          </span>
        </div>

        <div className="absolute bottom-2.5 inset-x-3 flex items-center justify-between text-xs text-slate-200">
          <div className="flex items-center gap-3">
            <span className="inline-flex items-center gap-1 font-medium">
              <Eye className="w-3.5 h-3.5 text-sky-400" />
              {formatCompactNumber(video.views)}
            </span>
            <span className="inline-flex items-center gap-1 font-medium">
              <Heart className="w-3.5 h-3.5 text-rose-400" />
              {formatCompactNumber(video.likes)}
            </span>
          </div>
          <span className="text-[11px] text-slate-300">
            赞播比 {video.engagement_rate.toFixed(1)}%
          </span>
        </div>
      </div>

      {/* Body */}
      <div className="p-4 flex-1 flex flex-col justify-between space-y-3">
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-white line-clamp-2 leading-snug">
            {video.title || video.platform_video_id}
          </h3>
          <div className="text-xs text-slate-400 bg-slate-950/70 border border-slate-800 rounded-xl p-2.5 space-y-1">
            <div>
              <span className="text-slate-500">原核心物品：</span>
              <span className="text-sky-300 font-medium">
                {video.original_featured_item || "已识别实体展示位"}
              </span>
            </div>
            <p className="text-slate-300 line-clamp-2">
              {video.analysis_json?.replaceability?.replacement_strategy}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 pt-1">
          <button
            type="button"
            onClick={() => onOpenDetail(video)}
            className="flex-1 py-2.5 px-3 rounded-xl bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold text-xs flex items-center justify-center gap-1.5 transition"
          >
            <Sparkles className="w-3.5 h-3.5" />
            拆解 & 提示词
          </button>
          <a
            href={video.video_url}
            target="_blank"
            rel="noopener noreferrer"
            className="py-2.5 px-3 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium inline-flex items-center gap-1 transition shrink-0"
          >
            原视频
            <ExternalLink className="w-3.5 h-3.5" />
          </a>
        </div>
      </div>
    </div>
  );
};
