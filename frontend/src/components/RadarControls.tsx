import React, { useRef } from "react";
import { FileText, Film, ImagePlus, Link2, Radar, Sparkles, X } from "lucide-react";

export interface RadarFormParams {
  mode: "prompt_import" | "direct_urls" | "radar";
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
  promptImages: File[];
  promptText: string;
  storyboardText: string;
  requirementsFile: File | null;
  storyboardFile: File | null;
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
  { id: "vfx_transition", label: "真人无缝转场 / 脑洞运镜" },
  { id: "luxury_aesthetic", label: "真人高级生活方式大片" },
  { id: "ai_commercial", label: "写实 AI 真人大片" },
  { id: "fooh_cgi", label: "FOOH 街头真人实景 CGI" },
  { id: "3d_popout", label: "实景 3D 悬浮 / 特效弹出" },
  { id: "miniature_world", label: "写实微缩小人国" },
];

export const RadarControls: React.FC<Props> = ({
  params,
  onChange,
  submitting,
  onSubmit,
}) => {
  const promptImgRef = useRef<HTMLInputElement | null>(null);
  const reqFileRef = useRef<HTMLInputElement | null>(null);
  const sbFileRef = useRef<HTMLInputElement | null>(null);

  const handleSelectReqFile = async (file: File | null) => {
    if (!file) return;
    let text = params.promptText;
    const lower = file.name.toLowerCase();
    if (lower.endsWith(".txt") || lower.endsWith(".md")) {
      try {
        const read = await file.text();
        if (read.trim()) text = read.trim();
      } catch {
        // backend parses fallback
      }
    }
    onChange({ ...params, requirementsFile: file, promptText: text });
  };

  const handleSelectSbFile = async (file: File | null) => {
    if (!file) return;
    let text = params.storyboardText;
    const lower = file.name.toLowerCase();
    if (lower.endsWith(".txt") || lower.endsWith(".md")) {
      try {
        const read = await file.text();
        if (read.trim()) text = read.trim();
      } catch {
        // backend parses fallback
      }
    }
    onChange({ ...params, storyboardFile: file, storyboardText: text });
  };

  const addPromptImages = (incoming: FileList | null) => {
    if (!incoming) return;
    const next = [...params.promptImages];
    Array.from(incoming).forEach((f) => {
      if (!next.some((e) => e.name === f.name && e.size === f.size)) {
        next.push(f);
      }
    });
    onChange({ ...params, promptImages: next.slice(0, 10) });
  };

  const removePromptImage = (idx: number) => {
    onChange({
      ...params,
      promptImages: params.promptImages.filter((_, i) => i !== idx),
    });
  };

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
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => onChange({ ...params, mode: "direct_urls" })}
          className={`flex-1 sm:flex-none px-4 py-2 rounded-xl text-xs sm:text-sm font-bold flex items-center justify-center gap-1.5 border transition ${
            params.mode === "direct_urls"
              ? "bg-sky-500/20 border-sky-400 text-sky-200"
              : "bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200"
          }`}
        >
          <Link2 className="w-4 h-4" />
          🔗 粘贴原视频链接逐帧解析（推荐）
        </button>
        <button
          type="button"
          onClick={() => onChange({ ...params, mode: "prompt_import" })}
          className={`flex-1 sm:flex-none px-4 py-2 rounded-xl text-xs sm:text-sm font-bold flex items-center justify-center gap-1.5 border transition ${
            params.mode === "prompt_import"
              ? "bg-emerald-500/20 border-emerald-400 text-emerald-200"
              : "bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200"
          }`}
        >
          <FileText className="w-4 h-4" />
          📄 双文件创作直出（要求 + 分镜）
        </button>
        <button
          type="button"
          onClick={() => onChange({ ...params, mode: "radar" })}
          className={`flex-1 sm:flex-none px-4 py-2 rounded-xl text-xs sm:text-sm font-medium flex items-center justify-center gap-1.5 border transition ${
            params.mode === "radar"
              ? "bg-purple-500/20 border-purple-400 text-purple-200"
              : "bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200"
          }`}
        >
          <Radar className="w-4 h-4" />
          三平台爆款搜索
        </button>
      </div>

      {params.mode === "prompt_import" ? (
        <div className="space-y-3.5 bg-emerald-950/15 border border-emerald-500/30 rounded-2xl p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-bold text-emerald-200">
              上传你的两个创作文件（视频要求提示词 + 分镜内容），AI 深度理解并自然拆解为逐镜制作包
            </span>
            <span className="text-[11px] text-emerald-300/90">
              ✓ 支持 .txt / .md / .docx 或直接粘贴，不强制照搬原片，保证新视频自然流畅
            </span>
          </div>

          {/* Two-File Upload Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {/* File 1: Video Requirements Prompt */}
            <div className="bg-slate-950/80 border border-emerald-500/30 rounded-xl p-3 space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-1.5">
                <span className="text-xs font-bold text-emerald-300">
                  📄 文件 1：视频要求提示词
                </span>
                <button
                  type="button"
                  onClick={() => reqFileRef.current?.click()}
                  className="px-2.5 py-1 rounded-lg bg-emerald-500/15 hover:bg-emerald-500/25 border border-dashed border-emerald-400/60 text-[11px] text-emerald-200 font-semibold inline-flex items-center gap-1"
                >
                  <FileText className="w-3 h-3 text-emerald-400" />
                  选择文件（.txt/.md/.docx）
                </button>
                <input
                  ref={reqFileRef}
                  type="file"
                  accept=".txt,.md,.docx,text/plain,text/markdown,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  className="hidden"
                  onChange={(e) => {
                    handleSelectReqFile(e.target.files?.[0] || null);
                    e.target.value = "";
                  }}
                />
              </div>
              {params.requirementsFile && (
                <div className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md bg-emerald-950/70 border border-emerald-500/40 text-[11px] text-emerald-200">
                  <FileText className="w-3 h-3 text-emerald-400" />
                  <span className="max-w-[180px] truncate">{params.requirementsFile.name}</span>
                  <button
                    type="button"
                    onClick={() => onChange({ ...params, requirementsFile: null })}
                    className="text-emerald-300/80 hover:text-rose-400"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              )}
              <textarea
                rows={4}
                value={params.promptText}
                onChange={(e) => onChange({ ...params, promptText: e.target.value })}
                placeholder="上传文件 1 后会自动显示，也可直接粘贴（全片风格、产品要求、人物场景设定、排除约束、剪辑与声音思路）..."
                className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 focus:border-emerald-400 focus:outline-none text-xs text-slate-100 placeholder-slate-500 leading-relaxed"
              />
            </div>

            {/* File 2: Storyboard Content */}
            <div className="bg-slate-950/80 border border-sky-500/30 rounded-xl p-3 space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-1.5">
                <span className="text-xs font-bold text-sky-300">
                  🎬 文件 2：分镜内容
                </span>
                <button
                  type="button"
                  onClick={() => sbFileRef.current?.click()}
                  className="px-2.5 py-1 rounded-lg bg-sky-500/15 hover:bg-sky-500/25 border border-dashed border-sky-400/60 text-[11px] text-sky-200 font-semibold inline-flex items-center gap-1"
                >
                  <Film className="w-3 h-3 text-sky-400" />
                  选择文件（.txt/.md/.docx）
                </button>
                <input
                  ref={sbFileRef}
                  type="file"
                  accept=".txt,.md,.docx,text/plain,text/markdown,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  className="hidden"
                  onChange={(e) => {
                    handleSelectSbFile(e.target.files?.[0] || null);
                    e.target.value = "";
                  }}
                />
              </div>
              {params.storyboardFile && (
                <div className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md bg-sky-950/70 border border-sky-500/40 text-[11px] text-sky-200">
                  <Film className="w-3 h-3 text-sky-400" />
                  <span className="max-w-[180px] truncate">{params.storyboardFile.name}</span>
                  <button
                    type="button"
                    onClick={() => onChange({ ...params, storyboardFile: null })}
                    className="text-sky-300/80 hover:text-rose-400"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              )}
              <textarea
                rows={4}
                value={params.storyboardText}
                onChange={(e) => onChange({ ...params, storyboardText: e.target.value })}
                placeholder="上传文件 2 后会自动显示，也可直接粘贴（镜头 1、镜头 2... 的关键帧图片内容、图生视频动态提示词与建议时长）..."
                className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 focus:border-sky-400 focus:outline-none text-xs text-slate-100 placeholder-slate-500 leading-relaxed"
              />
            </div>
          </div>

          {/* Optional Prompt Screenshots */}
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => promptImgRef.current?.click()}
              className="px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 border border-dashed border-slate-700 text-[11px] text-slate-300 inline-flex items-center gap-1.5"
            >
              <ImagePlus className="w-3.5 h-3.5 text-emerald-400" />
              补充上传提示词截图（可选 {params.promptImages.length}/10）
            </button>
            <input
              ref={promptImgRef}
              type="file"
              multiple
              accept="image/*"
              className="hidden"
              onChange={(e) => {
                addPromptImages(e.target.files);
                e.target.value = "";
              }}
            />
            {params.promptImages.map((imgFile, idx) => (
              <span
                key={`${imgFile.name}-${idx}`}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-slate-900 border border-emerald-500/40 text-[11px] text-emerald-100"
              >
                <span className="max-w-[140px] truncate">{imgFile.name}</span>
                <button
                  type="button"
                  onClick={() => removePromptImage(idx)}
                  className="text-slate-400 hover:text-rose-400"
                >
                  <X className="w-3 h-3" />
                </button>
              </span>
            ))}
          </div>
        </div>
      ) : params.mode === "radar" ? (
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
            <span className="px-2.5 py-1 rounded-lg bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 text-[11px] font-medium">
              ✓ 仅搜真人 / 写实 AI 真人（自动屏蔽动漫卡通）
            </span>
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
        <div className="space-y-1.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <label className="block text-xs font-medium text-slate-200">
              粘贴 1~5 条 TikTok / Instagram / YouTube 爆款视频链接（每行一条，支持直接粘贴手机 App 复制的带文字分享口令）
            </label>
            <span className="text-[11px] text-emerald-300">
              ✓ 自动走高速通道拉取无水印原片画面做 1:1 逐镜拆解
            </span>
          </div>
          <textarea
            rows={3}
            value={params.directUrls}
            onChange={(e) => onChange({ ...params, directUrls: e.target.value })}
            placeholder={"支持长链接、短链及 App 分享文案：\nhttps://vt.tiktok.com/ZSxxxxxx/  或  https://www.tiktok.com/@.../video/...\nhttps://www.instagram.com/reel/...\nhttps://www.youtube.com/shorts/..."}
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
        className="w-full py-3.5 px-5 rounded-xl bg-gradient-to-r from-emerald-500 via-sky-500 to-cyan-400 hover:from-emerald-400 hover:to-cyan-300 disabled:opacity-60 text-slate-950 font-bold text-sm sm:text-base shadow-lg shadow-sky-500/20 transition flex items-center justify-center gap-2"
      >
        <Sparkles className="w-4 h-4" />
        {submitting
          ? "正在启动处理..."
          : params.mode === "prompt_import"
          ? "🚀 识别提示词截图，直接进入生图 & 可灵视频制作"
          : params.mode === "radar"
          ? "启动三平台高播高赞扫描雷达"
          : "开始深度拆解并生成完整提示词"}
      </button>
    </div>
  );
};
