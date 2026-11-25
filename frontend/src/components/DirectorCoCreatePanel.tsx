import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Copy,
  Edit3,
  Film,
  ImagePlus,
  ListChecks,
  Loader2,
  Lock,
  Plus,
  Scissors,
  SearchCheck,
  ShieldAlert,
  Sparkles,
  Trash2,
  Unlock,
  Wrench,
  X,
} from "lucide-react";
import { api } from "../api/client";
import { copyText } from "../utils/copy";
import type {
  DirectorMemoryItem,
  PromptReviewResponse,
  VideoDeepAnalysis,
  VideoRecord,
} from "../types/radar";

interface Props {
  video: VideoRecord;
  onAnalysisUpdated: (nextAnalysis: VideoDeepAnalysis) => void;
  onConfirmedGenerate?: () => void;
  onToast: (msg: string) => void;
}

const MEMORY_CATEGORY_LABELS: Record<string, { label: string; cls: string }> = {
  character: { label: "👤 人物偏好", cls: "bg-purple-500/20 text-purple-200 border-purple-500/40" },
  scene_style: { label: "🎨 场景调性", cls: "bg-sky-500/20 text-sky-200 border-sky-500/40" },
  product_replacement: {
    label: "💡 替换手法",
    cls: "bg-emerald-500/20 text-emerald-200 border-emerald-500/40",
  },
  pacing_framing: { label: "🎬 框架纪律", cls: "bg-amber-500/20 text-amber-200 border-amber-500/40" },
  taboo: { label: "🚫 避坑禁区", cls: "bg-rose-500/20 text-rose-200 border-rose-500/40" },
};

const VERDICT_META: Record<string, { label: string; cls: string }> = {
  accurate: {
    label: "✓ 核对吻合 · 与原视频逐帧一致",
    cls: "bg-emerald-500/20 border-emerald-400/50 text-emerald-200",
  },
  minor_gaps: {
    label: "🔧 发现局部可优化项 · 建议确认以下意见",
    cls: "bg-amber-500/20 border-amber-400/50 text-amber-200",
  },
  major_mismatch: {
    label: "⚠️ 发现关键镜头偏差 · 强烈建议按以下意见修正",
    cls: "bg-rose-500/20 border-rose-400/50 text-rose-200",
  },
};

