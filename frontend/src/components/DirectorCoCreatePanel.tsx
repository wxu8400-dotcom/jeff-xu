import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowDownToLine,
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Copy,
  Edit3,
  Film,
  Loader2,
  Lock,
  MessageSquare,
  Plus,
  Send,
  ShieldAlert,
  Sparkles,
  Trash2,
  Unlock,
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

  // Box 1 (Immutable Original Video Full Prompt)
  const originalPromptCn =
    plan?.original_video_prompt_cn ||
    plan?.original_plot_summary ||
    (analysis?.storyboard || []).map((s) => s.original_visual).filter(Boolean).join("；") ||
    "正在读取原视频完整提示词...";

  // Box 3 (AI-Generated Revised Full Prompt + Constraints)
  const revisedPromptCn = plan?.current_master_prompt_cn || "";
  const revisedPromptEn = plan?.current_master_prompt_en || "";
  const negativeConstraints =
    plan?.negative_constraints ||
    "避免产品变形、颜色变化、纹理细节消失、多余手指、人物换脸、背景杂物带入、文字或水印。";

  const keyframes = plan?.keyframe_previews || [];
  const history = plan?.revision_history || [];

  const [expanded, setExpanded] = useState(true);
  const [feedback, setFeedback] = useState("");
  const [revising, setRevising] = useState(false);
  const [reviseError, setReviseError] = useState("");
  const [locking, setLocking] = useState(false);
  const [showEnglishPrompt, setShowEnglishPrompt] = useState(false);
  const [manualEditing, setManualEditing] = useState(false);
  const [manualTextCn, setManualTextCn] = useState(revisedPromptCn || originalPromptCn);

  const feedbackInputRef = useRef<HTMLTextAreaElement | null>(null);
  const revisedBoxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setManualTextCn(revisedPromptCn || originalPromptCn);
  }, [revisedPromptCn, originalPromptCn]);

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
      onToast("🧠 已记入长期记忆库，后续所有视频改写都会自动运用！");
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

  const handleLoadToEditor = (text: string, label: string) => {
    setFeedback(text);
    setReviseError("");
    onToast(`已将${label}载入修改框，直接改动你想改的词语再点生成即可！`);
    setTimeout(() => {
      feedbackInputRef.current?.focus();
    }, 50);
  };

  const handleCopy = async (text: string, label: string) => {
    const ok = await copyText(text);
    if (ok) onToast(`已复制${label}`);
  };

  const handleSendFeedback = async () => {
    const clean = feedback.trim();
    if (!clean) {
      onToast("请先写下你的修改意见，或点上方「一键载入到修改框」修改后再提交");
      return;
    }
    setRevising(true);
    setReviseError("");
    try {
      const resp = await api.reviseDirectorPlan(video.id, clean);
      setManualEditing(false);
      onAnalysisUpdated(resp.analysis_json);
      await loadMemories();
      const memCount = resp.learned_memories?.length || 0;
      const memHint = memCount > 0 ? `（并自动记住了 ${memCount} 条偏好 🧠）` : "";
      onToast(`✨ 已在下方生成更改后的完整提示词与排除约束${memHint}`);
      setTimeout(() => {
        revisedBoxRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }, 120);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "AI 重新生成提示词失败";
      setReviseError(msg);
      onToast(msg);
    } finally {
      setRevising(false);
    }
  };

  const handleToggleLock = async (nextLocked: boolean) => {
    setLocking(true);
    try {
      const overrides =
        manualEditing && manualTextCn.trim() && manualTextCn.trim() !== revisedPromptCn
          ? { master_prompt_cn: manualTextCn.trim() }
          : undefined;
      const resp = await api.lockDirectorPlan(video.id, nextLocked, overrides);
      setManualEditing(false);
      onAnalysisUpdated(resp.analysis_json);
      if (nextLocked) {
        onToast("✅ 提示词已确认定稿！现在可以直接在下方开始生成画面图与视频");
        onConfirmedGenerate?.();
      } else {
        setExpanded(true);
        onToast("已解锁提示词，你可以继续修改并重新生成");
      }
    } catch (err) {
      onToast(err instanceof Error ? err.message : "确认操作失败");
    } finally {
      setLocking(false);
    }
  };

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
            <MessageSquare className="w-5 h-5 text-sky-400 shrink-0" />
          )}
          <div className="min-w-0">
            <div className="text-sm font-bold text-white flex flex-wrap items-center gap-2">
              <span>步骤 1：原片提示词 → 修改意见 → 确认定稿</span>
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
                  ? "✓ 已确认定稿（下方正在/可开始制作视频）"
                  : hasCustomized
                  ? "已生成更改后提示词 · 请确认或继续修改"
                  : "已解析原片完整提示词 · 请写下修改意见"}
              </span>
            </div>
            <p className="text-[11px] text-slate-400 mt-0.5">
              先看框 1 原视频完整提示词 → 在框 2 写修改意见点击生成 → 在框 3 核对更改后的完整提示词与排除约束 → 满意点确认再开始生图与做视频。
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
              解锁继续修改提示词
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
                  每次修改都会自动提炼你的人物审美、场景调性与商品替换巧思，以后新视频改写时自动参考。
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
                  placeholder="手动添加一条长期偏好（如：优先使用欧美贵妇+奢华空间）"
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

          {/* Original Video Real Filmstrip Previews */}
          {keyframes.length > 0 && (
            <div className="space-y-1.5">
              <div className="text-[11px] text-slate-400 flex items-center gap-1.5">
                <Film className="w-3.5 h-3.5 text-sky-400" />
                原视频真实画面截帧（从 0.15 秒首帧到结尾）：
              </div>
              <div className="flex gap-2 overflow-x-auto pb-1">
                {keyframes.map((src, idx) => (
                  <div key={idx} className="relative shrink-0">
                    <img
                      src={src}
                      alt={`原片画面 ${idx + 1}`}
                      className="h-24 w-auto rounded-lg border border-slate-700 object-cover"
                    />
                    <span className="absolute bottom-1 left-1 px-1.5 py-0.5 rounded bg-black/70 text-[9px] text-slate-200">
                      {idx === 0 ? "开场首帧" : `画面 ${idx + 1}`}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* BOX 1 (FIXED): Original Video Complete Prompt */}
          <div className="bg-slate-950/95 border border-slate-800 rounded-xl p-4 space-y-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="px-2.5 py-0.5 rounded-md font-bold text-[11px] bg-sky-500/20 border border-sky-500/40 text-sky-300">
                ① 原视频 1:1 完整还原提示词（固定基准，不会被覆盖）
              </span>
              <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                <button
                  type="button"
                  onClick={() => handleLoadToEditor(originalPromptCn, "原视频完整提示词")}
                  className="px-2.5 py-1 rounded-lg bg-sky-500/20 hover:bg-sky-500/30 border border-sky-400/50 text-sky-200 font-semibold inline-flex items-center gap-1"
                >
                  <ArrowDownToLine className="w-3 h-3" />
                  一键载入下方修改框
                </button>
                <button
                  type="button"
                  onClick={() => handleCopy(originalPromptCn, "原视频完整提示词")}
                  className="px-2 py-1 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 inline-flex items-center gap-1"
                >
                  <Copy className="w-3 h-3 text-slate-400" />
                  复制
                </button>
              </div>
            </div>
            <div className="text-xs sm:text-sm text-slate-200 leading-relaxed whitespace-pre-wrap bg-slate-900/70 rounded-xl p-3.5 border border-slate-800/80 max-h-72 overflow-y-auto">
              {originalPromptCn}
            </div>
          </div>

          {/* BOX 2 (MIDDLE): User Modification Input */}
          <div className="bg-slate-950/95 border border-sky-500/40 rounded-xl p-4 space-y-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="px-2.5 py-0.5 rounded-md font-bold text-[11px] bg-amber-500/20 border border-amber-500/40 text-amber-200">
                ② 写下你要修改的地方（可点上方「一键载入」直接改字，或直接输入替换想法）
              </span>
              {hasCustomized && revisedPromptCn && (
                <button
                  type="button"
                  onClick={() => handleLoadToEditor(revisedPromptCn, "上一版更改后提示词")}
                  className="text-[11px] text-sky-400 hover:text-sky-300"
                >
                  载入上一版改写词继续微调
                </button>
              )}
            </div>

            {reviseError && (
              <div className="rounded-xl bg-rose-500/15 border border-rose-500/40 px-3 py-2 text-xs text-rose-200">
                生成失败：{reviseError}（请再点一次重试）
              </div>
            )}

            <textarea
              ref={feedbackInputRef}
              rows={4}
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  handleSendFeedback();
                }
              }}
              placeholder="例如：把炸鸡换成我上传的沙发，女人把缩小版沙发拿在手上扔下去火山口，炸出来正常尺寸沙发弹射落入豪华客机会客区，女人满意地坐上去开心大笑，直升机改为敞开舱门的豪华客机..."
              className="w-full px-3.5 py-2.5 rounded-xl bg-slate-900 border border-slate-700 focus:border-sky-400 focus:outline-none text-xs sm:text-sm text-slate-100 placeholder-slate-500 leading-relaxed"
            />

            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-[11px] text-slate-400">
                AI 会结合你上传的多角度商品图，在下方独立输出更改后的完整提示词与排除约束（可反复多轮修改）
              </span>
              <button
                type="button"
                disabled={revising || !feedback.trim()}
                onClick={handleSendFeedback}
                className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-sky-500 to-cyan-400 hover:from-sky-400 hover:to-cyan-300 disabled:opacity-50 text-slate-950 font-bold text-xs inline-flex items-center gap-1.5 shadow-lg shadow-sky-500/20"
              >
                {revising ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Send className="w-4 h-4" />
                )}
                {revising ? "AI 正在结合商品图生成完整提示词..." : "✨ 生成更改后的完整提示词"}
              </button>
            </div>
          </div>

          {/* BOX 3 (BELOW BOX 2 — INDEPENDENT): AI Revised Full Prompt + Constraints + Confirm Button */}
          <div
            ref={revisedBoxRef}
            className={`rounded-xl p-4 space-y-3 border ${
              hasCustomized
                ? "bg-emerald-950/20 border-emerald-500/45"
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
                ③ 更改后的完整提示词 & 统一排除约束（确认无误后点下方按钮开始制作视频）
              </span>
              {hasCustomized && (
                <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                  <button
                    type="button"
                    onClick={() => handleCopy(manualEditing ? manualTextCn : revisedPromptCn, "更改后的完整提示词")}
                    className="px-2.5 py-1 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-400/40 text-emerald-200 font-semibold inline-flex items-center gap-1"
                  >
                    <Copy className="w-3 h-3" />
                    一键复制总提示词
                  </button>
                  {revisedPromptEn && (
                    <button
                      type="button"
                      onClick={() => setShowEnglishPrompt((v) => !v)}
                      className="px-2 py-1 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300"
                    >
                      {showEnglishPrompt ? "收起英文" : "英文版"}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => setManualEditing((v) => !v)}
                    className="px-2 py-1 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 inline-flex items-center gap-1"
                  >
                    <Edit3 className="w-3 h-3 text-amber-400" />
                    {manualEditing ? "取消手改" : "手动微调"}
                  </button>
                </div>
              )}
            </div>

            {!hasCustomized ? (
              <div className="py-5 text-center text-xs text-slate-400">
                在上方「② 修改意见框」写下你想替换的内容并点击<b>「✨ 生成更改后的完整提示词」</b>，AI 会在这里输出可直接使用的完整总提示词和排除约束。
              </div>
            ) : (
              <>
                {manualEditing ? (
                  <textarea
                    rows={12}
                    value={manualTextCn}
                    onChange={(e) => setManualTextCn(e.target.value)}
                    className="w-full p-3.5 rounded-xl bg-slate-950 border border-amber-500/40 text-xs sm:text-sm text-slate-100 leading-relaxed focus:outline-none"
                  />
                ) : (
                  <div className="text-xs sm:text-sm text-slate-100 leading-relaxed whitespace-pre-wrap bg-slate-950/90 rounded-xl p-4 border border-slate-800 max-h-[460px] overflow-y-auto">
                    {revisedPromptCn}
                  </div>
                )}

                {showEnglishPrompt && revisedPromptEn && (
                  <div className="bg-slate-950/70 border border-slate-800 rounded-xl p-3 font-mono text-[11px] text-slate-300 leading-relaxed whitespace-pre-wrap max-h-60 overflow-y-auto">
                    {revisedPromptEn}
                  </div>
                )}

                {/* Dedicated Negative Constraints Box */}
                <div className="bg-rose-950/20 border border-rose-500/30 rounded-xl p-3 space-y-1.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] font-bold text-rose-300 flex items-center gap-1">
                      <ShieldAlert className="w-3.5 h-3.5" />
                      统一排除约束（减少生成变形与偏差）
                    </span>
                    <button
                      type="button"
                      onClick={() => handleCopy(negativeConstraints, "统一排除约束")}
                      className="text-[11px] text-rose-300 hover:text-rose-200 inline-flex items-center gap-1"
                    >
                      <Copy className="w-3 h-3" /> 复制约束
                    </button>
                  </div>
                  <div className="text-xs text-rose-100/90 leading-relaxed whitespace-pre-wrap">
                    {negativeConstraints}
                  </div>
                </div>

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
                    如果还有不满意，直接回到上面「② 修改意见框」继续改；确认无误后点右侧按钮进入制作！
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
                      ✅ 确认没问题，开始制作视频
                    </button>
                  ) : (
                    <span className="text-emerald-300 font-bold text-xs inline-flex items-center gap-1">
                      <Lock className="w-3.5 h-3.5" />
                      已确认定稿，请在下方执行生图与视频制作
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
