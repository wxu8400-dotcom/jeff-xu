import React, { useState } from "react";
import {
  Bot,
  Camera,
  Check,
  Copy,
  ExternalLink,
  Film,
  FileText,
  Image as ImageIcon,
  Layers,
  Sparkles,
  X,
} from "lucide-react";
import type { VideoRecord } from "../types/radar";
import { copyText, formatCompactNumber } from "../utils/copy";

interface Props {
  video: VideoRecord;
  onClose: () => void;
  onToast: (msg: string) => void;
}

type TabKey = "overview" | "storyboard" | "shooting" | "copywriting" | "prompts";

export const VideoDetailModal: React.FC<Props> = ({ video, onClose, onToast }) => {
  const [tab, setTab] = useState<TabKey>("prompts");
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const a = video.analysis_json;

  const handleCopy = async (id: string, text: string, label: string) => {
    const ok = await copyText(text);
    if (ok) {
      setCopiedId(id);
      onToast(`已复制：${label}`);
      setTimeout(() => setCopiedId((curr) => (curr === id ? null : curr)), 1800);
    }
  };

  const copyAllKling = () => {
    const joined = (a?.kling_prompts || [])
      .map(
        (kp) =>
          `【分镜${kp.shot_no} - ${kp.scene_title}】\n模式：${kp.mode}\n推荐参数：${kp.recommended_params}\n中文提示词：\n${kp.prompt_cn}\n英文提示词：\n${kp.prompt_en}\n负向提示词：${kp.negative_prompt}`
      )
      .join("\n\n---\n\n");
    handleCopy("all-kling", joined, "全部可灵 Kling 分镜提示词");
  };

  const tabs: { key: TabKey; label: string; icon: React.ReactNode }[] = [
    { key: "prompts", label: "AI 提示词(可灵/GPT)", icon: <Sparkles className="w-3.5 h-3.5" /> },
    { key: "overview", label: "替换方案 & 结构", icon: <Layers className="w-3.5 h-3.5" /> },
    { key: "storyboard", label: "逐秒分镜表", icon: <Film className="w-3.5 h-3.5" /> },
    { key: "shooting", label: "拍摄要求", icon: <Camera className="w-3.5 h-3.5" /> },
    { key: "copywriting", label: "视频文案", icon: <FileText className="w-3.5 h-3.5" /> },
  ];

  return (
    <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-end sm:items-center justify-center p-0 sm:p-4">
      <div className="bg-slate-900 border border-slate-700 w-full sm:max-w-4xl h-[94vh] sm:h-[90vh] rounded-t-2xl sm:rounded-2xl flex flex-col overflow-hidden shadow-2xl">
        {/* Header */}
        <div className="p-4 border-b border-slate-800 flex items-start justify-between gap-3 shrink-0">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2 mb-1">
              <span className="px-2 py-0.5 rounded bg-sky-500/20 text-sky-300 text-xs font-semibold uppercase">
                {video.platform}
              </span>
              <span className="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 text-xs font-semibold">
                可替换性 {video.replaceability_score} 分
              </span>
              <span className="px-2 py-0.5 rounded bg-purple-500/20 text-purple-200 text-xs inline-flex items-center gap-1">
                {video.is_ai_generated ? <Bot className="w-3 h-3" /> : <Camera className="w-3 h-3" />}
                {video.is_ai_generated ? "AI 原片复刻" : "实拍 + AI双方案"}
              </span>
              <span className="text-xs text-slate-400">
                播放 {formatCompactNumber(video.views)} · 点赞 {formatCompactNumber(video.likes)}
              </span>
            </div>
            <h2 className="text-sm sm:text-base font-bold text-white line-clamp-2">
              {video.title}
            </h2>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <a
              href={video.video_url}
              target="_blank"
              rel="noopener noreferrer"
              className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-sky-300 inline-flex items-center gap-1"
            >
              打开原视频 <ExternalLink className="w-3.5 h-3.5" />
            </a>
            <button
              type="button"
              onClick={onClose}
              className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="px-3 sm:px-4 py-2 border-b border-slate-800 flex items-center gap-1.5 overflow-x-auto shrink-0 bg-slate-950/40">
          {tabs.map((t) => (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={`px-3 py-2 rounded-xl text-xs font-semibold whitespace-nowrap inline-flex items-center gap-1.5 transition ${
                tab === t.key
                  ? "bg-sky-500 text-slate-950"
                  : "text-slate-300 hover:bg-slate-800"
              }`}
            >
              {t.icon}
              {t.label}
            </button>
          ))}
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-5 space-y-5">
          {tab === "prompts" && (
            <>
              {/* Section A: ChatGPT Images */}
              <section className="space-y-3">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-sm sm:text-base font-bold text-emerald-300 flex items-center gap-2">
                    <ImageIcon className="w-4 h-4" />
                    ChatGPT Images 海报 & 分镜首帧提示词（上传产品图后直接复制）
                  </h3>
                </div>
                <div className="space-y-3">
                  {(a?.chatgpt_images_prompts || []).map((p, idx) => (
                    <div
                      key={idx}
                      className="bg-slate-950 border border-slate-800 rounded-2xl p-4 space-y-2.5"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="font-semibold text-sm text-white">
                          {p.scene_title}{" "}
                          <span className="ml-1 px-2 py-0.5 rounded bg-slate-800 text-emerald-300 text-[11px]">
                            {p.aspect_ratio || "9:16"}
                          </span>
                        </div>
                        <div className="flex gap-2">
                          <button
                            type="button"
                            onClick={() =>
                              handleCopy(`gpt-en-${idx}`, p.prompt_en, `${p.scene_title} (英文提示词)`)
                            }
                            className="px-3 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-semibold text-xs inline-flex items-center gap-1"
                          >
                            {copiedId === `gpt-en-${idx}` ? (
                              <Check className="w-3.5 h-3.5" />
                            ) : (
                              <Copy className="w-3.5 h-3.5" />
                            )}
                            复制英文 Prompt
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              handleCopy(`gpt-cn-${idx}`, p.prompt_cn, `${p.scene_title} (中文提示词)`)
                            }
                            className="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs inline-flex items-center gap-1"
                          >
                            <Copy className="w-3 h-3" /> 中文
                          </button>
                        </div>
                      </div>
                      <p className="text-xs text-amber-300/90">💡 {p.usage_note}</p>
                      <pre className="text-xs text-slate-200 bg-slate-900/90 border border-slate-800 rounded-xl p-3 whitespace-pre-wrap font-mono leading-relaxed">
                        {p.prompt_en}
                      </pre>
                      {p.prompt_cn && (
                        <div className="text-xs text-slate-400 leading-relaxed">
                          <span className="text-slate-500">中文对照：</span>
                          {p.prompt_cn}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </section>

              {/* Section B: Kling AI */}
              <section className="space-y-3 pt-2 border-t border-slate-800">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-sm sm:text-base font-bold text-sky-300 flex items-center gap-2">
                    <Sparkles className="w-4 h-4" />
                    可灵 Kling 视频生成提示词（分镜级直接复制）
                  </h3>
                  <button
                    type="button"
                    onClick={copyAllKling}
                    className="px-3 py-1.5 rounded-lg bg-sky-500/20 hover:bg-sky-500/30 border border-sky-400/40 text-sky-200 text-xs font-semibold inline-flex items-center gap-1"
                  >
                    <Copy className="w-3.5 h-3.5" /> 一键复制全部 Kling 分镜
                  </button>
                </div>

                <div className="space-y-3">
                  {(a?.kling_prompts || []).map((kp, idx) => (
                    <div
                      key={idx}
                      className="bg-slate-950 border border-slate-800 rounded-2xl p-4 space-y-2.5"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div>
                          <div className="font-semibold text-sm text-white">
                            分镜 {kp.shot_no} · {kp.scene_title}
                          </div>
                          <div className="text-[11px] text-slate-400 mt-0.5">
                            {kp.mode} · <span className="text-sky-300">{kp.recommended_params}</span>
                          </div>
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          <button
                            type="button"
                            onClick={() =>
                              handleCopy(`kling-cn-${idx}`, kp.prompt_cn, `可灵分镜${kp.shot_no}中文提示词`)
                            }
                            className="px-3 py-1.5 rounded-lg bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold text-xs inline-flex items-center gap-1"
                          >
                            {copiedId === `kling-cn-${idx}` ? (
                              <Check className="w-3.5 h-3.5" />
                            ) : (
                              <Copy className="w-3.5 h-3.5" />
                            )}
                            复制中文(可灵国内版)
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              handleCopy(`kling-en-${idx}`, kp.prompt_en, `可灵分镜${kp.shot_no}英文提示词`)
                            }
                            className="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs inline-flex items-center gap-1"
                          >
                            <Copy className="w-3 h-3" /> 英文版
                          </button>
                        </div>
                      </div>

                      <div className="text-xs text-slate-100 bg-slate-900/90 border border-slate-800 rounded-xl p-3 leading-relaxed">
                        {kp.prompt_cn}
                      </div>

                      {kp.prompt_en && (
                        <div className="text-xs text-slate-400 font-mono bg-slate-900/50 rounded-lg p-2.5">
                          {kp.prompt_en}
                        </div>
                      )}

                      <div className="flex items-center justify-between gap-2 bg-rose-500/5 border border-rose-500/20 rounded-lg px-3 py-2 text-xs">
                        <span className="text-rose-200/90 truncate">
                          负向提示词：{kp.negative_prompt}
                        </span>
                        <button
                          type="button"
                          onClick={() =>
                            handleCopy(`kling-neg-${idx}`, kp.negative_prompt, "负向提示词")
                          }
                          className="text-rose-300 hover:text-rose-200 shrink-0 font-medium"
                        >
                          复制
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            </>
          )}

          {tab === "overview" && (
            <div className="space-y-4">
              <div className="bg-slate-950 border border-slate-800 rounded-2xl p-4 space-y-2">
                <h3 className="text-sm font-bold text-emerald-300">产品可替换性深度评估</h3>
                <div className="text-xs text-slate-300 space-y-1.5">
                  <p>
                    <span className="text-slate-500">原视频核心物品：</span>
                    <b className="text-white">{a?.replaceability?.original_featured_item}</b>
                  </p>
                  <p>
                    <span className="text-slate-500">替换难度 / 推荐流程：</span>
                    {a?.replaceability?.replacement_difficulty} ·{" "}
                    <span className="text-sky-300">{a?.replaceability?.recommended_workflow}</span>
                  </p>
                  <p className="leading-relaxed text-slate-200 bg-slate-900 rounded-xl p-3">
                    {a?.replaceability?.replacement_strategy}
                  </p>
                  <p className="text-slate-400">
                    <span className="text-slate-500">AI 制作判定依据：</span>
                    {a?.ai_detection_reason}（置信度 {video.ai_confidence}%）
                  </p>
                </div>
              </div>

              <div className="bg-slate-950 border border-slate-800 rounded-2xl p-4 space-y-3">
                <h3 className="text-sm font-bold text-sky-300">爆款结构拆解</h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                  <div className="bg-slate-900 rounded-xl p-3">
                    <div className="text-slate-400 mb-1">黄金 3 秒钩子</div>
                    <div className="text-slate-100 leading-relaxed">{a?.structure?.hook_3s}</div>
                  </div>
                  <div className="bg-slate-900 rounded-xl p-3">
                    <div className="text-slate-400 mb-1">结尾转化 CTA</div>
                    <div className="text-slate-100 leading-relaxed">{a?.structure?.conversion_cta}</div>
                  </div>
                </div>
                <div className="bg-slate-900 rounded-xl p-3 text-xs">
                  <div className="text-slate-400 mb-1">全片节奏曲线</div>
                  <div className="text-slate-100 leading-relaxed">{a?.structure?.pacing_curve}</div>
                </div>
                <div className="space-y-1 text-xs">
                  <div className="text-slate-400">爆款核心原因：</div>
                  {(a?.structure?.viral_reasons || []).map((r, i) => (
                    <div key={i} className="text-slate-200">
                      • {r}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {tab === "storyboard" && (
            <div className="space-y-3">
              {(a?.storyboard || []).map((shot) => (
                <div
                  key={shot.shot_no}
                  className="bg-slate-950 border border-slate-800 rounded-2xl p-4 space-y-2.5 text-xs"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="px-2 py-0.5 rounded bg-sky-500/20 text-sky-300 font-bold">
                      镜头 {shot.shot_no}
                    </span>
                    <span className="font-mono text-slate-300">{shot.time_range}</span>
                    <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300">
                      {shot.shot_size}
                    </span>
                    <span className="px-2 py-0.5 rounded bg-slate-800 text-purple-300">
                      运镜：{shot.camera_movement}
                    </span>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                    <div className="bg-slate-900/70 rounded-xl p-3">
                      <div className="text-slate-500 mb-1">原视频画面</div>
                      <div className="text-slate-300 leading-relaxed">{shot.original_visual}</div>
                    </div>
                    <div className="bg-emerald-500/10 border border-emerald-500/25 rounded-xl p-3">
                      <div className="text-emerald-300 font-medium mb-1">
                        替换为你的产品后的画面
                      </div>
                      <div className="text-slate-100 leading-relaxed">
                        {shot.adapted_visual_for_product}
                      </div>
                    </div>
                  </div>
                  <div className="text-slate-400">🔊 音效/BGM：{shot.audio_sfx}</div>
                </div>
              ))}
            </div>
          )}

          {tab === "shooting" && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
              {[
                { label: "灯光与布光要求", val: a?.shooting_requirements?.lighting },
                { label: "机位与拍摄参数", val: a?.shooting_requirements?.camera_setup },
                { label: "场景与道具清单", val: a?.shooting_requirements?.props_and_scene },
                { label: "剪辑节奏与转场", val: a?.shooting_requirements?.editing_rhythm },
                { label: "BGM 风格与卡点", val: a?.shooting_requirements?.bgm_style },
              ].map((item) => (
                <div
                  key={item.label}
                  className="bg-slate-950 border border-slate-800 rounded-2xl p-4 space-y-1.5"
                >
                  <div className="text-sky-300 font-semibold">{item.label}</div>
                  <div className="text-slate-200 leading-relaxed">{item.val || "—"}</div>
                </div>
              ))}
            </div>
          )}

          {tab === "copywriting" && (
            <div className="space-y-3 text-xs">
              {[
                {
                  id: "script-cn",
                  label: "可直接使用的中文改写口播 / 字幕文案（已融入你的产品卖点）",
                  val: a?.copywriting?.adapted_script_cn,
                  highlight: true,
                },
                {
                  id: "script-en",
                  label: "出海可直接使用的英文改写口播 / 字幕文案",
                  val: a?.copywriting?.adapted_script_en,
                  highlight: true,
                },
                {
                  id: "hashtags",
                  label: "推荐发布标题与流量标签",
                  val: a?.copywriting?.caption_and_hashtags,
                },
                {
                  id: "orig",
                  label: "原视频文案转录",
                  val: a?.copywriting?.original_transcript,
                },
                {
                  id: "trans",
                  label: "原视频中文翻译",
                  val: a?.copywriting?.chinese_translation,
                },
              ].map((block) => (
                <div
                  key={block.id}
                  className={`rounded-2xl p-4 space-y-2 border ${
                    block.highlight
                      ? "bg-sky-500/10 border-sky-500/30"
                      : "bg-slate-950 border-slate-800"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold text-slate-200">{block.label}</span>
                    {block.val && (
                      <button
                        type="button"
                        onClick={() => handleCopy(block.id, block.val || "", block.label)}
                        className="px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-sky-300 inline-flex items-center gap-1"
                      >
                        <Copy className="w-3 h-3" /> 复制
                      </button>
                    )}
                  </div>
                  <div className="text-slate-100 whitespace-pre-wrap leading-relaxed">
                    {block.val || "—"}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
