import React, { useCallback, useEffect, useState } from "react";
import {
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Lock,
  MessageSquare,
  Plus,
  Send,
  Sparkles,
  Trash2,
  Unlock,
  UserRound,
  Loader2,
} from "lucide-react";
import { api } from "../api/client";
import type { DirectorMemoryItem, VideoDeepAnalysis, VideoRecord } from "../types/radar";

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

interface Props {
  video: VideoRecord;
  onAnalysisUpdated: (nextAnalysis: VideoDeepAnalysis) => void;
  onToast: (msg: string) => void;
}

const ACTION_BADGE: Record<string, { label: string; cls: string }> = {
  keep_scene: {
    label: "🔒 1:1 原样复刻场景/情节",
    cls: "bg-slate-800 text-slate-200 border-slate-600",
  },
  insert_product: {
    label: "🔄 植入你的产品",
    cls: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
  },
  rewrite_scene: {
    label: "✏️ 适度改写场景",
    cls: "bg-amber-500/20 text-amber-300 border-amber-500/40",
  },
};

export const DirectorCoCreatePanel: React.FC<Props> = ({
  video,
  onAnalysisUpdated,
  onToast,
}) => {
  const analysis = video.analysis_json;
  const plan = analysis?.director_plan;
  const isLocked = plan?.revision_status === "locked";

  const [expanded, setExpanded] = useState(!isLocked);
  const [feedback, setFeedback] = useState("");
  const [revising, setRevising] = useState(false);
  const [locking, setLocking] = useState(false);
  const [recentChangedShots, setRecentChangedShots] = useState<number[]>([]);

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

  const storyboard = analysis?.storyboard || [];
  const history = plan?.revision_history || [];
  const questions = plan?.open_questions_for_user || [];
  const activeMemoryCount = memories.filter((m) => m.is_active).length;

  const handleAddMemory = async () => {
    const clean = newRuleText.trim();
    if (clean.length < 4) {
      onToast("请输入至少 4 个字的导演偏好规则");
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
      onToast("🧠 已写入导演长期记忆库，以后拆解所有新视频都会自动运用！");
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
      onToast("请先输入你想调整的分镜、人物或产品出场意见");
      return;
    }
    setRevising(true);
    try {
      const resp = await api.reviseDirectorPlan(video.id, clean);
      setRecentChangedShots(resp.changed_shots || []);
      setFeedback("");
      onAnalysisUpdated(resp.analysis_json);
      await loadMemories();
      const memCount = resp.learned_memories?.length || 0;
      const memHint = memCount > 0 ? `，并新沉淀 ${memCount} 条长期记忆 🧠` : "";
      onToast(
        resp.changed_shots?.length
          ? `AI 导演已更新分镜 ${resp.changed_shots.join("、")} 及全部提示词${memHint}！`
          : `AI 导演已更新分镜与提示词${memHint}！`
      );
    } catch (err) {
      onToast(err instanceof Error ? err.message : "AI 导演修改失败");
    } finally {
      setRevising(false);
    }
  };

  const handleToggleLock = async (nextLocked: boolean) => {
    setLocking(true);
    try {
      const resp = await api.lockDirectorPlan(video.id, nextLocked);
      onAnalysisUpdated(resp.analysis_json);
      setExpanded(!nextLocked);
      onToast(
        nextLocked
          ? "✅ 分镜方案已定稿锁定！现在可以放心按 1 → 2 → 3 生成图片和视频啦"
          : "已解锁分镜方案，你可以继续和 AI 导演对话修改"
      );
    } catch (err) {
      onToast(err instanceof Error ? err.message : "操作失败");
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
              <span>步骤 0：AI 导演 1:1 复刻分镜共创 & 定稿</span>
              <span
                className={`px-2 py-0.5 rounded-full text-[11px] font-semibold border ${
                  isLocked
                    ? "bg-emerald-500/20 border-emerald-400/50 text-emerald-200"
                    : "bg-amber-500/20 border-amber-400/50 text-amber-200"
                }`}
              >
                {isLocked ? "✓ 已确认定稿（可安心出片）" : "待你确认 · 0 生图费无限改稿"}
              </span>
            </div>
            <p className="text-[11px] text-slate-400 mt-0.5">
              {isLocked
                ? "下方 1→2→3 生图/可灵视频/配音将严格按照你的定稿分镜与 AI 人物执行。"
                : "先审阅 1:1 剧情复刻方案、替换的 AI 新人物和产品出场位置；不满意直接发意见让 AI 改到满意再花钱出图！"}
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
            title="查看或管理 AI 导演从你历史对话中积累的专属偏好记忆"
          >
            <Brain className="w-3.5 h-3.5 text-purple-400" />
            导演记忆库（{activeMemoryCount} 条）
          </button>
          {isLocked ? (
            <button
              type="button"
              disabled={locking}
              onClick={() => handleToggleLock(false)}
              className="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold inline-flex items-center gap-1.5"
            >
              <Unlock className="w-3.5 h-3.5 text-amber-400" />
              解锁继续修改分镜
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
              ✅ 确认定稿，开始按步骤生成
            </button>
          )}
        </div>
      </div>

      {expanded && (
        <div className="p-4 space-y-4 text-xs">
          {/* Expandable Long-Term Director Memory Vault */}
          {showMemories && (
            <div className="bg-purple-950/25 border border-purple-500/40 rounded-xl p-3.5 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="text-purple-200 font-bold flex items-center gap-1.5">
                    <Brain className="w-4 h-4 text-purple-400" />
                    AI 导演长期记忆库（跨视频自动生效 · 越聊越懂你）
                  </div>
                  <p className="text-[11px] text-slate-400 mt-0.5">
                    每次你发修改意见，AI 会自动提炼你的人物审美、场景调性、产品替换巧思与改写纪律，下次拆解新视频首版就会直接运用！
                  </p>
                </div>
              </div>

              {memories.length === 0 ? (
                <div className="text-[11px] text-slate-400 bg-slate-950/60 rounded-lg px-3 py-2.5">
                  还没有沉淀记忆。只要在下方和 AI 导演聊 1 次你的想法（或者直接在下面手动写一条铁律），系统就会永久记住并在以后每个视频自动运用！
                </div>
              ) : (
                <div className="space-y-1.5 max-h-52 overflow-y-auto pr-1">
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
                            {m.product_scope && m.product_scope !== "global" && (
                              <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 text-[10px]">
                                适用：{m.product_scope}
                              </span>
                            )}
                            {m.confidence_hits > 1 && (
                              <span className="text-[10px] text-emerald-300 font-semibold">
                                强化 ×{m.confidence_hits}
                              </span>
                            )}
                          </div>
                          <div className="text-slate-100 leading-relaxed">{m.rule_summary}</div>
                          {m.example_snippet && (
                            <div className="text-[10px] text-slate-400 truncate">
                              案例：{m.example_snippet}
                            </div>
                          )}
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
                            title="删除该记忆"
                          >
                            <Trash2 className="w-3 h-3" />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Manual quick-add memory row */}
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
                  placeholder="手动教导演一条长期偏好（如：优先使用欧美贵妇+奢华高端空间；未提及部分绝不改动）"
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

          {/* Top 3 Director Summary Cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="bg-slate-950/90 border border-slate-800 rounded-xl p-3 space-y-1">
              <div className="text-sky-300 font-semibold">🎬 原爆款 1:1 情节还原</div>
              <p className="text-slate-200 leading-relaxed">
                {plan?.original_plot_summary ||
                  analysis?.structure?.pacing_curve ||
                  "保留原爆款视频的分镜顺序、场景氛围与转场节奏。"}
              </p>
            </div>

            <div className="bg-slate-950/90 border border-purple-500/30 rounded-xl p-3 space-y-1">
              <div className="text-purple-300 font-semibold flex items-center gap-1">
                <UserRound className="w-3.5 h-3.5" />
                替换用 AI 原创人物（全片统一）
              </div>
              <p className="text-slate-200 leading-relaxed">
                {plan?.ai_character_profile_cn ||
                  "若原片有人物，可在下方直接指定你想要替换的新 AI 人物形象（如年龄/性别/穿搭），绝不照搬原片真人。"}
              </p>
            </div>

            <div className="bg-slate-950/90 border border-emerald-500/30 rounded-xl p-3 space-y-1">
              <div className="text-emerald-300 font-semibold">🔄 导演产品植入与改写建议</div>
              <p className="text-slate-200 leading-relaxed">
                {plan?.product_placement_plan ||
                  analysis?.replaceability?.replacement_strategy ||
                  "已规划各分镜的保留/替换方案，详见下方逐镜对照表。"}
              </p>
            </div>
          </div>

          {/* Shot-by-Shot 1:1 Comparison & Director Advice */}
          <div className="space-y-2">
            <div className="font-semibold text-slate-300">
              逐镜 1:1 复刻与替换规划（确认好再点「确认定稿」）：
            </div>
            <div className="space-y-2">
              {storyboard.map((shot) => {
                const badge =
                  ACTION_BADGE[shot.replication_action || "insert_product"] ||
                  ACTION_BADGE.insert_product;
                const justChanged = recentChangedShots.includes(shot.shot_no);
                return (
                  <div
                    key={shot.shot_no}
                    className={`rounded-xl p-3 border space-y-1.5 ${
                      justChanged
                        ? "bg-sky-500/10 border-sky-400/60"
                        : "bg-slate-950/80 border-slate-800"
                    }`}
                  >
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="px-2 py-0.5 rounded bg-sky-500/20 text-sky-300 font-bold">
                        分镜 {shot.shot_no}
                      </span>
                      <span className="font-mono text-slate-400">{shot.time_range}</span>
                      <span className={`px-2 py-0.5 rounded border text-[11px] font-medium ${badge.cls}`}>
                        {badge.label}
                      </span>
                      {shot.has_person && (
                        <span className="px-2 py-0.5 rounded bg-purple-500/20 border border-purple-500/30 text-purple-200 text-[11px]">
                          👤 含统一 AI 人物
                        </span>
                      )}
                      {justChanged && (
                        <span className="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 text-[11px] font-bold">
                          ✨ 刚已按你意见更新
                        </span>
                      )}
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2 pt-0.5">
                      <div className="bg-slate-900/70 rounded-lg p-2 text-slate-400">
                        <span className="text-slate-500 font-medium">原片画面：</span>
                        {shot.original_visual}
                      </div>
                      <div className="bg-slate-900 rounded-lg p-2 text-slate-100">
                        <span className="text-emerald-300 font-medium">复刻后本镜画面：</span>
                        {shot.adapted_visual_for_product}
                      </div>
                    </div>

                    {shot.director_advice && (
                      <div className="text-[11px] text-amber-200/90">
                        💡 <b>导演建议：</b>
                        {shot.director_advice}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* Director Questions + Quick Reply Chips */}
          {questions.length > 0 && (
            <div className="bg-slate-950/80 border border-slate-800 rounded-xl p-3 space-y-1.5">
              <div className="text-sky-300 font-semibold">🙋 AI 导演想和你确认：</div>
              {questions.map((q, idx) => (
                <div key={idx} className="text-slate-300">
                  {idx + 1}. {q}
                </div>
              ))}
            </div>
          )}

          {/* Co-creation Chat History */}
          {history.length > 0 && (
            <div className="bg-slate-950/90 border border-slate-800 rounded-xl p-3 space-y-2 max-h-56 overflow-y-auto">
              <div className="text-[11px] text-slate-400 font-semibold">共创修改记录：</div>
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
                    <span>{msg.role === "user" ? "你的修改意见" : "🎬 AI 导演回复"}</span>
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

          {/* Interactive Feedback Input */}
          <div className="space-y-2 pt-1">
            <div className="flex flex-wrap gap-1.5">
              <span className="text-[11px] text-slate-400 self-center">常用指令示例：</span>
              {[
                "把人物换成25岁亚洲时尚女生，穿黑色极简西装",
                "把我的产品提前到第2镜就正式特写亮相",
                "第1镜完全1:1保留原片场景和悬念，先不要露出我的产品",
                "口播文案改得更简短有力、更有悬念感",
              ].map((sample) => (
                <button
                  key={sample}
                  type="button"
                  onClick={() =>
                    setFeedback((prev) => (prev.trim() ? `${prev}；${sample}` : sample))
                  }
                  className="px-2 py-1 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-800 text-[11px] text-slate-300 transition"
                >
                  + {sample}
                </button>
              ))}
            </div>

            <div className="flex flex-col sm:flex-row gap-2">
              <textarea
                rows={2}
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                    e.preventDefault();
                    handleSendFeedback();
                  }
                }}
                placeholder="直接告诉 AI 导演你想怎么改（例如：人物换成年轻帅气男生、产品放第2和第4镜、第3镜保持原片客厅场景别改...）"
                className="flex-1 px-3 py-2 rounded-xl bg-slate-950 border border-slate-700 focus:border-sky-400 focus:outline-none text-xs text-slate-100 placeholder-slate-500"
              />
              <div className="flex sm:flex-col gap-2 shrink-0">
                <button
                  type="button"
                  disabled={revising || !feedback.trim()}
                  onClick={handleSendFeedback}
                  className="flex-1 px-4 py-2 rounded-xl bg-sky-500 hover:bg-sky-400 disabled:opacity-50 text-slate-950 font-bold text-xs inline-flex items-center justify-center gap-1.5"
                >
                  {revising ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Send className="w-3.5 h-3.5" />
                  )}
                  {revising ? "AI 改稿中..." : "让 AI 导演修改"}
                </button>
                <button
                  type="button"
                  disabled={locking}
                  onClick={() => handleToggleLock(true)}
                  className="flex-1 px-4 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 disabled:opacity-50 text-slate-950 font-bold text-xs inline-flex items-center justify-center gap-1.5"
                >
                  <Sparkles className="w-3.5 h-3.5" />
                  满意，确认定稿
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
