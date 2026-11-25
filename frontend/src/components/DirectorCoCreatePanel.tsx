import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowDownToLine,
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Copy,
  Edit3,
  Film,
  ImagePlus,
  Loader2,
  Lock,
  Plus,
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
import type { DirectorMemoryItem, VideoDeepAnalysis, VideoRecord } from "../types/radar";

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
    label: "🔧 发现局部遗漏 · 已按原片逐帧自动补全",
    cls: "bg-amber-500/20 border-amber-400/50 text-amber-200",
  },
  major_mismatch: {
    label: "⚠️ 发现关键镜头偏差 · 已按原片逐帧纠偏",
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

  // Box 1: Original Video Frame-by-Frame Reference
  const originalPromptCn =
    plan?.original_video_prompt_cn ||
    plan?.original_plot_summary ||
    (analysis?.storyboard || []).map((s) => s.original_visual).filter(Boolean).join("；") ||
    "正在读取原视频逐帧画面...";

  // Box 3: 3-Part Structured Output
  const auditReport = plan?.prompt_audit_report || null;
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
  const [referencePromptText, setReferencePromptText] = useState("");
  const [promptImages, setPromptImages] = useState<File[]>([]);
  const [modificationNotes, setModificationNotes] = useState("");
  const [revising, setRevising] = useState(false);
  const [reviseError, setReviseError] = useState("");
  const [locking, setLocking] = useState(false);
  const [showCombinedMaster, setShowCombinedMaster] = useState(false);
  const [showEnglishPrompt, setShowEnglishPrompt] = useState(false);
  const [manualEditing, setManualEditing] = useState(false);
  const [manualGlobalRefCn, setManualGlobalRefCn] = useState(globalRefCn || revisedPromptCn);
  const [manualConstraints, setManualConstraints] = useState(negativeConstraints);

  const promptImgInputRef = useRef<HTMLInputElement | null>(null);
  const refTextInputRef = useRef<HTMLTextAreaElement | null>(null);
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
      onToast("🧠 已记入长期记忆库，后续所有视频核对与改写都会自动运用！");
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

  const handleLoadToRefEditor = (text: string, label: string) => {
    setReferencePromptText(text);
    setReviseError("");
    onToast(`已将${label}载入参考提示词框`);
    setTimeout(() => {
      refTextInputRef.current?.focus();
    }, 50);
  };

  const handleCopy = async (text: string, label: string) => {
    const ok = await copyText(text);
    if (ok) onToast(`已复制${label}`);
  };

  const handleAuditAndGenerate = async () => {
    const cleanRef = referencePromptText.trim();
    const cleanMod = modificationNotes.trim();
    if (!cleanRef && !cleanMod && promptImages.length === 0) {
      onToast("请至少上传参考提示词截图、粘贴参考提示词，或写下你想修改的内容");
      return;
    }
    setRevising(true);
    setReviseError("");
    try {
      const resp = await api.auditRevisePrompt(video.id, {
        referencePromptText: cleanRef,
        modificationNotes: cleanMod,
        promptImages,
      });
      setManualEditing(false);
      onAnalysisUpdated(resp.analysis_json);
      await loadMemories();
      const memCount = resp.learned_memories?.length || 0;
      const memHint = memCount > 0 ? `（并记住 ${memCount} 条偏好 🧠）` : "";
      onToast(`✅ 已对照原片逐帧完成核对并生成新版三段式提示词${memHint}`);
      setTimeout(() => {
        revisedBoxRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }, 120);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "逐帧核对并生成提示词失败";
      setReviseError(msg);
      onToast(msg);
    } finally {
      setRevising(false);
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
        onToast("✅ 三段式提示词已确认定稿！现在可以直接在下方开始生成关键帧图与可灵视频");
        onConfirmedGenerate?.();
      } else {
        setExpanded(true);
        onToast("已解锁提示词，你可以继续核对或修改");
      }
    } catch (err) {
      onToast(err instanceof Error ? err.message : "确认操作失败");
    } finally {
      setLocking(false);
    }
  };

  const verdictInfo = auditReport
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
              <span>步骤 1：原片逐帧阅读 → 提示词比对核对 → 三段式新提示词定稿</span>
              <span
                className={`px-2 py-0.5 rounded-full text-[11px] font-semibold border ${
                  isLocked
                    ? "bg-emerald-500/20 border-emerald-400/50 text-emerald-200"
                    : hasCustomized
                    ? "bg-sky-500/20 border-sky-400/50 text-sky-200"
                    : "bg-amber-500/20 border-amber-400/50 text-amber-200"
                }`}
              >
                {isLocked
                  ? "✓ 已确认定稿（下方可生图确认与做视频）"
                  : hasCustomized
                  ? "已逐帧核对并生成三段式提示词 · 请确认"
                  : "已读取原片逐帧画面 · 请提交提示词与修改意见"}
              </span>
            </div>
            <p className="text-[11px] text-slate-400 mt-0.5">
              系统已对原视频执行切镜检测 + 逐帧存档。提交你的参考提示词（文字/截图）与修改内容，AI 会对照原片逐帧核对纠偏，并输出「统一参考 + 可控分镜表 + 统一约束」三段式提示词。
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
                  AI 长期记忆库（越聊越懂你的替换手法与审美偏好）
                </div>
                <p className="text-[11px] text-slate-400 mt-0.5">
                  每次修改都会自动提炼你的人物审美、场景调性与商品替换巧思，以后新视频核对改写时自动参考。
                </p>
              </div>
              {memories.length === 0 ? (
                <div className="text-[11px] text-slate-400 bg-slate-950/60 rounded-lg px-3 py-2.5">
                  暂无记忆。在下方提交一次修改想法，或手动添加一条偏好，系统就会自动记住！
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
                  placeholder="手动添加一条长期偏好（如：优先使用真实电影摄影质感+清晰产品主体）"
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

          {/* BOX 1: Original Video Real Timestamped Filmstrip + Collapsible Initial Transcript */}
          <div className="bg-slate-950/90 border border-slate-800 rounded-xl p-3.5 space-y-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="px-2.5 py-0.5 rounded-md font-bold text-[11px] bg-sky-500/20 border border-sky-500/40 text-sky-300 inline-flex items-center gap-1">
                  <Film className="w-3.5 h-3.5" />
                  ① 原视频已逐帧读取存档（共 {keyframes.length || 1} 帧切镜证据，核对时 AI 将直接对照真实原片画面）
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                <button
                  type="button"
                  onClick={() => handleLoadToRefEditor(originalPromptCn, "系统初版原片描述")}
                  className="px-2.5 py-1 rounded-lg bg-sky-500/15 hover:bg-sky-500/25 border border-sky-400/40 text-sky-200 font-semibold inline-flex items-center gap-1"
                >
                  <ArrowDownToLine className="w-3 h-3" />
                  载入初版原片描述
                </button>
                <button
                  type="button"
                  onClick={() => setShowOriginalBox((v) => !v)}
                  className="px-2.5 py-1 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300"
                >
                  {showOriginalBox ? "收起初版描述" : "查看系统初版描述"}
                </button>
              </div>
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
                        className="h-24 w-auto rounded-lg border border-slate-700 object-cover"
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
              <div className="text-xs text-slate-300 leading-relaxed whitespace-pre-wrap bg-slate-900/70 rounded-xl p-3 border border-slate-800/80 max-h-60 overflow-y-auto">
                {originalPromptCn}
              </div>
            )}
          </div>

          {/* BOX 2: Submit Reference Prompt (Text + Screenshots) & Modification Requirements */}
          <div className="bg-slate-950/95 border border-sky-500/45 rounded-xl p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="px-2.5 py-0.5 rounded-md font-bold text-[11px] bg-amber-500/20 border border-amber-500/40 text-amber-200">
                ② 提交你的参考提示词（文字或截图）+ 修改内容 → AI 对照原片逐帧核对并改写
              </span>
              {hasCustomized && globalRefCn && (
                <button
                  type="button"
                  onClick={() =>
                    handleLoadToRefEditor(
                      revisedPromptCn || globalRefCn,
                      "上一版核对后提示词"
                    )
                  }
                  className="text-[11px] text-sky-400 hover:text-sky-300"
                >
                  载入上一版继续微调
                </button>
              )}
            </div>

            {reviseError && (
              <div className="rounded-xl bg-rose-500/15 border border-rose-500/40 px-3 py-2 text-xs text-rose-200">
                核对生成失败：{reviseError}（请重试）
              </div>
            )}

            {/* Sub-section 2A: Reference Prompt (Screenshots + Text) */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              <div className="space-y-2">
                <label className="block text-[11px] font-semibold text-slate-300">
                  A. 你的参考提示词（可选：直接粘贴三段式文本，或在下方上传提示词截图）
                </label>
                <textarea
                  ref={refTextInputRef}
                  rows={5}
                  value={referencePromptText}
                  onChange={(e) => setReferencePromptText(e.target.value)}
                  placeholder="把你手头的参考提示词（如全片统一参考 + 分镜表 + 约束，或 Codex 拆解的文本）粘贴在这里；也可以留空只传截图或直接写右侧修改要求..."
                  className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 focus:border-sky-400 focus:outline-none text-xs text-slate-100 placeholder-slate-500 leading-relaxed"
                />

                {/* Prompt Screenshot Uploader */}
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => promptImgInputRef.current?.click()}
                    className="px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 border border-dashed border-sky-500/50 text-[11px] text-sky-200 font-semibold inline-flex items-center gap-1.5"
                  >
                    <ImagePlus className="w-3.5 h-3.5 text-sky-400" />
                    上传参考提示词截图（{promptImages.length}/8）
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
                    <span className="text-[11px] text-emerald-300">
                      已选 {promptImages.length} 张截图，提交时将与原片逐帧同屏核对
                    </span>
                  )}
                </div>

                {promptImages.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {promptImages.map((f, idx) => (
                      <span
                        key={`${f.name}-${idx}`}
                        className="inline-flex items-center gap-1 px-2 py-1 rounded-lg bg-slate-900 border border-slate-700 text-[11px] text-slate-200"
                      >
                        <span className="max-w-[140px] truncate">{f.name}</span>
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

              {/* Sub-section 2B: User Modification Notes */}
              <div className="space-y-2 flex flex-col">
                <label className="block text-[11px] font-semibold text-slate-300">
                  B. 你想修改的内容（替换商品、人物/场景调整、时长节奏等）
                </label>
                <textarea
                  rows={6}
                  value={modificationNotes}
                  onChange={(e) => setModificationNotes(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                      e.preventDefault();
                      handleAuditAndGenerate();
                    }
                  }}
                  placeholder="例如：把原片里的主角物品换成我上传的多角度商品，保持原片动作节奏和转场逻辑；如果原参考提示词有漏掉原片的关键转场，请按原视频逐帧帮我补齐修正..."
                  className="flex-1 w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 focus:border-sky-400 focus:outline-none text-xs text-slate-100 placeholder-slate-500 leading-relaxed"
                />
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
              <span className="text-[11px] text-slate-400">
                AI 会同时读取「原片带时间戳接触表 + 关键切镜帧 + 你的参考提示词 + 商品多角度图」，先核对纠偏再输出新版三段式提示词
              </span>
              <button
                type="button"
                disabled={
                  revising ||
                  (!referencePromptText.trim() &&
                    !modificationNotes.trim() &&
                    promptImages.length === 0)
                }
                onClick={handleAuditAndGenerate}
                className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-sky-500 to-cyan-400 hover:from-sky-400 hover:to-cyan-300 disabled:opacity-50 text-slate-950 font-bold text-xs inline-flex items-center gap-1.5 shadow-lg shadow-sky-500/20"
              >
                {revising ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <SearchCheck className="w-4 h-4" />
                )}
                {revising
                  ? "正在对照原片逐帧核对并生成三段式提示词..."
                  : "🔍 原片逐帧核对并生成新版三段式提示词"}
              </button>
            </div>
          </div>

          {/* BOX 3: Frame-by-Frame Audit Report + 3-Part Structured Prompt Package */}
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
                ③ 逐帧核对结论 & 新版三段式提示词（确认后直接驱动下方生图与可灵 I2V）
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
              <div className="py-6 text-center text-xs text-slate-400">
                在上方「② 提交参考提示词与修改内容」点击<b>「🔍 原片逐帧核对并生成新版三段式提示词」</b>，系统将在这里输出：
                <br />
                <b>原片逐帧核对报告</b> + <b>① 全片统一参考提示词</b> + <b>② 可控分镜表（关键帧图 + 图生视频动态词）</b> + <b>③ 统一约束</b>。
              </div>
            ) : (
              <>
                {/* 3.0 Frame-by-Frame Audit Report Card */}
                {auditReport && (
                  <div className="rounded-xl bg-slate-950/90 border border-sky-500/35 p-3.5 space-y-2.5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-bold text-sky-200 flex items-center gap-1.5">
                        <SearchCheck className="w-4 h-4 text-sky-400" />
                        原视频逐帧比对核对报告
                      </span>
                      {verdictInfo && (
                        <span
                          className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold border ${verdictInfo.cls}`}
                        >
                          {verdictInfo.label}
                        </span>
                      )}
                    </div>
                    {auditReport.summary && (
                      <p className="text-xs text-slate-200 leading-relaxed">
                        {auditReport.summary}
                      </p>
                    )}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-2.5 text-[11px]">
                      {auditReport.matched_points && auditReport.matched_points.length > 0 && (
                        <div className="bg-emerald-950/25 border border-emerald-500/25 rounded-lg p-2.5 space-y-1">
                          <div className="font-bold text-emerald-300 flex items-center gap-1">
                            <CheckCircle2 className="w-3.5 h-3.5" /> 核对无误点
                          </div>
                          <ul className="space-y-1 text-emerald-100/90 list-disc list-inside">
                            {auditReport.matched_points.map((pt, i) => (
                              <li key={i}>{pt}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {auditReport.issues_found && auditReport.issues_found.length > 0 && (
                        <div className="bg-amber-950/25 border border-amber-500/25 rounded-lg p-2.5 space-y-1">
                          <div className="font-bold text-amber-300 flex items-center gap-1">
                            <AlertTriangle className="w-3.5 h-3.5" /> 发现的原片遗漏/偏差
                          </div>
                          <ul className="space-y-1 text-amber-100/90 list-disc list-inside">
                            {auditReport.issues_found.map((pt, i) => (
                              <li key={i}>{pt}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {auditReport.fixes_applied && auditReport.fixes_applied.length > 0 && (
                        <div className="bg-sky-950/25 border border-sky-500/25 rounded-lg p-2.5 space-y-1">
                          <div className="font-bold text-sky-300 flex items-center gap-1">
                            <Wrench className="w-3.5 h-3.5" /> 已自动修正落实
                          </div>
                          <ul className="space-y-1 text-sky-100/90 list-disc list-inside">
                            {auditReport.fixes_applied.map((pt, i) => (
                              <li key={i}>{pt}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* PART 1: Global Reference Prompt */}
                <div className="bg-slate-950/90 border border-slate-800 rounded-xl p-3.5 space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <span className="font-bold text-emerald-300">
                        第一部分：全片统一参考提示词
                      </span>
                      <span className="text-[11px] text-slate-400 ml-2">
                        用于锁定产品外观、统一人物、核心场景与摄影质感
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
                      rows={6}
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

                {/* PART 2: Controllable Shot Table (Keyframe Image Prompt | I2V Motion Prompt) */}
                {storyboard.length > 0 && (
                  <div className="bg-slate-950/90 border border-slate-800 rounded-xl p-3.5 space-y-2.5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <span className="font-bold text-sky-300">
                          第二部分：拆分为 {storyboard.length} 个可控制的镜头
                        </span>
                        <span className="text-[11px] text-slate-400 ml-2">
                          每一行先按「关键帧图片内容」生图确认，再用右侧「图生视频动态提示词」交给可灵 I2V
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
                              关键帧图片内容（用于步骤 2 先出图确认）
                            </th>
                            <th className="py-2 pl-3 font-semibold min-w-[260px]">
                              可复制的图生视频提示词（用于可灵 I2V）
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
                                      handleCopy(motionDesc, `镜头 ${shot.shot_no} 图生视频提示词`)
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
                      第三部分：每段附加同一组统一约束（防换款、防变形、防穿帮）
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

                {/* Optional Combined Master Prompt & English View */}
                {showCombinedMaster && revisedPromptCn && (
                  <div className="bg-slate-950/80 border border-slate-800 rounded-xl p-3 space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-bold text-slate-300">
                        完整汇总总稿（一键整段复制）
                      </span>
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

                {/* Recent AI reply + learned memory badges */}
                {history.length > 0 && history[history.length - 1].role === "director" && (
                  <div className="bg-slate-950/70 border border-slate-800 rounded-xl px-3 py-2 text-[11px] text-slate-300 space-y-1">
                    <div>🤖 {history[history.length - 1].message}</div>
                    {history[history.length - 1].learned_memories &&
                      history[history.length - 1].learned_memories!.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 pt-0.5">
                          {history[history.length - 1].learned_memories!.map((rule, rIdx) => (
                            <span
                              key={rIdx}
                              className="px-2 py-0.5 rounded-md bg-purple-500/20 border border-purple-400/40 text-purple-200 text-[10px]"
                            >
                              🧠 已记住：{rule}
                            </span>
                          ))}
                        </div>
                      )}
                  </div>
                )}

                {/* Primary Confirm & Start Video Production Button */}
                <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                  <span className="text-[11px] text-slate-400">
                    核对三段式提示词无误后，点右侧按钮直接进入下方「关键帧生图确认（支持单图中文修正）→ 可灵生视频 → 成片合成」！
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
                      ✅ 确认没问题，进入生图确认与视频制作
                    </button>
                  ) : (
                    <span className="text-emerald-300 font-bold text-xs inline-flex items-center gap-1">
                      <Lock className="w-3.5 h-3.5" />
                      已确认定稿，请在下方执行生图确认与视频制作
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
