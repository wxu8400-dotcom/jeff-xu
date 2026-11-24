import React from "react";
import { Link2, Radar, Sparkles } from "lucide-react";

export interface RadarFormParams {
  mode: "radar" | "direct_urls";
  searchStrategy: "cross_category" | "hybrid" | "same_category";
  creativeStyles: string[];
  platforms: string[];
  minViews: number;
  minLikes: number;
  dateRangeDays: number;
  targetCount: number;
  autoRelax: boolean;
  userInstruction: string;
  directUrls: string;
}

interface Props {
  params: RadarFormParams;
  onChange: (next: RadarFormParams) => void;
  submitting: boolean;
  onSubmit: () => void;
}

const PLATFORMS = [
  { id: "tiktok", label: "TikTok", color: "border-cyan-500/50 bg-cyan-500/15 text-cyan-300" },
  { id: "instagram", label: "Instagram Reels", color: "border-pink-500/50 bg-pink-500/15 text-pink-300" },
  { id: "youtube", label: "YouTube Shorts", color: "border-rose-500/50 bg-rose-500/15 text-rose-300" },
];

const CREATIVE_STYLES = [
  { id: "fooh_cgi", label: "FOOH 户外巨物 CGI" },
  { id: "3d_popout", label: "3D 悬浮 / 画册弹出" },
  { id: "ai_commercial", label: "AI 超现实大片" },
  { id: "vfx_transition", label: "无缝转场 / 脑洞运镜" },
  { id: "miniature_world", label: "微缩世界 / 定格动画" },
  { id: "luxury_aesthetic", label: "极简高级美学" },
];