export const DirectorCoCreatePanel: React.FC<Props> = ({
  video,
  onAnalysisUpdated,
  onConfirmedGenerate,
  onToast,
}) => {
  const analysis = video.analysis_json;
  const plan = analysis?.director_plan;
  const isLocked = plan?.revision_status === "locked";
  const hasCustomized = Boolean(plan?.has_user_customized);

  // Box 1: Original Video Frame-by-Frame Reference (collapsed by default so UI stays clean)
  const originalPromptCn =
    plan?.original_video_prompt_cn ||
    plan?.original_plot_summary ||
    (analysis?.storyboard || []).map((s) => s.original_visual).filter(Boolean).join("；") ||
    "正在读取原视频逐帧画面...";

  // Box 3: 4-Part Structured Output
  const auditReport = plan?.prompt_audit_report || null;
  const editingGuidelines = plan?.editing_guidelines || null;
  const globalRefCn = plan?.global_reference_prompt_cn || "";
  const revisedPromptCn = plan?.current_master_prompt_cn || "";
  const revisedPromptEn = plan?.current_master_prompt_en || "";
  const negativeConstraints =
    plan?.negative_constraints ||
    "避免产品换款、颜色漂移、纹理消失、配件增减、生成多余产品、人物换脸、手指畸形、穿模、场景漂移、画面文字或水印。";

  const keyframes = plan?.keyframe_previews || [];
  const keyframeTimestamps = plan?.keyframe_timestamps || [];
  const history = plan?.revision_history || [];
  const storyboard = analysis?.storyboard || [];
  const imagePrompts = analysis?.chatgpt_images_prompts || [];
  const klingPrompts = analysis?.kling_prompts || [];

  const [expanded, setExpanded] = useState(true);
  const [showOriginalBox, setShowOriginalBox] = useState(false);

  // Step 2A: Direct Product-Replaced Prompt Input -> Review ONLY
  const [productReplacedPrompt, setProductReplacedPrompt] = useState("");
  const [promptImages, setPromptImages] = useState<File[]>([]);
  const [reviewing, setReviewing] = useState(false);
  const [reviewError, setReviewError] = useState("");
  const [reviewResult, setReviewResult] = useState<PromptReviewResponse | null>(null);
  const [selectedFixIds, setSelectedFixIds] = useState<Record<string, boolean>>({});
  const [extraConfirmNote, setExtraConfirmNote] = useState("");

  // Step 2B: Apply Confirmed Fixes -> Finalize 4-Part Split Prompt Package
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState("");
  const [locking, setLocking] = useState(false);
  const [showCombinedMaster, setShowCombinedMaster] = useState(false);
  const [showEnglishPrompt, setShowEnglishPrompt] = useState(false);
  const [manualEditing, setManualEditing] = useState(false);
  const [manualGlobalRefCn, setManualGlobalRefCn] = useState(globalRefCn || revisedPromptCn);
  const [manualConstraints, setManualConstraints] = useState(negativeConstraints);

  const promptImgInputRef = useRef<HTMLInputElement | null>(null);
  const reviewBoxRef = useRef<HTMLDivElement | null>(null);
  const revisedBoxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setManualGlobalRefCn(globalRefCn || revisedPromptCn || originalPromptCn);
    setManualConstraints(negativeConstraints);
  }, [globalRefCn, revisedPromptCn, originalPromptCn, negativeConstraints]);

  // Long-term AI Director Memory Vault
  const [memories, setMemories] = useState<DirectorMemoryItem[]>([]);
  const [showMemories, setShowMemories] = useState(false);
  const [newRuleText, setNewRuleText] = useState("");
  const [newRuleCategory, setNewRuleCategory] = useState("product_replacement");
  const [savingRule, setSavingRule] = useState(false);

  const loadMemories = useCallback(async () => {
    try {
      const list = await api.getDirectorMemories();
      setMemories(list);
    } catch {
      // Ignore silent memory fetch failure
    }
  }, []);

  useEffect(() => {
    loadMemories();
  }, [loadMemories]);

  const activeMemoryCount = memories.filter((m) => m.is_active).length;

  const handleAddPromptImages = (incoming: FileList | null) => {
    if (!incoming) return;
    setPromptImages((prev) => {
      const next = [...prev];
      Array.from(incoming).forEach((f) => {
        if (!next.some((e) => e.name === f.name && e.size === f.size)) {
          next.push(f);
        }
      });
      return next.slice(0, 8);
    });
  };

  const handleRemovePromptImage = (idx: number) => {
    setPromptImages((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleAddMemory = async () => {
    const clean = newRuleText.trim();
    if (clean.length < 4) {
      onToast("请输入至少 4 个字的偏好规则");
      return;
    }
    setSavingRule(true);
    try {
      await api.createDirectorMemory({
        category: newRuleCategory,
        product_scope: "global",
        rule_summary: clean,
      });
      setNewRuleText("");
      await loadMemories();
      onToast("🧠 已记入长期记忆库！");
    } catch (err) {
      onToast(err instanceof Error ? err.message : "保存记忆失败");
    } finally {
      setSavingRule(false);
    }
  };

  const handleToggleMemory = async (item: DirectorMemoryItem) => {
    try {
      await api.updateDirectorMemory(item.id, { is_active: !item.is_active });
      await loadMemories();
    } catch {
      onToast("更新记忆状态失败");
    }
  };

  const handleDeleteMemory = async (id: string) => {
    try {
      await api.deleteDirectorMemory(id);
      setMemories((prev) => prev.filter((m) => m.id !== id));
      onToast("已移除该条记忆");
    } catch {
      onToast("删除记忆失败");
    }
  };

  const handleCopy = async (text: string, label: string) => {
    const ok = await copyText(text);
    if (ok) onToast(`已复制${label}`);
  };

  // Step 2A: Compare user's product-replaced prompt vs original video -> Review Opinions ONLY
  const handleRunReview = async () => {
    const cleanPrompt = productReplacedPrompt.trim();
    if (!cleanPrompt && promptImages.length === 0) {
      onToast("请先粘贴你替换商品后的提示词，或上传提示词截图");
      return;
    }
    setReviewing(true);
    setReviewError("");
    setApplyError("");
    try {
      const resp = await api.reviewProductReplacedPrompt(video.id, {
        productReplacedPromptText: cleanPrompt,
        promptImages,
      });
      setReviewResult(resp.review);
      const defaults: Record<string, boolean> = {};
      (resp.review.suggestions || []).forEach((s) => {
        defaults[s.id] = true;
      });
      setSelectedFixIds(defaults);
      onToast("🔍 已对照原视频逐帧完成比对！请查看下方核对意见并勾选要修改的项");
      setTimeout(() => {
        reviewBoxRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }, 100);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "对照原片核对失败";
      setReviewError(msg);
      onToast(msg);
    } finally {
      setReviewing(false);
    }
  };

  // Step 2B: Apply ONLY the user-confirmed suggestions & split into shot-by-shot 4-part package
  const handleApplyConfirmedFixes = async (skipAllSuggestions = false) => {
    const cleanPrompt = productReplacedPrompt.trim();
    if (!cleanPrompt && promptImages.length === 0) {
      onToast("请先提交你替换商品后的提示词");
      return;
    }

    const pickedLines: string[] = [];
    if (!skipAllSuggestions && reviewResult?.suggestions) {
      reviewResult.suggestions.forEach((s) => {
        if (selectedFixIds[s.id]) {
          pickedLines.push(`- 【${s.target_area}】${s.suggestion}`);
        }
      });
    }
    const extra = extraConfirmNote.trim();
    let modInstruction = "";
    if (pickedLines.length > 0 || extra) {
      modInstruction = [
        "【请严格以用户提交的“替换商品后提示词”为底稿，只修改以下用户确认采纳的意见，其余内容 100% 保留并按逐个独立镜头拆分（每次只写当前镜头动作，不重复塞入整套剧情）】：",
        ...pickedLines,
        extra ? `- 【用户额外补充】${extra}` : "",
      ]
        .filter(Boolean)
        .join("\n");
    } else {
      modInstruction =
        "【无需改动剧情，100% 忠实保留用户提交的“替换商品后提示词”，严格拆分为独立逐镜的关键帧生图提示词 + 可灵单镜动态提示词 + 统一约束 + 生成与剪辑重点】";
    }

    setApplying(true);
    setApplyError("");
    try {
      const resp = await api.auditRevisePrompt(video.id, {
        referencePromptText: cleanPrompt,
        modificationNotes: modInstruction,
        promptImages,
      });
      setManualEditing(false);
      onAnalysisUpdated(resp.analysis_json);
      await loadMemories();
      onToast("✅ 已按你确认的意见完成修改，并已逐镜拆分为四段式可执行提示词！");
      setTimeout(() => {
        revisedBoxRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }, 120);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "按确认意见生成失败";
      setApplyError(msg);
      onToast(msg);
    } finally {
      setApplying(false);
    }
  };

  const handleToggleLock = async (nextLocked: boolean) => {
    setLocking(true);
    try {
      const overrides = manualEditing
        ? {
            global_reference_prompt_cn: manualGlobalRefCn.trim() || undefined,
            negative_constraints: manualConstraints.trim() || undefined,
          }
        : undefined;
      const resp = await api.lockDirectorPlan(video.id, nextLocked, overrides);
      setManualEditing(false);
      onAnalysisUpdated(resp.analysis_json);
      if (nextLocked) {
        onToast("✅ 提示词已确认定稿！请在下方按逐个分镜依次生成关键帧图与可灵视频");
        onConfirmedGenerate?.();
      } else {
        setExpanded(true);
        onToast("已解锁提示词，你可以继续核对或微调");
      }
    } catch (err) {
      onToast(err instanceof Error ? err.message : "确认操作失败");
    } finally {
      setLocking(false);
    }
  };

  const reviewVerdictInfo = reviewResult
    ? VERDICT_META[reviewResult.verdict] || VERDICT_META.minor_gaps
    : null;
  const auditVerdictInfo = auditReport
    ? VERDICT_META[auditReport.verdict] || VERDICT_META.minor_gaps
    : null;

  return (
    <div
      className={`rounded-2xl border overflow-hidden transition ${
        isLocked
          ? "bg-emerald-950/20 border-emerald-500/40"
          : "bg-gradient-to-br from-sky-950/40 via-slate-950 to-indigo-950/30 border-sky-500/40"
      }`}
    >
      {/* Header Bar */}
      <div className="px-4 py-3.5 flex flex-wrap items-center justify-between gap-2 bg-slate-950/70 border-b border-slate-800/80">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center gap-2 text-left min-w-0"
        >
          {isLocked ? (
            <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
          ) : (
            <SearchCheck className="w-5 h-5 text-sky-400 shrink-0" />
          )}
          <div className="min-w-0">
            <div className="text-sm font-bold text-white flex flex-wrap items-center gap-2">
              <span>步骤 1：直接贴替换商品后的提示词 → 对照原片给意见 → 确认后拆分逐镜</span>
              <span
                className={`px-2 py-0.5 rounded-full text-[11px] font-semibold border ${
                  isLocked
                    ? "bg-emerald-500/20 border-emerald-400/50 text-emerald-200"
                    : hasCustomized
                    ? "bg-sky-500/20 border-sky-400/50 text-sky-200"
                    : reviewResult
                    ? "bg-amber-500/20 border-amber-400/50 text-amber-200"
                    : "bg-slate-800 border-slate-700 text-slate-300"
                }`}
              >
                {isLocked
                  ? "✓ 已定稿 · 下方逐镜单独生成"
                  : hasCustomized
                  ? "已拆分逐镜四段式提示词 · 请确认"
                  : reviewResult
                  ? "已出逐帧核对意见 · 请勾选确认"
                  : "已逐帧读取原视频 · 请直接粘贴替换商品后的提示词"}
              </span>
            </div>
            <p className="text-[11px] text-slate-400 mt-0.5">
              无需复制原视频提示词！直接贴入你替换好商品的提示词（可一次性粘全部分镜）→ AI 对照原片逐帧先给意见 → 你勾选确认后自动修改并拆成逐个独立分镜 + 剪辑重点。
            </p>
          </div>
          {expanded ? (
            <ChevronUp className="w-4 h-4 text-slate-400 shrink-0 ml-1" />
          ) : (
            <ChevronDown className="w-4 h-4 text-slate-400 shrink-0 ml-1" />
          )}
        </button>

        <div className="flex items-center gap-2 shrink-0 flex-wrap">
          <button
            type="button"
            onClick={() => {
              setShowMemories((v) => !v);
              if (!expanded) setExpanded(true);
            }}
            className={`px-3 py-1.5 rounded-xl border text-xs font-semibold inline-flex items-center gap-1.5 transition ${
              showMemories
                ? "bg-purple-500/25 border-purple-400 text-purple-100"
                : "bg-slate-900 hover:bg-slate-800 border-purple-500/40 text-purple-200"
            }`}
          >
            <Brain className="w-3.5 h-3.5 text-purple-400" />
            记忆库（{activeMemoryCount} 条）
          </button>
          {isLocked && (
            <button
              type="button"
              disabled={locking}
              onClick={() => handleToggleLock(false)}
              className="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold inline-flex items-center gap-1.5"
            >
              <Unlock className="w-3.5 h-3.5 text-amber-400" />
              解锁继续修改
            </button>
          )}
        </div>
      </div>

      {expanded && (
        <div className="p-4 space-y-4 text-xs">
          {/* Expandable Long-Term Director Memory Vault */}
          {showMemories && (
            <div className="bg-purple-950/25 border border-purple-500/40 rounded-xl p-3.5 space-y-3">
              <div>
                <div className="text-purple-200 font-bold flex items-center gap-1.5">
                  <Brain className="w-4 h-4 text-purple-400" />
                  AI 长期记忆库
                </div>
                <p className="text-[11px] text-slate-400 mt-0.5">
                  每次修改都会自动提炼你的替换手法与审美偏好，后续核对与拆分时自动参考。
                </p>
              </div>
              {memories.length === 0 ? (
                <div className="text-[11px] text-slate-400 bg-slate-950/60 rounded-lg px-3 py-2.5">
                  暂无记忆。
                </div>
              ) : (
                <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
                  {memories.map((m) => {
                    const meta =
                      MEMORY_CATEGORY_LABELS[m.category] ||
                      MEMORY_CATEGORY_LABELS.product_replacement;
                    return (
                      <div
                        key={m.id}
                        className={`rounded-lg px-2.5 py-2 border flex items-start justify-between gap-2 ${
                          m.is_active
                            ? "bg-slate-950/80 border-slate-800"
                            : "bg-slate-950/40 border-slate-800/50 opacity-55"
                        }`}
                      >
                        <div className="space-y-0.5 min-w-0">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className={`px-1.5 py-0.5 rounded border text-[10px] ${meta.cls}`}>
                              {meta.label}
                            </span>
                            {m.confidence_hits > 1 && (
                              <span className="text-[10px] text-emerald-300 font-semibold">
                                强化 ×{m.confidence_hits}
                              </span>
                            )}
                          </div>
                          <div className="text-slate-100 leading-relaxed">{m.rule_summary}</div>
                        </div>
                        <div className="flex items-center gap-1.5 shrink-0">
                          <button
                            type="button"
                            onClick={() => handleToggleMemory(m)}
                            className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-[10px] text-slate-300"
                          >
                            {m.is_active ? "已启用" : "已暂停"}
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDeleteMemory(m.id)}
                            className="p-1 rounded bg-slate-800 hover:bg-rose-500/20 text-slate-400 hover:text-rose-300"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
              <div className="flex flex-wrap sm:flex-nowrap items-center gap-1.5 pt-1 border-t border-purple-500/20">
                <select
                  value={newRuleCategory}
                  onChange={(e) => setNewRuleCategory(e.target.value)}
                  className="px-2 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-[11px] text-slate-200"
                >
                  <option value="product_replacement">💡 替换手法</option>
                  <option value="character">👤 人物偏好</option>
                  <option value="scene_style">🎨 场景调性</option>
                  <option value="pacing_framing">🎬 框架纪律</option>
                  <option value="taboo">🚫 避坑禁区</option>
                </select>
                <input
                  type="text"
                  value={newRuleText}
                  onChange={(e) => setNewRuleText(e.target.value)}
                  placeholder="手动添加一条长期偏好..."
                  className="flex-1 min-w-[180px] px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500"
                />
                <button
                  type="button"
                  disabled={savingRule || !newRuleText.trim()}
                  onClick={handleAddMemory}
                  className="px-3 py-1.5 rounded-lg bg-purple-500 hover:bg-purple-400 disabled:opacity-50 text-slate-950 font-bold text-[11px] inline-flex items-center gap-1 shrink-0"
                >
                  <Plus className="w-3 h-3" />
                  记住这条
                </button>
              </div>
            </div>
          )}

          {/* BOX 1: Original Video Real Timestamped Filmstrip (Reference Baseline) */}
          <div className="bg-slate-950/90 border border-slate-800 rounded-xl p-3.5 space-y-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="px-2.5 py-0.5 rounded-md font-bold text-[11px] bg-sky-500/20 border border-sky-500/40 text-sky-300 inline-flex items-center gap-1">
                <Film className="w-3.5 h-3.5" />
                ① 原视频已逐帧存档（{keyframes.length || 1} 帧切镜证据 · 比对时 AI 自动对照原片）
              </span>
              <button
                type="button"
                onClick={() => setShowOriginalBox((v) => !v)}
                className="px-2.5 py-1 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 text-[11px]"
              >
                {showOriginalBox ? "收起原片解析词" : "查看原片解析词"}
              </button>
            </div>

            {keyframes.length > 0 && (
              <div className="flex gap-2 overflow-x-auto pb-1">
                {keyframes.map((src, idx) => {
                  const ts = keyframeTimestamps[idx];
                  const label =
                    typeof ts === "number"
                      ? `${ts.toFixed(2)}s`
                      : idx === 0
                      ? "0.15s 首帧"
                      : `帧 #${idx + 1}`;
                  return (
                    <div key={idx} className="relative shrink-0">
                      <img
                        src={src}
                        alt={`原片画面 ${idx + 1}`}
                        className="h-20 w-auto rounded-lg border border-slate-700 object-cover"
                      />
                      <span className="absolute bottom-1 left-1 px-1.5 py-0.5 rounded bg-black/75 text-[10px] font-mono text-sky-200">
                        {label}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}

            {showOriginalBox && (
              <div className="text-xs text-slate-300 leading-relaxed whitespace-pre-wrap bg-slate-900/70 rounded-xl p-3 border border-slate-800/80 max-h-56 overflow-y-auto">
                {originalPromptCn}
              </div>
            )}
          </div>

          {/* BOX 2: Directly Paste Product-Replaced Prompt (Single Clean Input -> Review Opinions First!) */}
          <div className="bg-slate-950/95 border border-sky-500/45 rounded-xl p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="px-2.5 py-0.5 rounded-md font-bold text-[11px] bg-amber-500/20 border border-amber-500/40 text-amber-200">
                ② 直接贴入你「替换商品后」的提示词（可一次性粘全部分镜，或上传截图）
              </span>
              <span className="text-[11px] text-slate-400">
                无需复制原视频提示词 · 先由 AI 对照原片逐帧给意见
              </span>
            </div>

            {reviewError && (
              <div className="rounded-xl bg-rose-500/15 border border-rose-500/40 px-3 py-2 text-xs text-rose-200">
                逐帧比对失败：{reviewError}（请重试）
              </div>
            )}

            <textarea
              rows={7}
              value={productReplacedPrompt}
              onChange={(e) => setProductReplacedPrompt(e.target.value)}
              placeholder="直接把你替换好商品的完整提示词（全片统一参考 + 全部分镜提示词 + 统一约束）一次性粘贴在这里即可；下方也可补充上传提示词截图..."
              className="w-full px-3.5 py-2.5 rounded-xl bg-slate-900 border border-slate-700 focus:border-sky-400 focus:outline-none text-xs sm:text-sm text-slate-100 placeholder-slate-500 leading-relaxed"
            />

            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => promptImgInputRef.current?.click()}
                  className="px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 border border-dashed border-sky-500/50 text-[11px] text-sky-200 font-semibold inline-flex items-center gap-1.5"
                >
                  <ImagePlus className="w-3.5 h-3.5 text-sky-400" />
                  上传提示词截图（{promptImages.length}/8）
                </button>
                <input
                  ref={promptImgInputRef}
                  type="file"
                  accept="image/*"
                  multiple
                  className="hidden"
                  onChange={(e) => {
                    handleAddPromptImages(e.target.files);
                    e.target.value = "";
                  }}
                />
                {promptImages.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {promptImages.map((f, idx) => (
                      <span
                        key={`${f.name}-${idx}`}
                        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-slate-900 border border-slate-700 text-[11px] text-slate-200"
                      >
                        <span className="max-w-[120px] truncate">{f.name}</span>
                        <button
                          type="button"
                          onClick={() => handleRemovePromptImage(idx)}
                          className="text-slate-400 hover:text-rose-400"
                        >
                          <X className="w-3 h-3" />
                        </button>
                      </span>
                    ))}
                  </div>
                )}
              </div>

              <button
                type="button"
                disabled={
                  reviewing || (!productReplacedPrompt.trim() && promptImages.length === 0)
                }
                onClick={handleRunReview}
                className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-sky-500 to-cyan-400 hover:from-sky-400 hover:to-cyan-300 disabled:opacity-50 text-slate-950 font-bold text-xs inline-flex items-center gap-1.5 shadow-lg shadow-sky-500/20"
              >
                {reviewing ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <SearchCheck className="w-4 h-4" />
                )}
                {reviewing
                  ? "正在对照原视频逐帧比对..."
                  : "🔍 对照原片逐帧比对，给我修改意见"}
              </button>
            </div>
          </div>

          {/* BOX 2.5 (APPEARS AFTER REVIEW): AI Review Opinions -> User Confirms Which Fixes to Apply! */}
          {reviewResult && (
            <div
              ref={reviewBoxRef}
              className="rounded-xl bg-amber-950/20 border border-amber-500/45 p-4 space-y-3.5"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-bold text-amber-200 flex items-center gap-1.5">
                  <ListChecks className="w-4 h-4 text-amber-400" />
                  ③ 原片逐帧比对意见（请勾选你认可的修改项，确认后再修改并拆分逐镜）
                </span>
                {reviewVerdictInfo && (
                  <span
                    className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold border ${reviewVerdictInfo.cls}`}
                  >
                    {reviewVerdictInfo.label}
                  </span>
                )}
              </div>

              {reviewResult.summary && (
                <p className="text-xs text-slate-100 leading-relaxed bg-slate-950/70 rounded-lg px-3 py-2 border border-slate-800">
                  {reviewResult.summary}
                </p>
              )}

              {reviewResult.matched_points && reviewResult.matched_points.length > 0 && (
                <div className="bg-emerald-950/25 border border-emerald-500/25 rounded-lg p-2.5 space-y-1 text-[11px]">
                  <div className="font-bold text-emerald-300 flex items-center gap-1">
                    <CheckCircle2 className="w-3.5 h-3.5" /> 与原片一致 / 写得很好的地方
                  </div>
                  <ul className="space-y-0.5 text-emerald-100/90 list-disc list-inside">
                    {reviewResult.matched_points.map((pt, i) => (
                      <li key={i}>{pt}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Checkable Suggestions List */}
              {reviewResult.suggestions && reviewResult.suggestions.length > 0 ? (
                <div className="space-y-2">
                  <div className="text-[11px] font-bold text-amber-300">
                    建议修改项（勾选你同意修改的地方，不勾则保持你原词不动）：
                  </div>
                  {reviewResult.suggestions.map((sug) => {
                    const checked = Boolean(selectedFixIds[sug.id]);
                    return (
                      <label
                        key={sug.id}
                        className={`block rounded-xl p-3 border cursor-pointer transition ${
                          checked
                            ? "bg-slate-950/90 border-amber-400/60"
                            : "bg-slate-950/40 border-slate-800 opacity-70"
                        }`}
                      >
                        <div className="flex items-start gap-2.5">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(e) =>
                              setSelectedFixIds((prev) => ({
                                ...prev,
                                [sug.id]: e.target.checked,
                              }))
                            }
                            className="mt-0.5 rounded border-slate-600 bg-slate-900 text-amber-400"
                          />
                          <div className="space-y-1 min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className="px-2 py-0.5 rounded bg-amber-500/20 text-amber-200 font-bold text-[10px]">
                                {sug.target_area || "关键调整"}
                              </span>
                              {sug.priority === "high" && (
                                <span className="px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300 text-[10px] font-semibold">
                                  重点建议
                                </span>
                              )}
                            </div>
                            <div className="text-slate-300">
                              <span className="text-amber-300/90 font-semibold">原片比对发现：</span>
                              {sug.issue}
                            </div>
                            <div className="text-slate-100">
                              <span className="text-emerald-300 font-semibold">建议修改为：</span>
                              {sug.suggestion}
                            </div>
                          </div>
                        </div>
                      </label>
                    );
                  })}
                </div>
              ) : (
                <div className="text-xs text-emerald-300 bg-emerald-950/25 border border-emerald-500/30 rounded-lg px-3 py-2">
                  ✓ 核对无重大问题，可直接点下方按钮拆分为独立逐镜提示词！
                </div>
              )}

              {/* Optional short user note before applying */}
              <input
                type="text"
                value={extraConfirmNote}
                onChange={(e) => setExtraConfirmNote(e.target.value)}
                placeholder="（可选）如果你还有想额外补充微调的一句话，写在这里..."
                className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-700 focus:border-amber-400 focus:outline-none text-xs text-slate-100 placeholder-slate-500"
              />

              {applyError && (
                <div className="rounded-xl bg-rose-500/15 border border-rose-500/40 px-3 py-2 text-xs text-rose-200">
                  生成失败：{applyError}
                </div>
              )}

              <div className="flex flex-wrap items-center justify-end gap-2">
                <button
                  type="button"
                  disabled={applying}
                  onClick={() => handleApplyConfirmedFixes(true)}
                  className="px-3.5 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 border border-slate-700 text-slate-300 text-xs font-semibold"
                >
                  不采纳意见，直接按我原词拆分逐镜
                </button>
                <button
                  type="button"
                  disabled={applying}
                  onClick={() => handleApplyConfirmedFixes(false)}
                  className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-amber-400 to-orange-400 hover:from-amber-300 hover:to-orange-300 disabled:opacity-50 text-slate-950 font-bold text-xs inline-flex items-center gap-1.5 shadow-lg shadow-amber-500/20"
                >
                  {applying ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Wrench className="w-4 h-4" />
                  )}
                  {applying
                    ? "正在按你确认的意见修改并拆分逐镜..."
                    : "✅ 确认以上意见，修改对应部分并拆分为逐镜提示词"}
                </button>
              </div>
            </div>
          )}

          {/* BOX 3: Finalized 4-Part Production Package */}
          <div
            ref={revisedBoxRef}
            className={`rounded-xl p-4 space-y-4 border ${
              hasCustomized
                ? "bg-emerald-950/15 border-emerald-500/45"
                : "bg-slate-950/60 border-dashed border-slate-800"
            }`}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span
                className={`px-2.5 py-0.5 rounded-md font-bold text-[11px] ${
                  hasCustomized
                    ? "bg-emerald-500/20 border border-emerald-500/40 text-emerald-300"
                    : "bg-slate-800 text-slate-400"
                }`}
              >
                ④ 已修正并拆分的四段式可执行提示词包（逐镜独立隔离，确认后逐个分镜生成）
              </span>
              {hasCustomized && (
                <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                  <button
                    type="button"
                    onClick={() => setManualEditing((v) => !v)}
                    className="px-2.5 py-1 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 inline-flex items-center gap-1"
                  >
                    <Edit3 className="w-3 h-3 text-amber-400" />
                    {manualEditing ? "取消手改" : "手动微调"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowCombinedMaster((v) => !v)}
                    className="px-2.5 py-1 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300"
                  >
                    {showCombinedMaster ? "收起完整总稿" : "查看完整总稿"}
                  </button>
                  {revisedPromptEn && (
                    <button
                      type="button"
                      onClick={() => setShowEnglishPrompt((v) => !v)}
                      className="px-2.5 py-1 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300"
                    >
                      {showEnglishPrompt ? "收起英文版" : "英文版"}
                    </button>
                  )}
                </div>
              )}
            </div>

            {!hasCustomized ? (
              <div className="py-5 text-center text-xs text-slate-400">
                先在上方「② 贴入替换商品后的提示词」点<b>「🔍 对照原片逐帧比对，给我修改意见」</b>，勾选确认意见后，这里会生成：
                <br />
                <b>一、全片统一参考</b> + <b>二、独立逐镜对照表</b> + <b>三、全片统一约束</b> + <b>四、生成与剪辑注意事项及重点</b>。
              </div>
            ) : (
              <>
                {/* Audit Summary Strip */}
                {auditReport && (
                  <div className="rounded-xl bg-slate-950/90 border border-sky-500/30 p-3 space-y-1.5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-bold text-sky-200 flex items-center gap-1.5 text-[11px]">
                        <SearchCheck className="w-3.5 h-3.5 text-sky-400" />
                        本次修改核对摘要
                      </span>
                      {auditVerdictInfo && (
                        <span
                          className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${auditVerdictInfo.cls}`}
                        >
                          {auditVerdictInfo.label}
                        </span>
                      )}
                    </div>
                    {auditReport.summary && (
                      <p className="text-xs text-slate-200 leading-relaxed">{auditReport.summary}</p>
                    )}
                    {auditReport.fixes_applied && auditReport.fixes_applied.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 pt-0.5">
                        {auditReport.fixes_applied.map((fix, i) => (
                          <span
                            key={i}
                            className="px-2 py-0.5 rounded-md bg-sky-500/15 border border-sky-500/30 text-sky-200 text-[10px]"
                          >
                            🔧 {fix}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* PART 1: Global Reference Prompt */}
                <div className="bg-slate-950/90 border border-slate-800 rounded-xl p-3.5 space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <span className="font-bold text-emerald-300">
                        一、全片统一参考提示词
                      </span>
                      <span className="text-[11px] text-slate-400 ml-2">
                        锁定产品外观、统一人物、核心场景与摄影质感
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={() =>
                        handleCopy(
                          manualEditing ? manualGlobalRefCn : globalRefCn || revisedPromptCn,
                          "全片统一参考提示词"
                        )
                      }
                      className="px-2.5 py-1 rounded-lg bg-emerald-500/15 hover:bg-emerald-500/25 border border-emerald-400/40 text-emerald-200 text-[11px] font-semibold inline-flex items-center gap-1"
                    >
                      <Copy className="w-3 h-3" /> 复制第一部分
                    </button>
                  </div>
                  {manualEditing ? (
                    <textarea
                      rows={5}
                      value={manualGlobalRefCn}
                      onChange={(e) => setManualGlobalRefCn(e.target.value)}
                      className="w-full p-3 rounded-xl bg-slate-900 border border-amber-500/40 text-xs text-slate-100 leading-relaxed focus:outline-none"
                    />
                  ) : (
                    <div className="text-xs sm:text-sm text-slate-100 leading-relaxed whitespace-pre-wrap bg-slate-900/60 rounded-xl p-3 border border-slate-800/80">
                      {globalRefCn || revisedPromptCn}
                    </div>
                  )}
                </div>

                {/* PART 2: Shot-by-Shot Controllable Table */}
                {storyboard.length > 0 && (
                  <div className="bg-slate-950/90 border border-slate-800 rounded-xl p-3.5 space-y-2.5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <span className="font-bold text-sky-300">
                          二、已拆分为 {storyboard.length} 个独立可控镜头（逐镜单独生成，每次只跑当前镜头）
                        </span>
                      </div>
                    </div>

                    <div className="overflow-x-auto">
                      <table className="w-full text-left border-collapse text-xs">
                        <thead>
                          <tr className="border-b border-slate-800 text-[11px] text-slate-400">
                            <th className="py-2 pr-3 font-semibold whitespace-nowrap w-32">
                              镜头 / 建议时长
                            </th>
                            <th className="py-2 px-3 font-semibold min-w-[220px]">
                              关键帧图片内容（逐镜先出图确认）
                            </th>
                            <th className="py-2 pl-3 font-semibold min-w-[260px]">
                              独立图生视频提示词（仅当前镜头动作）
                            </th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-800/80">
                          {storyboard.map((shot, idx) => {
                            const imgPrompt =
                              imagePrompts[idx + 1] || imagePrompts[idx] || null;
                            const kling =
                              klingPrompts.find((k) => k.shot_no === shot.shot_no) ||
                              klingPrompts[idx] ||
                              null;
                            const keyframeDesc =
                              imgPrompt?.prompt_cn ||
                              shot.adapted_visual_for_product ||
                              shot.original_visual;
                            const motionDesc =
                              kling?.prompt_cn ||
                              kling?.prompt_en ||
                              shot.adapted_visual_for_product;
                            const title =
                              imgPrompt?.scene_title ||
                              kling?.scene_title ||
                              `镜头 ${shot.shot_no}`;

                            return (
                              <tr key={shot.shot_no || idx} className="align-top">
                                <td className="py-2.5 pr-3">
                                  <div className="font-bold text-white">{title}</div>
                                  <div className="text-[11px] text-slate-400 mt-0.5">
                                    {shot.time_range}
                                  </div>
                                  <div className="flex flex-wrap gap-1 mt-1">
                                    <span className="px-1.5 py-0.5 rounded bg-slate-900 border border-slate-700 text-[10px] text-slate-300">
                                      {shot.shot_size}
                                    </span>
                                    {shot.replication_action === "insert_product" && (
                                      <span className="px-1.5 py-0.5 rounded bg-emerald-500/15 border border-emerald-500/30 text-[10px] text-emerald-300">
                                        含商品
                                      </span>
                                    )}
                                  </div>
                                </td>
                                <td className="py-2.5 px-3 text-slate-200 leading-relaxed">
                                  <div className="whitespace-pre-wrap">{keyframeDesc}</div>
                                  <button
                                    type="button"
                                    onClick={() =>
                                      handleCopy(keyframeDesc, `镜头 ${shot.shot_no} 关键帧描述`)
                                    }
                                    className="mt-1.5 text-[10px] text-sky-400 hover:text-sky-300 inline-flex items-center gap-1"
                                  >
                                    <Copy className="w-3 h-3" /> 复制关键帧词
                                  </button>
                                </td>
                                <td className="py-2.5 pl-3 text-slate-100 leading-relaxed">
                                  <div className="whitespace-pre-wrap">{motionDesc}</div>
                                  <button
                                    type="button"
                                    onClick={() =>
                                      handleCopy(motionDesc, `镜头 ${shot.shot_no} 图生视频词`)
                                    }
                                    className="mt-1.5 text-[10px] text-emerald-400 hover:text-emerald-300 inline-flex items-center gap-1"
                                  >
                                    <Copy className="w-3 h-3" /> 复制图生视频词
                                  </button>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {/* PART 3: Global Negative Constraints */}
                <div className="bg-rose-950/20 border border-rose-500/30 rounded-xl p-3.5 space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-bold text-rose-300 flex items-center gap-1.5">
                      <ShieldAlert className="w-3.5 h-3.5" />
                      三、每段附加同一组统一约束
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        handleCopy(
                          manualEditing ? manualConstraints : negativeConstraints,
                          "全片统一约束"
                        )
                      }
                      className="text-[11px] text-rose-300 hover:text-rose-200 inline-flex items-center gap-1"
                    >
                      <Copy className="w-3 h-3" /> 复制约束
                    </button>
                  </div>
                  {manualEditing ? (
                    <textarea
                      rows={2}
                      value={manualConstraints}
                      onChange={(e) => setManualConstraints(e.target.value)}
                      className="w-full p-2.5 rounded-lg bg-slate-950 border border-rose-500/40 text-xs text-rose-100 focus:outline-none"
                    />
                  ) : (
                    <div className="text-xs text-rose-100/90 leading-relaxed whitespace-pre-wrap">
                      {negativeConstraints}
                    </div>
                  )}
                </div>

                {/* PART 4: Generation & Editing Guidelines + Final QA Checklist */}
                {editingGuidelines && (
                  <div className="bg-indigo-950/25 border border-indigo-500/35 rounded-xl p-3.5 space-y-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-bold text-indigo-200 flex items-center gap-1.5">
                        <Scissors className="w-3.5 h-3.5 text-indigo-400" />
                        四、生成顺序与剪辑注意事项及重点
                      </span>
                      <button
                        type="button"
                        onClick={() => {
                          const txt = [
                            "【生成顺序】",
                            ...(editingGuidelines.generation_order || []).map((x, i) => `${i + 1}. ${x}`),
                            "\n【转场与衔接重点】",
                            ...(editingGuidelines.transition_tips || []).map((x) => `- ${x}`),
                            "\n【音效与 Logo 叠加】",
                            ...(editingGuidelines.audio_and_overlay_tips || []).map((x) => `- ${x}`),
                            "\n【最终成片验收四项红线】",
                            ...(editingGuidelines.final_qa_checklist || []).map((x) => `✓ ${x}`),
                          ].join("\n");
                          handleCopy(txt, "生成与剪辑重点");
                        }}
                        className="text-[11px] text-indigo-300 hover:text-indigo-200 inline-flex items-center gap-1"
                      >
                        <Copy className="w-3 h-3" /> 复制剪辑指南
                      </button>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5 text-[11px]">
                      {editingGuidelines.generation_order?.length > 0 && (
                        <div className="bg-slate-950/75 border border-slate-800 rounded-lg p-2.5 space-y-1">
                          <div className="font-bold text-sky-300">1. 推荐逐镜生成顺序</div>
                          <ol className="list-decimal list-inside space-y-1 text-slate-200 leading-relaxed">
                            {editingGuidelines.generation_order.map((item, i) => (
                              <li key={i}>{item}</li>
                            ))}
                          </ol>
                        </div>
                      )}
                      {editingGuidelines.transition_tips?.length > 0 && (
                        <div className="bg-slate-950/75 border border-slate-800 rounded-lg p-2.5 space-y-1">
                          <div className="font-bold text-amber-300">2. 剪辑转场与衔接重点</div>
                          <ul className="list-disc list-inside space-y-1 text-slate-200 leading-relaxed">
                            {editingGuidelines.transition_tips.map((item, i) => (
                              <li key={i}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {editingGuidelines.audio_and_overlay_tips?.length > 0 && (
                        <div className="bg-slate-950/75 border border-slate-800 rounded-lg p-2.5 space-y-1">
                          <div className="font-bold text-purple-300">3. 声音与 Logo/文案叠加</div>
                          <ul className="list-disc list-inside space-y-1 text-slate-200 leading-relaxed">
                            {editingGuidelines.audio_and_overlay_tips.map((item, i) => (
                              <li key={i}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {editingGuidelines.final_qa_checklist?.length > 0 && (
                        <div className="bg-emerald-950/25 border border-emerald-500/25 rounded-lg p-2.5 space-y-1">
                          <div className="font-bold text-emerald-300">4. 最终成片验收红线</div>
                          <ul className="space-y-1 text-emerald-100/90 leading-relaxed">
                            {editingGuidelines.final_qa_checklist.map((item, i) => (
                              <li key={i} className="flex items-start gap-1.5">
                                <AlertTriangle className="w-3 h-3 text-emerald-400 shrink-0 mt-0.5" />
                                <span>{item}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* Optional Combined Master Prompt & English View */}
                {showCombinedMaster && revisedPromptCn && (
                  <div className="bg-slate-950/80 border border-slate-800 rounded-xl p-3 space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-bold text-slate-300">完整汇总总稿</span>
                      <button
                        type="button"
                        onClick={() => handleCopy(revisedPromptCn, "完整汇总总稿")}
                        className="text-[11px] text-sky-400 hover:text-sky-300 inline-flex items-center gap-1"
                      >
                        <Copy className="w-3 h-3" /> 复制总稿
                      </button>
                    </div>
                    <div className="text-xs text-slate-200 leading-relaxed whitespace-pre-wrap max-h-64 overflow-y-auto">
                      {revisedPromptCn}
                    </div>
                  </div>
                )}

                {showEnglishPrompt && revisedPromptEn && (
                  <div className="bg-slate-950/70 border border-slate-800 rounded-xl p-3 font-mono text-[11px] text-slate-300 leading-relaxed whitespace-pre-wrap max-h-60 overflow-y-auto">
                    {revisedPromptEn}
                  </div>
                )}

                {/* Primary Confirm & Enter Shot-by-Shot Production */}
                <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                  <span className="text-[11px] text-slate-400">
                    确认无误后点右侧按钮展开下方工作台，按<b>逐个分镜单独出图确认 → 逐个分镜生成可灵视频</b>执行！
                  </span>
                  {!isLocked ? (
                    <button
                      type="button"
                      disabled={locking}
                      onClick={() => handleToggleLock(true)}
                      className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-400 hover:from-emerald-400 hover:to-teal-300 disabled:opacity-50 text-slate-950 font-bold text-xs inline-flex items-center gap-1.5 shadow-lg shadow-emerald-500/20"
                    >
                      {locking ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <Sparkles className="w-4 h-4" />
                      )}
                      ✅ 确认定稿，进入逐镜生成工作台
                    </button>
                  ) : (
                    <span className="text-emerald-300 font-bold text-xs inline-flex items-center gap-1">
                      <Lock className="w-3.5 h-3.5" />
                      已确认定稿，请在下方按逐个分镜依次生图与生成视频
                    </span>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
