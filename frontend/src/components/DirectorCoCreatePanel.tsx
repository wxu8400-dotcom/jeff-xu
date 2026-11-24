import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowDownToLine,
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Copy,
  Edit3,
  Eye,
  Film,
  Loader2,
  Lock,
  MessageSquare,
  Plus,
  Send,
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

  // Build fallback continuous prompt cleanly if viewing an older record created before V2.3
  const fallbackOriginalPrompt =
    plan?.original_video_prompt_cn ||
    plan?.original_plot_summary ||
    (analysis?.storyboard || []).map((s) => s.original_visual).filter(Boolean).join("；") ||
    "正在读取原视频画面提示词...";

  const currentPromptCn =
    plan?.current_master_prompt_cn ||
    (hasCustomized
      ? (analysis?.storyboard || []).map((s) => s.adapted_visual_for_product).filter(Boolean).join("；")
      : fallbackOriginalPrompt);

  const currentPromptEn = plan?.current_master_prompt_en || plan?.original_video_prompt_en || "";
  const keyframes = plan?.keyframe_previews || [];
  const history = plan?.revision_history || [];

  const [expanded, setExpanded] = useState(true);
  const [feedback, setFeedback] = useState("");
  const [revising, setRevising] = useState(false);
  const [reviseError, setReviseError] = useState("");
  const [locking, setLocking] = useState(false);
  const [showOriginalRef, setShowOriginalRef] = useState(false);
  const [showEnglishPrompt, setShowEnglishPrompt] = useState(false);
  const [manualEditing, setManualEditing] = useState(false);
  const [manualTextCn, setManualTextCn] = useState(currentPromptCn);
  const feedbackInputRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    setManualTextCn(currentPromptCn);
  }, [currentPromptCn]);

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

  const handleSendFeedback = async () => {
    const clean = feedback.trim();
    if (!clean) {
      onToast("请先写下你的修改意见或载入提示词修改后再提交");
      return;
    }
    setRevising(true);
    setReviseError("");
    try {
      const resp = await api.reviseDirectorPlan(video.id, clean);
      setFeedback("");
      setManualEditing(false);
      onAnalysisUpdated(resp.analysis_json);
      await loadMemories();
      const memCount = resp.learned_memories?.length || 0;
      const memHint = memCount > 0 ? `（并自动记住了 ${memCount} 条偏好 🧠）` : "";
      onToast(`✨ 已按你的意见重新编写好提示词${memHint}`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "AI 重新编写提示词失败";
      setReviseError(msg);
      onToast(msg);
    } finally {
      setRevising(false);
    }
  };

  const handleLoadPromptToEditor = () => {
    setFeedback(currentPromptCn);
    setReviseError("");
    onToast("已将完整提示词载入下方修改框，直接改动你想改的词语再点提交即可！");
    setTimeout(() => {
      feedbackInputRef.current?.focus();
    }, 50);
  };

  const handleCopyPrompt = async () => {
    const ok = await copyText(currentPromptCn);
    if (ok) onToast("已复制完整提示词");
  };

  const handleToggleLock = async (nextLocked: boolean) => {
    setLocking(true);
    try {
      const overrides =
        manualEditing && manualTextCn.trim() && manualTextCn.trim() !== currentPromptCn
          ? { master_prompt_cn: manualTextCn.trim() }
          : undefined;
      const resp = await api.lockDirectorPlan(video.id, nextLocked, overrides);
      setManualEditing(false);
      onAnalysisUpdated(resp.analysis_json);
      if (nextLocked) {
        onToast("✅ 提示词已确认定稿！现在可以直接在下方点击生成画面与视频");
        onConfirmedGenerate?.();
      } else {
        setExpanded(true);
        onToast("已解锁提示词，你可以继续发意见修改");
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
              <span>步骤 1：原视频提示词还原 & 按你的意见改写</span>
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
                  ? "✓ 已确认无误（下方可直接生成）"
                  : hasCustomized
                  ? "已按你意见改写 · 可继续修改或确认"
                  : "已还原原视频提示词 · 等待你的修改意见"}
              </span>
            </div>
            <p className="text-[11px] text-slate-400 mt-0.5">
              先核对原视频还原的提示词 → 写下你想替换的人物/场景/商品，你没提到的地方 100% 保持原视频不变 → 改到完全满意再点确认生成！
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
          {isLocked ? (
            <button
              type="button"
              disabled={locking}
              onClick={() => handleToggleLock(false)}
              className="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold inline-flex items-center gap-1.5"
            >
              <Unlock className="w-3.5 h-3.5 text-amber-400" />
              继续修改提示词
            </button>
          ) : (
            <button
              type="button"
              disabled={locking}
              onClick={() => handleToggleLock(true)}
              className="px-3.5 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 text-xs font-bold inline-flex items-center gap-1.5 shadow-lg shadow-emerald-500/20"
            >
              {locking ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Lock className="w-3.5 h-3.5" />
              )}
              ✅ 确认没问题，去生成视频
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
                  每次你发修改意见，系统会自动提炼你的人物审美、奢华场景调性与产品替换巧思，以后改写新视频会自动参考（同时严格遵守“未提及处不变”）。
                </p>
              </div>

              {memories.length === 0 ? (
                <div className="text-[11px] text-slate-400 bg-slate-950/60 rounded-lg px-3 py-2.5">
                  暂无记忆。在下方发一次你的修改想法，或者手动添加一条偏好，系统就会自动记住！
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
                  placeholder="手动添加一条长期偏好（如：优先使用欧美贵妇+奢华空间；未提及部分绝不改动）"
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

          {/* Genuine Original Video Filmstrip Previews (from 0.15s Frame 1 to End) */}
          {keyframes.length > 0 && (
            <div className="space-y-1.5">
              <div className="text-[11px] text-slate-400 flex items-center gap-1.5">
                <Film className="w-3.5 h-3.5 text-sky-400" />
                原视频真实画面截帧（已从 0.1 秒第一帧起提取，供你核对原片内容）：
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

          {/* Unified Clean Video Prompt Box */}
          <div className="bg-slate-950/95 border border-slate-800 rounded-xl p-4 space-y-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2 flex-wrap">
                <span
                  className={`px-2.5 py-0.5 rounded-md font-bold text-[11px] ${
                    hasCustomized
                      ? "bg-emerald-500/20 border border-emerald-500/40 text-emerald-300"
                      : "bg-sky-500/20 border border-sky-500/40 text-sky-300"
                  }`}
                >
                  {hasCustomized
                    ? "✨ 按你意见重新编写后的视频提示词"
                    : "📄 原视频 1:1 画面还原提示词（未改动）"}
                </span>
                {hasCustomized && (
                  <span className="text-[11px] text-slate-400">
                    （你没提及的画面、坐姿与情节已严格保持原视频不变）
                  </span>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                <button
                  type="button"
                  onClick={handleLoadPromptToEditor}
                  className="px-2.5 py-1 rounded-lg bg-sky-500/20 hover:bg-sky-500/30 border border-sky-400/50 text-sky-200 font-semibold inline-flex items-center gap-1"
                >
                  <ArrowDownToLine className="w-3 h-3" />
                  一键载入下方修改框
                </button>
                <button
                  type="button"
                  onClick={handleCopyPrompt}
                  className="px-2 py-1 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 inline-flex items-center gap-1"
                >
                  <Copy className="w-3 h-3 text-slate-400" />
                  复制
                </button>
                {hasCustomized && (
                  <button
                    type="button"
                    onClick={() => setShowOriginalRef((v) => !v)}
                    className="px-2 py-1 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 inline-flex items-center gap-1"
                  >
                    <Eye className="w-3 h-3 text-sky-400" />
                    {showOriginalRef ? "收起原片词" : "对照原片词"}
                  </button>
                )}
                {currentPromptEn && (
                  <button
                    type="button"
                    onClick={() => setShowEnglishPrompt((v) => !v)}
                    className="px-2 py-1 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-400 hover:text-slate-200"
                  >
                    {showEnglishPrompt ? "收起英文" : "英文 Prompt"}
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
            </div>

            {manualEditing ? (
              <textarea
                rows={5}
                value={manualTextCn}
                onChange={(e) => setManualTextCn(e.target.value)}
                className="w-full p-3 rounded-xl bg-slate-900 border border-amber-500/40 text-xs sm:text-sm text-slate-100 leading-relaxed focus:outline-none"
              />
            ) : (
              <div className="text-xs sm:text-sm text-slate-100 leading-relaxed whitespace-pre-wrap bg-slate-900/70 rounded-xl p-3.5 border border-slate-800/80">
                {currentPromptCn}
              </div>
            )}

            {showOriginalRef && hasCustomized && (
              <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-3 space-y-1">
                <div className="text-[11px] text-slate-400 font-semibold">原视频初始还原提示词：</div>
                <div className="text-xs text-slate-300 leading-relaxed whitespace-pre-wrap">
                  {fallbackOriginalPrompt}
                </div>
              </div>
            )}

            {showEnglishPrompt && currentPromptEn && (
              <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-3 font-mono text-[11px] text-slate-300 leading-relaxed whitespace-pre-wrap">
                {currentPromptEn}
              </div>
            )}
          </div>

          {/* Multi-turn Revision Conversation History */}
          {history.length > 0 && (
            <div className="bg-slate-950/90 border border-slate-800 rounded-xl p-3 space-y-2 max-h-52 overflow-y-auto">
              <div className="text-[11px] text-slate-400 font-semibold">历次修改记录：</div>
              {history.map((msg, i) => (
                <div
                  key={i}
                  className={`rounded-xl px-3 py-2 text-xs leading-relaxed ${
                    msg.role === "user"
                      ? "bg-sky-500/15 border border-sky-500/30 text-sky-100 ml-6"
                      : "bg-slate-900 border border-slate-800 text-slate-200 mr-6"
                  }`}
                >
                  <div className="flex items-center justify-between text-[10px] opacity-70 mb-0.5">
                    <span>{msg.role === "user" ? "你的修改意见" : "🤖 AI 改写反馈"}</span>
                    <span>{msg.timestamp || ""}</span>
                  </div>
                  <div>{msg.message}</div>
                  {msg.learned_memories && msg.learned_memories.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {msg.learned_memories.map((rule, rIdx) => (
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
              ))}
            </div>
          )}

          {/* Direct User Feedback Input + Two Primary Actions */}
          <div className="space-y-2 pt-1">
            <label className="block text-xs font-semibold text-sky-200">
              👇 点上方「一键载入下方修改框」把原片完整提示词载入后直接改你想要的词语/增补新画面，或直接写下你的修改意见（可多轮修改直到满意）：
            </label>
            {reviseError && (
              <div className="rounded-xl bg-rose-500/15 border border-rose-500/40 px-3 py-2 text-xs text-rose-200">
                改写失败：{reviseError}（请再点一次「按我意见重新编写」重试）
              </div>
            )}
            <div className="flex flex-col sm:flex-row gap-2.5">
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
                placeholder="可以点上方「一键载入下方修改框」直接把原提示词贴进来改字，也可以直接输入你的修改想法..."
                className="flex-1 px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-700 focus:border-sky-400 focus:outline-none text-xs sm:text-sm text-slate-100 placeholder-slate-500 leading-relaxed"
              />
              <div className="flex sm:flex-col gap-2 shrink-0 sm:w-48">
                <button
                  type="button"
                  disabled={revising || !feedback.trim()}
                  onClick={handleSendFeedback}
                  className="flex-1 px-4 py-2.5 rounded-xl bg-sky-500 hover:bg-sky-400 disabled:opacity-50 text-slate-950 font-bold text-xs inline-flex items-center justify-center gap-1.5"
                >
                  {revising ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Send className="w-4 h-4" />
                  )}
                  {revising ? "正在重新编写..." : "按我意见重新编写"}
                </button>
                <button
                  type="button"
                  disabled={locking}
                  onClick={() => handleToggleLock(true)}
                  className="flex-1 px-4 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 disabled:opacity-50 text-slate-950 font-bold text-xs inline-flex items-center justify-center gap-1.5 shadow-lg shadow-emerald-500/20"
                >
                  <Sparkles className="w-4 h-4" />
                  确认没问题，开始生成
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