export const RadarControls: React.FC<Props> = ({
  params,
  onChange,
  submitting,
  onSubmit,
}) => {
  const togglePlatform = (id: string) => {
    const exists = params.platforms.includes(id);
    if (exists && params.platforms.length === 1) return;
    onChange({
      ...params,
      platforms: exists
        ? params.platforms.filter((p) => p !== id)
        : [...params.platforms, id],
    });
  };

  const toggleCreativeStyle = (id: string) => {
    const exists = params.creativeStyles.includes(id);
    onChange({
      ...params,
      creativeStyles: exists
        ? params.creativeStyles.filter((s) => s !== id)
        : [...params.creativeStyles, id],
    });
  };

  return (
    <div className="space-y-4 pt-3 border-t border-slate-800">
      {/* Mode Switch */}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => onChange({ ...params, mode: "radar" })}
          className={`flex-1 sm:flex-none px-4 py-2 rounded-xl text-xs sm:text-sm font-medium flex items-center justify-center gap-1.5 border transition ${
            params.mode === "radar"
              ? "bg-sky-500/20 border-sky-400 text-sky-200"
              : "bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200"
          }`}
        >
          <Radar className="w-4 h-4" />
          三平台爆款实时雷达
        </button>
        <button
          type="button"
          onClick={() => onChange({ ...params, mode: "direct_urls" })}
          className={`flex-1 sm:flex-none px-4 py-2 rounded-xl text-xs sm:text-sm font-medium flex items-center justify-center gap-1.5 border transition ${
            params.mode === "direct_urls"
              ? "bg-purple-500/20 border-purple-400 text-purple-200"
              : "bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200"
          }`}
        >
          <Link2 className="w-4 h-4" />
          粘贴链接直接拆解
        </button>
      </div>

      {params.mode === "radar" ? (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-slate-400 mr-1">扫描平台：</span>
            {PLATFORMS.map((p) => {
              const active = params.platforms.includes(p.id);
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => togglePlatform(p.id)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition ${
                    active
                      ? p.color
                      : "bg-slate-950 border-slate-800 text-slate-500"
                  }`}
                >
                  {active ? "✓ " : ""}
                  {p.label}
                </button>
              );
            })}
          </div>

          {/* Search Strategy Selector */}
          <div className="space-y-1.5">
            <span className="text-xs text-slate-400">爆款搜寻策略：</span>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              {[
                {
                  id: "cross_category" as const,
                  title: "✨ 跨品类爆款模板（推荐）",
                  desc: "搜索词与产品 100% 解耦，绝不搜同品类；只抓全网创意爆款来替换物品",
                },
                {
                  id: "hybrid" as const,
                  title: "🔀 跨品类 + 同品类混合",
                  desc: "2 组纯跨品类爆款模板词 + 1 组同品类高热词",
                },
                {
                  id: "same_category" as const,
                  title: "🎯 仅搜同品类高热",
                  desc: "只搜与上传产品同一品类的热门视频",
                },
              ].map((st) => {
                const active = params.searchStrategy === st.id;
                return (
                  <button
                    key={st.id}
                    type="button"
                    onClick={() => onChange({ ...params, searchStrategy: st.id })}
                    className={`text-left p-2.5 rounded-xl border transition ${
                      active
                        ? "bg-sky-500/15 border-sky-400 text-sky-100"
                        : "bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700"
                    }`}
                  >
                    <div className="text-xs font-semibold">{st.title}</div>
                    <div className="text-[11px] opacity-80 mt-0.5 leading-snug">{st.desc}</div>
                  </button>
                );
              })}
            </div>
          </div>

          {params.searchStrategy !== "same_category" && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-slate-400">
                  爆款视觉创意模板（可多选，不选则全网跨品类爆款混搭）：
                </span>
                {params.creativeStyles.length > 0 && (
                  <button
                    type="button"
                    onClick={() => onChange({ ...params, creativeStyles: [] })}
                    className="text-[11px] text-sky-400 hover:text-sky-300"
                  >
                    恢复全网混搭
                  </button>
                )}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {CREATIVE_STYLES.map((style) => {
                  const active = params.creativeStyles.includes(style.id);
                  return (
                    <button
                      key={style.id}
                      type="button"
                      onClick={() => toggleCreativeStyle(style.id)}
                      className={`px-2.5 py-1.5 rounded-lg text-[11px] font-medium border transition ${
                        active
                          ? "bg-emerald-500/15 border-emerald-400/60 text-emerald-200"
                          : "bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700 hover:text-slate-200"
                      }`}
                    >
                      {active ? "✓ " : "+ "}
                      {style.label}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Quick presets */}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-slate-400">快捷门槛：</span>
            <button
              type="button"
              onClick={() =>
                onChange({ ...params, minViews: 50000, minLikes: 2000, dateRangeDays: 90 })
              }
              className="px-2.5 py-1 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-200"
            >
              5万播放 / 2千赞（创意广告推荐）
            </button>
            <button
              type="button"
              onClick={() =>
                onChange({ ...params, minViews: 100000, minLikes: 5000, dateRangeDays: 90 })
              }
              className="px-2.5 py-1 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-200"
            >
              10万播放 / 5千赞
            </button>
            <button
              type="button"
              onClick={() =>
                onChange({ ...params, minViews: 500000, minLikes: 20000, dateRangeDays: 90 })
              }
              className="px-2.5 py-1 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-200"
            >
              50万大爆款
            </button>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div>
              <label className="block text-[11px] text-slate-400 mb-1">最低播放量</label>
              <input
                type="number"
                min={0}
                step={10000}
                value={params.minViews}
                onChange={(e) =>
                  onChange({ ...params, minViews: Number(e.target.value) || 0 })
                }
                className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-sm text-slate-100"
              />
            </div>
            <div>
              <label className="block text-[11px] text-slate-400 mb-1">最低点赞数</label>
              <input
                type="number"
                min={0}
                step={500}
                value={params.minLikes}
                onChange={(e) =>
                  onChange({ ...params, minLikes: Number(e.target.value) || 0 })
                }
                className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-sm text-slate-100"
              />
            </div>
            <div>
              <label className="block text-[11px] text-slate-400 mb-1">发布时间（天内）</label>
              <select
                value={params.dateRangeDays}
                onChange={(e) =>
                  onChange({ ...params, dateRangeDays: Number(e.target.value) })
                }
                className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-sm text-slate-100"
              >
                <option value={7}>最近 7 天</option>
                <option value={30}>最近 30 天</option>
                <option value={90}>最近 90 天</option>
                <option value={0}>不限时间</option>
              </select>
            </div>
            <div>
              <label className="block text-[11px] text-slate-400 mb-1">
                精选收录条数（省 Token）
              </label>
              <select
                value={params.targetCount}
                onChange={(e) =>
                  onChange({ ...params, targetCount: Number(e.target.value) })
                }
                className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-sm text-slate-100"
              >
                <option value={3}>Top 3 条（最省）</option>
                <option value={5}>Top 5 条（推荐）</option>
                <option value={8}>Top 8 条</option>
                <option value={10}>Top 10 条</option>
              </select>
            </div>
          </div>

          <label className="inline-flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
            <input
              type="checkbox"
              checked={params.autoRelax}
              onChange={(e) => onChange({ ...params, autoRelax: e.target.checked })}
              className="rounded border-slate-600 bg-slate-900 text-sky-500"
            />
            候选视频偏少时自动阶梯放宽门槛（避免空结果）
          </label>
        </>
      ) : (
        <div>
          <label className="block text-xs font-medium text-slate-300 mb-1.5">
            粘贴 1~5 条 TikTok / Instagram Reels / YouTube Shorts 链接（每行一条）
          </label>
          <textarea
            rows={3}
            value={params.directUrls}
            onChange={(e) => onChange({ ...params, directUrls: e.target.value })}
            placeholder={"https://www.tiktok.com/@.../video/...\nhttps://www.instagram.com/reel/...\nhttps://www.youtube.com/shorts/..."}
            className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-700 text-xs sm:text-sm text-slate-100 placeholder-slate-500 font-mono"
          />
        </div>
      )}

      <div>
        <label className="block text-xs font-medium text-slate-300 mb-1.5">
          雷达搜索与拆解指令（可选）
        </label>
        <input
          type="text"
          value={params.userInstruction}
          onChange={(e) => onChange({ ...params, userInstruction: e.target.value })}
          placeholder="例如：优先找欧美风格、带强视觉反差或 AI 创意广告、单人桌面就能复刻的高转化爆款"
          className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-700 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-sky-400"
        />
      </div>

      <button
        type="button"
        disabled={submitting}
        onClick={onSubmit}
        className="w-full py-3.5 px-5 rounded-xl bg-gradient-to-r from-sky-500 to-cyan-400 hover:from-sky-400 hover:to-cyan-300 disabled:opacity-60 text-slate-950 font-bold text-sm sm:text-base shadow-lg shadow-sky-500/20 transition flex items-center justify-center gap-2"
      >
        <Sparkles className="w-4 h-4" />
        {submitting
          ? "雷达启动中..."
          : params.mode === "radar"
          ? "启动三平台高播高赞扫描雷达"
          : "开始深度拆解并生成可灵 & ChatGPT 提示词"}
      </button>
    </div>
  );
};
