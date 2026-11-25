import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Bot,
  Camera,
  CheckCircle2,
  Clapperboard,
  Download,
  Film,
  Image as ImageIcon,
  Loader2,
  Music,
  RefreshCw,
  Sparkles,
  Trash2,
  Upload,
  UserRound,
  Volume2,
  Wand2,
  X,
} from "lucide-react";
import { api } from "../api/client";
import type {
  GeneratedAsset,
  StoryboardShot,
  StudioState,
  VideoDeepAnalysis,
  VideoRecord,
} from "../types/radar";
import { DirectorCoCreatePanel } from "./DirectorCoCreatePanel";

interface Props {
  video: VideoRecord;
  onAnalysisUpdated?: (next: VideoDeepAnalysis) => void;
  onToast: (msg: string) => void;
}

type GlobalMode = "all_ai" | "hybrid_shoot";

function inferDefaultShotMode(shot: StoryboardShot, isAiVideo: boolean): "ai" | "real_shoot" {
  const raw = (shot.production_mode || "").toLowerCase();
  if (raw === "ai" || raw === "real_shoot") return raw;
  if (isAiVideo) return "ai";
  const txt = `${shot.adapted_visual_for_product || ""} ${shot.original_visual || ""}`.toLowerCase();
  if (/(手持|握持|安装|手部|开箱|实测|hand|unbox)/.test(txt)) return "real_shoot";
  return "ai";
}

export const StudioWorkbench: React.FC<Props> = ({ video, onAnalysisUpdated, onToast }) => {
  const [studio, setStudio] = useState<StudioState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Global mode: "all_ai" = 100% AI generated (zero filming/upload needed!), "hybrid_shoot" = AI + real-shoot split
  const [globalMode, setGlobalMode] = useState<GlobalMode>("all_ai");
  const [shotModeOverrides, setShotModeOverrides] = useState<Record<number, "ai" | "real_shoot">>({});
  const [imageProvider, setImageProvider] = useState<"gemini" | "openai">("gemini");
  const [openaiModel, setOpenaiModel] = useState<string>("seedream-4.5");
  const [useCharacterRef, setUseCharacterRef] = useState<boolean>(true);
  const [klingModel, setKlingModel] = useState<string>("kling-v2-5-turbo");
  const [enableKlingSound, setEnableKlingSound] = useState<boolean>(false);

  // Free Audio Mixing State (AI Voiceover + BGM)
  const [enableVoiceover, setEnableVoiceover] = useState<boolean>(true);
  const [voiceoverVoice, setVoiceoverVoice] = useState<string>("zh-CN-YunxiNeural");
  const [voiceoverText, setVoiceoverText] = useState<string>(
    () => video.analysis_json?.copywriting?.adapted_script_cn || ""
  );
  const [showVoiceEditor, setShowVoiceEditor] = useState<boolean>(false);
  const [sfxMode, setSfxMode] = useState<
    "auto_match_source" | "source_audio_only" | "kling_v2a" | "none"
  >("auto_match_source");
  const [sfxPrompt, setSfxPrompt] = useState<string>("");
  const [bgmMode, setBgmMode] = useState<"none" | "ambient_chill" | "upbeat_pulse" | "custom">(
    "none"
  );
  const [bgmUploadBusy, setBgmUploadBusy] = useState<boolean>(false);
  const [checkedRealShots, setCheckedRealShots] = useState<Record<number, boolean>>({});
  const [editedPrompts, setEditedPrompts] = useState<Record<number, string>>({});
  const [editingSlot, setEditingSlot] = useState<number | null>(null);

  const [busySlots, setBusySlots] = useState<Record<string, boolean>>({});
  const [batchImgBusy, setBatchImgBusy] = useState(false);
  const [batchVidBusy, setBatchVidBusy] = useState(false);
  const [stitchBusy, setStitchBusy] = useState(false);
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);
  const [forceShowGenerator, setForceShowGenerator] = useState(false);
  const [showSegmentDetails, setShowSegmentDetails] = useState(true);
  const [imageFixInputs, setImageFixInputs] = useState<Record<number, string>>({});

  const refInputRef = useRef<HTMLInputElement | null>(null);
  const genSectionRef = useRef<HTMLDivElement | null>(null);

  const a = video.analysis_json;
  const storyboard = useMemo(() => a?.storyboard || [], [a]);
  const imgPrompts = useMemo(() => a?.chatgpt_images_prompts || [], [a]);
  const klingPrompts = useMemo(() => a?.kling_prompts || [], [a]);

  const loadState = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const data = await api.getStudioState(video.id);
      setStudio(data);
      if (!silent) {
        if (data.recommended_sfx_prompt && !sfxPrompt) {
          setSfxPrompt(data.recommended_sfx_prompt);
        }
        if (data.default_image_provider === "openai" && data.openai_image_configured) {
          setImageProvider("openai");
        } else if (data.gemini_image_configured) {
          setImageProvider("gemini");
        } else if (data.openai_image_configured) {
          setImageProvider("openai");
        }
      }
      setError("");
    } catch (err) {
      if (!silent) setError(err instanceof Error ? err.message : "加载一键复刻工坊失败");
    } finally {
      if (!silent) setLoading(false);
    }
  }, [video.id]);

  useEffect(() => {
    loadState(false);
  }, [loadState]);

  // Poll automatically while any image or Kling video task is still processing
  const hasProcessing = useMemo(
    () => (studio?.assets || []).some((x) => x.status === "processing" || x.status === "pending"),
    [studio]
  );

  useEffect(() => {
    if (!hasProcessing) return;
    const timer = setInterval(() => {
      loadState(true);
    }, 3000);
    return () => clearInterval(timer);
  }, [hasProcessing, loadState]);

  // Build latest asset lookup maps per slot / shot
  const { latestImageBySlot, latestVideoByShot, latestUploadByShot, finalVideos, customBgm } = useMemo(() => {
    const imgMap: Record<number, GeneratedAsset> = {};
    const vidMap: Record<number, GeneratedAsset> = {};
    const upMap: Record<number, GeneratedAsset> = {};
    const finals: GeneratedAsset[] = [];
    let bgm: GeneratedAsset | null = null;

    for (const item of studio?.assets || []) {
      if (item.asset_type === "image") {
        if (!imgMap[item.slot_index]) imgMap[item.slot_index] = item;
      } else if (item.asset_type === "video_clip" && item.shot_no != null) {
        if (!vidMap[item.shot_no]) vidMap[item.shot_no] = item;
      } else if (item.asset_type === "uploaded_clip" && item.shot_no != null) {
        if (!upMap[item.shot_no]) upMap[item.shot_no] = item;
      } else if (item.asset_type === "final_video" && item.status === "completed") {
        finals.push(item);
      } else if (item.asset_type === "bgm_audio" && item.status === "completed") {
        if (!bgm) bgm = item;
      }
    }
    return {
      latestImageBySlot: imgMap,
      latestVideoByShot: vidMap,
      latestUploadByShot: upMap,
      finalVideos: finals,
      customBgm: bgm,
    };
  }, [studio]);

  const effectiveShotMode = (shot: StoryboardShot): "ai" | "real_shoot" => {
    if (shotModeOverrides[shot.shot_no]) return shotModeOverrides[shot.shot_no];
    if (globalMode === "all_ai") return "ai";
    return inferDefaultShotMode(shot, video.is_ai_generated);
  };

  const getSlotPrompt = (slotIndex: number, shot?: StoryboardShot): { title: string; prompt: string; ratio: string } => {
    if (slotIndex === 0) {
      const p0 = imgPrompts[0];
      return {
        title: p0?.scene_title || "爆款主视觉海报（封面图）",
        prompt:
          editedPrompts[0] ??
          p0?.prompt_en ??
          p0?.prompt_cn ??
          `Keep the exact product from the uploaded reference image 100% unchanged. Hero commercial 9:16 poster for ${studio?.product_name || "the product"}.`,
        ratio: p0?.aspect_ratio || "9:16",
      };
    }
    const idx = storyboard.findIndex((s) => s.shot_no === slotIndex);
    const matched = idx >= 0 && imgPrompts[idx + 1] ? imgPrompts[idx + 1] : undefined;
    const defaultPrompt =
      matched?.prompt_en ||
      matched?.prompt_cn ||
      `Keep the exact product from the uploaded reference image (${studio?.product_name || "the product"}, 100% unchanged). Commercial storyboard frame for Shot ${slotIndex} (${shot?.shot_size || "close-up"}): ${shot?.adapted_visual_for_product || shot?.original_visual || ""}. Cinematic commercial lighting, photorealistic, vertical 9:16, no text, no watermark.`;
    return {
      title: matched?.scene_title || `分镜 ${slotIndex} 首帧商品图`,
      prompt: editedPrompts[slotIndex] ?? defaultPrompt,
      ratio: matched?.aspect_ratio || "9:16",
    };
  };

  const getKlingPromptForShot = (shot: StoryboardShot) => {
    const matched = klingPrompts.find((k) => k.shot_no === shot.shot_no);
    if (matched) {
      return {
        title: matched.scene_title || `分镜 ${shot.shot_no} AI 视频`,
        prompt: matched.prompt_en || matched.prompt_cn,
        negative: matched.negative_prompt || "变形, 模糊, 水印, 杂乱文字",
      };
    }
    return {
      title: `分镜 ${shot.shot_no} AI 视频`,
      prompt: `Keep the exact ${studio?.product_name || "product"} completely solid and undistorted. ${shot.adapted_visual_for_product}. Camera movement: ${shot.camera_movement}. Smooth cinematic commercial footage, 4K realistic lighting.`,
      negative: "变形, 模糊, 产品扭曲, 闪烁, 穿模, 多余手指, 水印, 杂乱文字",
    };
  };

  const handleAnalysisUpdated = useCallback(
    (next: VideoDeepAnalysis) => {
      onAnalysisUpdated?.(next);
      setEditedPrompts({});
      const copy = next.copywriting;
      if (copy) {
        if (voiceoverVoice.startsWith("en-") && copy.adapted_script_en) {
          setVoiceoverText(copy.adapted_script_en);
        } else if (copy.adapted_script_cn) {
          setVoiceoverText(copy.adapted_script_cn);
        }
      }
    },
    [onAnalysisUpdated, voiceoverVoice]
  );

  const handleUploadProductRef = async (file: File) => {
    try {
      await api.uploadProductReference(video.id, file);
      onToast("已更新高清商品参考图，后续一键生图将自动使用该图");
      await loadState(true);
    } catch (err) {
      onToast(err instanceof Error ? err.message : "上传参考图失败");
    }
  };

  const handleGenerateOneImage = async (slotIndex: number, shot?: StoryboardShot) => {
    const key = `img-${slotIndex}`;
    setBusySlots((prev) => ({ ...prev, [key]: true }));
    try {
      const info = getSlotPrompt(slotIndex, shot);
      await api.generateStudioImage(video.id, {
        slot_index: slotIndex,
        shot_no: slotIndex === 0 ? null : slotIndex,
        scene_title: info.title,
        prompt: info.prompt,
        provider: imageProvider,
        model_override: imageProvider === "openai" ? openaiModel : "",
        aspect_ratio: info.ratio,
        use_character_ref: useCharacterRef,
      });
      onToast(`已生成：${info.title}`);
      await loadState(true);
    } catch (err) {
      onToast(err instanceof Error ? err.message : "生图失败");
    } finally {
      setBusySlots((prev) => ({ ...prev, [key]: false }));
    }
  };

  const handleRefineImage = async (slotIndex: number, shot?: StoryboardShot) => {
    const fb = (imageFixInputs[slotIndex] || "").trim();
    if (!fb) {
      onToast("请先输入你对这张图的中文修改意见（如：人物换年轻点、光线调亮、沙发放大...）");
      return;
    }
    const key = `img-${slotIndex}`;
    setBusySlots((prev) => ({ ...prev, [key]: true }));
    try {
      const info = getSlotPrompt(slotIndex, shot);
      await api.refineStudioImage(video.id, {
        slot_index: slotIndex,
        shot_no: slotIndex === 0 ? null : slotIndex,
        scene_title: info.title,
        base_prompt: info.prompt,
        feedback: fb,
        provider: imageProvider,
        model_override: imageProvider === "openai" ? openaiModel : "",
        aspect_ratio: info.ratio,
        use_character_ref: useCharacterRef,
      });
      setImageFixInputs((prev) => ({ ...prev, [slotIndex]: "" }));
      onToast(`🎨 已按你的意见重绘完成：${info.title}`);
      await loadState(true);
    } catch (err) {
      onToast(err instanceof Error ? err.message : "单图修正重绘失败");
    } finally {
      setBusySlots((prev) => ({ ...prev, [key]: false }));
    }
  };

  const handleGenerateAllImages = async () => {
    setBatchImgBusy(true);
    try {
      const created = await api.generateAllStudioImages(video.id, {
        provider: imageProvider,
        model_override: imageProvider === "openai" ? openaiModel : "",
        only_missing: true,
        include_real_shoot_shots: globalMode === "all_ai",
        include_poster: true,
        use_character_ref: useCharacterRef,
      });
      if (created.length === 0) {
        onToast("当前所有需要的分镜商品图均已生成完毕！");
      } else {
        onToast(`已启动批量生成 ${created.length} 张商品分镜图，正在自动出图...`);
      }
      await loadState(true);
    } catch (err) {
      onToast(err instanceof Error ? err.message : "批量生图失败");
    } finally {
      setBatchImgBusy(false);
    }
  };

  const handleGenerateOneVideo = async (shot: StoryboardShot) => {
    const imgAsset = latestImageBySlot[shot.shot_no];
    if (!imgAsset || imgAsset.status !== "completed") {
      onToast(`请先点击「一键生图」生成分镜 ${shot.shot_no} 的首帧商品图`);
      return;
    }
    const key = `vid-${shot.shot_no}`;
    setBusySlots((prev) => ({ ...prev, [key]: true }));
    try {
      const kp = getKlingPromptForShot(shot);
      await api.generateStudioVideoClip(video.id, {
        slot_index: shot.shot_no,
        shot_no: shot.shot_no,
        scene_title: kp.title,
        source_image_asset_id: imgAsset.id,
        prompt: kp.prompt,
        negative_prompt: kp.negative,
        duration_sec: 5,
        model_override: klingModel,
        enable_sound: enableKlingSound,
      });
      onToast(`分镜 ${shot.shot_no} 已提交可灵 AI 生成，完成后自动显示`);
      await loadState(true);
    } catch (err) {
      onToast(err instanceof Error ? err.message : "可灵生视频提交失败");
    } finally {
      setBusySlots((prev) => ({ ...prev, [key]: false }));
    }
  };

  const handleGenerateAllVideos = async () => {
    setBatchVidBusy(true);
    try {
      const created = await api.generateAllStudioVideos(video.id, {
        only_missing: true,
        duration_sec: 5,
        include_real_shoot_shots: globalMode === "all_ai",
        model_override: klingModel,
        enable_sound: enableKlingSound,
      });
      onToast(`已提交 ${created.length} 个分镜至可灵 AI 生成视频，请稍候...`);
      await loadState(true);
    } catch (err) {
      onToast(err instanceof Error ? err.message : "批量生成视频失败");
    } finally {
      setBatchVidBusy(false);
    }
  };

  const handleUploadRealClip = async (shot: StoryboardShot, file: File) => {
    const key = `up-${shot.shot_no}`;
    setBusySlots((prev) => ({ ...prev, [key]: true }));
    try {
      await api.uploadRealShootClip(
        video.id,
        shot.shot_no,
        file,
        `分镜 ${shot.shot_no} 手机实拍`
      );
      setCheckedRealShots((prev) => ({ ...prev, [shot.shot_no]: true }));
      onToast(`分镜 ${shot.shot_no} 实拍片段已上传，可参与一键成片混剪！`);
      await loadState(true);
    } catch (err) {
      onToast(err instanceof Error ? err.message : "上传实拍视频失败");
    } finally {
      setBusySlots((prev) => ({ ...prev, [key]: false }));
    }
  };

  const handleUploadBgm = async (file: File) => {
    setBgmUploadBusy(true);
    try {
      await api.uploadCustomBgm(video.id, file);
      setBgmMode("custom");
      onToast(`已上传自定义 BGM：${file.name}`);
      await loadState(true);
    } catch (err) {
      onToast(err instanceof Error ? err.message : "上传 BGM 失败");
    } finally {
      setBgmUploadBusy(false);
    }
  };

  const handleVoiceChange = (nextVoice: string) => {
    setVoiceoverVoice(nextVoice);
    const copy = video.analysis_json?.copywriting;
    if (!copy) return;
    if (nextVoice.startsWith("en-") && copy.adapted_script_en) {
      setVoiceoverText(copy.adapted_script_en);
    } else if (nextVoice.startsWith("zh-") && copy.adapted_script_cn) {
      setVoiceoverText(copy.adapted_script_cn);
    }
  };

  const handleStitchFinal = async () => {
    setStitchBusy(true);
    try {
      // Build exact ordered asset IDs according to current storyboard & each shot's active mode
      const orderedIds: string[] = [];
      for (const shot of storyboard) {
        const mode = effectiveShotMode(shot);
        const up = latestUploadByShot[shot.shot_no];
        const aiVid = latestVideoByShot[shot.shot_no];
        const img = latestImageBySlot[shot.shot_no];

        if (mode === "real_shoot" && up?.status === "completed") {
          orderedIds.push(up.id);
        } else if (aiVid?.status === "completed") {
          orderedIds.push(aiVid.id);
        } else if (up?.status === "completed") {
          orderedIds.push(up.id);
        } else if (img?.status === "completed") {
          orderedIds.push(img.id);
        }
      }

      if (orderedIds.length === 0) {
        onToast("请先点「一键生成全部分镜商品图」或上传至少 1 段实拍片段，再合成成片！");
        return;
      }

      await api.stitchFinalVideo(video.id, {
        asset_ids: orderedIds,
        include_images_as_motion: true,
        image_clip_duration: 3.5,
        sfx_mode: sfxMode,
        sfx_prompt: sfxPrompt,
        enable_voiceover: enableVoiceover,
        voiceover_text: voiceoverText,
        voiceover_voice: voiceoverVoice,
        bgm_mode: bgmMode,
        bgm_asset_id: bgmMode === "custom" ? customBgm?.id || "" : "",
        bgm_volume: 0.2,
      });
      onToast("🎉 有声 9:16 复刻成片已合成完毕，可直接播放或下载 MP4！");
      await loadState(true);
    } catch (err) {
      onToast(err instanceof Error ? err.message : "成片合成失败");
    } finally {
      setStitchBusy(false);
    }
  };

  const handleDeleteAsset = async (assetId: string) => {
    try {
      await api.deleteStudioAsset(assetId);
      onToast("已移除该素材");
      await loadState(true);
    } catch {
      onToast("删除失败");
    }
  };

  if (loading) {
    return (
      <div className="py-12 flex items-center justify-center gap-2 text-sm text-slate-400">
        <Loader2 className="w-4 h-4 animate-spin text-sky-400" />
        正在加载一键复刻工坊...
      </div>
    );
  }

  if (error || !studio) {
    return (
      <div className="p-4 rounded-2xl bg-rose-500/10 border border-rose-500/30 text-xs text-rose-300">
        {error || "无法加载工坊状态"}
      </div>
    );
  }

  const readyShotCount = storyboard.filter((shot) => {
    const up = latestUploadByShot[shot.shot_no];
    const vid = latestVideoByShot[shot.shot_no];
    const img = latestImageBySlot[shot.shot_no];
    return up?.status === "completed" || vid?.status === "completed" || img?.status === "completed";
  }).length;

  const posterAsset = latestImageBySlot[0];
  const isDirectorLocked = a?.director_plan?.revision_status === "locked";
  const showGeneratorPanel = isDirectorLocked || forceShowGenerator || studio.assets.length > 0;

  return (
    <div className="space-y-5">
      {/* Step 1: Unified Original Prompt -> Multi-Turn User Revision -> Confirm */}
      <DirectorCoCreatePanel
        video={video}
        onAnalysisUpdated={handleAnalysisUpdated}
        onConfirmedGenerate={() => {
          setForceShowGenerator(true);
          setTimeout(() => {
            genSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
          }, 120);
        }}
        onToast={onToast}
      />

      {!showGeneratorPanel ? (
        <div className="bg-slate-950/70 border border-dashed border-slate-800 rounded-2xl p-4 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
          <span>
            👆 请先在上方审阅提示词并写下修改意见，确认完全没问题后点击<b>「确认没问题，开始生成」</b>，下方的一键生成面板就会自动展开（改提示词阶段 0 生图费用）。
          </span>
          <button
            type="button"
            onClick={() => setForceShowGenerator(true)}
            className="text-sky-400 hover:text-sky-300 font-semibold shrink-0"
          >
            跳过确认，直接展开生成面板 →
          </button>
        </div>
      ) : (
        <div ref={genSectionRef} className="space-y-5">
      {/* Top Control Header */}
      <div className="bg-slate-950 border border-slate-800 rounded-2xl p-4 space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            {studio.product_reference_previews && studio.product_reference_previews.length > 0 ? (
              <div className="flex items-center gap-1.5 shrink-0">
                {studio.product_reference_previews.slice(0, 5).map((src, idx) => (
                  <img
                    key={idx}
                    src={src}
                    alt={`商品参考图 ${idx + 1}`}
                    onClick={() => setLightboxUrl(src)}
                    className="w-11 h-11 rounded-xl object-cover border border-sky-500/40 cursor-zoom-in"
                  />
                ))}
              </div>
            ) : studio.product_reference_preview ? (
              <img
                src={studio.product_reference_preview}
                alt="商品参考图"
                className="w-12 h-12 rounded-xl object-cover border border-sky-500/40 shrink-0"
              />
            ) : (
              <div className="w-12 h-12 rounded-xl bg-slate-900 border border-dashed border-slate-700 flex items-center justify-center text-slate-500 shrink-0">
                <ImageIcon className="w-5 h-5" />
              </div>
            )}
            <div className="min-w-0">
              <div className="text-sm font-bold text-white flex items-center gap-2 flex-wrap">
                <span>步骤 2：逐个分镜单独出图确认 → 逐镜生成可灵视频 → 合成成片</span>
                <span className="px-2 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 text-[11px] font-medium">
                  已绑定商品图：{studio.product_name}
                </span>
              </div>
              <p className="text-[11px] text-slate-400 mt-0.5">
                {studio.has_product_reference
                  ? "已自动记住你上传的商品图，直接点下方按钮即可融合出图与合成成片，无需切去其他网站反复上传。"
                  : "当前历史记录未含商品参考图，建议先点右侧补传 1 张清晰商品实拍图，生图还原度会大幅提升。"}
              </p>
            </div>
          </div>

          <div className="shrink-0">
            <input
              ref={refInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleUploadProductRef(f);
                e.target.value = "";
              }}
            />
            <button
              type="button"
              onClick={() => refInputRef.current?.click()}
              className="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs inline-flex items-center gap-1.5"
            >
              <Upload className="w-3.5 h-3.5 text-sky-400" />
              {studio.has_product_reference ? "更换商品参考图" : "补传商品参考图"}
            </button>
          </div>
        </div>

        {/* Mode Switch + Image Provider Switch */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-slate-800/80">
          {/* Global Production Mode */}
          <div className="space-y-1.5">
            <div className="text-[11px] text-slate-400 font-medium">复刻制作模式（可随时切换）：</div>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => {
                  setGlobalMode("all_ai");
                  setShotModeOverrides({});
                }}
                className={`p-2.5 rounded-xl border text-left transition ${
                  globalMode === "all_ai"
                    ? "bg-sky-500/15 border-sky-400 text-sky-100"
                    : "bg-slate-900 border-slate-800 text-slate-400 hover:text-slate-200"
                }`}
              >
                <div className="text-xs font-bold flex items-center gap-1.5">
                  <Bot className="w-3.5 h-3.5 text-sky-400" />
                  全片 100% AI 生成
                </div>
                <div className="text-[11px] opacity-80 mt-0.5">完全免实拍、免上传</div>
              </button>
              <button
                type="button"
                onClick={() => {
                  setGlobalMode("hybrid_shoot");
                  setShotModeOverrides({});
                }}
                className={`p-2.5 rounded-xl border text-left transition ${
                  globalMode === "hybrid_shoot"
                    ? "bg-amber-500/15 border-amber-400 text-amber-100"
                    : "bg-slate-900 border-slate-800 text-slate-400 hover:text-slate-200"
                }`}
              >
                <div className="text-xs font-bold flex items-center gap-1.5">
                  <Camera className="w-3.5 h-3.5 text-amber-400" />
                  AI + 手机实拍混剪
                </div>
                <div className="text-[11px] opacity-80 mt-0.5">特效走 AI，实拍给分镜卡</div>
              </button>
            </div>
          </div>

          {/* Image Engine Switch */}
          <div className="space-y-1.5">
            <div className="text-[11px] text-slate-400 font-medium">生图引擎切换（自动融合你的商品图）：</div>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setImageProvider("gemini")}
                className={`p-2.5 rounded-xl border text-left transition ${
                  imageProvider === "gemini"
                    ? "bg-emerald-500/15 border-emerald-400 text-emerald-100"
                    : "bg-slate-900 border-slate-800 text-slate-400 hover:text-slate-200"
                }`}
              >
                <div className="text-xs font-bold flex items-center justify-between">
                  <span>Gemini 原生生图</span>
                  <span
                    className={`text-[10px] px-1.5 py-0.5 rounded ${
                      studio.gemini_image_configured
                        ? "bg-emerald-500/20 text-emerald-300"
                        : "bg-slate-800 text-slate-500"
                    }`}
                  >
                    {studio.gemini_image_configured ? "已就绪" : "未配 Key"}
                  </span>
                </div>
                <div className="text-[11px] opacity-80 mt-0.5">直接复用现有 Gemini Key</div>
              </button>
              <button
                type="button"
                onClick={() => setImageProvider("openai")}
                className={`p-2.5 rounded-xl border text-left transition ${
                  imageProvider === "openai"
                    ? "bg-purple-500/15 border-purple-400 text-purple-100"
                    : "bg-slate-900 border-slate-800 text-slate-400 hover:text-slate-200"
                }`}
              >
                <div className="text-xs font-bold flex items-center justify-between">
                  <span>302.ai / GPT 生图</span>
                  <span
                    className={`text-[10px] px-1.5 py-0.5 rounded ${
                      studio.openai_image_configured
                        ? "bg-purple-500/20 text-purple-200"
                        : "bg-slate-800 text-slate-500"
                    }`}
                  >
                    {studio.openai_image_configured ? "已就绪" : "需配 Key"}
                  </span>
                </div>
                <div className="text-[11px] opacity-80 mt-0.5">Seedream / Nano Banana / GPT 2.6</div>
              </button>
            </div>
            {imageProvider === "openai" && (
              <div className="flex flex-wrap items-center gap-1.5 pt-1">
                <span className="text-[11px] text-slate-400">生图档位：</span>
                {[
                  { id: "seedream-4.5", label: "Seedream 4.5（省钱 ~¥0.15）" },
                  { id: "gemini-2.5-flash-image", label: "Nano Banana（性价比 ~¥0.28）" },
                  { id: "gpt-image-2.6-flare", label: "GPT 2.6 Flare（6秒极速）" },
                  { id: "gpt-image-2.6-sunburst", label: "GPT 2.6 Sunburst（顶配高精）" },
                ].map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => setOpenaiModel(m.id)}
                    className={`px-2 py-1 rounded-lg text-[11px] border transition ${
                      openaiModel === m.id
                        ? "bg-purple-500/25 border-purple-400 text-purple-100 font-semibold"
                        : "bg-slate-900 border-slate-800 text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
            )}
            <label className="inline-flex items-center gap-1.5 text-[11px] text-slate-300 pt-1 cursor-pointer">
              <input
                type="checkbox"
                checked={useCharacterRef}
                onChange={(e) => setUseCharacterRef(e.target.checked)}
                className="rounded border-slate-600 bg-slate-950 text-sky-500"
              />
              <UserRound className="w-3.5 h-3.5 text-sky-400" />
              跨镜头 AI 人物一致（含人物分镜自动锁脸/引用首张人物图，非产品铺垫镜不强塞商品）
            </label>
          </div>
        </div>

        {/* Audio & Sound Panel (100% Free AI Voiceover + BGM) */}
        <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-3 space-y-2.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-bold text-emerald-300 flex items-center gap-1.5">
              <Volume2 className="w-4 h-4" />
              成片配音 & BGM（0 元免费合成，自动混入第 3 步 MP4）
            </span>
            <button
              type="button"
              onClick={() => setShowVoiceEditor((v) => !v)}
              className="text-[11px] text-sky-400 hover:text-sky-300"
            >
              {showVoiceEditor ? "收起口播台词" : "查看 / 修改配音台词"}
            </button>
          </div>

          {/* Automatic Original-Video-Style SFX Matching Row */}
          <div className="rounded-xl bg-emerald-950/20 border border-emerald-500/30 p-2.5 space-y-2 text-xs">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-bold text-emerald-300">🔊 自动匹配原片风格音效：</span>
                <select
                  value={sfxMode}
                  onChange={(e) =>
                    setSfxMode(
                      e.target.value as
                        | "auto_match_source"
                        | "source_audio_only"
                        | "kling_v2a"
                        | "none"
                    )
                  }
                  className="px-2.5 py-1.5 rounded-lg bg-slate-950 border border-emerald-500/40 text-[11px] text-emerald-100 font-semibold"
                >
                  <option value="auto_match_source">
                    🎬 自动匹配原片同款音效（推荐·合成时自动变速对齐）
                  </option>
                  <option value="source_audio_only">
                    🎵 仅用原视频真实音轨对齐（免费·与原片 100% 同款）
                  </option>
                  <option value="kling_v2a">
                    ✨ AI 逐帧拟音（Kling Video-to-Audio，失败自动回退原片音轨）
                  </option>
                  <option value="none">不额外叠音效（仅保留分镜原声）</option>
                </select>
              </div>
              {studio.has_source_audio ? (
                <span className="px-2 py-0.5 rounded-full bg-emerald-500/20 border border-emerald-400/40 text-emerald-200 text-[10px] font-semibold">
                  ✓ 已存档原视频真实音轨
                </span>
              ) : (
                <span className="text-[10px] text-slate-400">
                  （未检测到原片音轨时将自动采用 AI 拟音/氛围音效兜底）
                </span>
              )}
            </div>
            {sfxMode === "kling_v2a" && (
              <input
                type="text"
                value={sfxPrompt}
                onChange={(e) => setSfxPrompt(e.target.value)}
                placeholder="AI 拟音提示词（如：机舱风声、下坠呼啸、火山喷发轰鸣、沙发落地闷响、自然笑声）"
                className="w-full px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500"
              />
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5 text-xs">
            {/* Free AI Voiceover Controls */}
            <div className="flex flex-wrap items-center gap-2">
              <label className="inline-flex items-center gap-1.5 text-slate-200 cursor-pointer shrink-0">
                <input
                  type="checkbox"
                  checked={enableVoiceover}
                  onChange={(e) => setEnableVoiceover(e.target.checked)}
                  className="rounded border-slate-600 bg-slate-950 text-emerald-500"
                />
                免费 AI 真人配音
              </label>
              {enableVoiceover && (
                <select
                  value={voiceoverVoice}
                  onChange={(e) => handleVoiceChange(e.target.value)}
                  className="flex-1 min-w-[160px] px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-[11px] text-slate-100"
                >
                  <option value="zh-CN-YunxiNeural">中文活力男声（种草推荐）</option>
                  <option value="zh-CN-XiaoxiaoNeural">中文自然女声（亲切推荐）</option>
                  <option value="zh-CN-YunjianNeural">中文磁性男声（商业大片）</option>
                  <option value="en-US-AndrewNeural">英文自然男声（出海推荐）</option>
                  <option value="en-US-AvaNeural">英文爆款女声（TikTok/INS）</option>
                </select>
              )}
            </div>

            {/* BGM Controls */}
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-slate-300 inline-flex items-center gap-1 shrink-0">
                <Music className="w-3.5 h-3.5 text-pink-400" />
                BGM：
              </span>
              <select
                value={bgmMode}
                onChange={(e) =>
                  setBgmMode(e.target.value as "none" | "ambient_chill" | "upbeat_pulse" | "custom")
                }
                className="flex-1 min-w-[140px] px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-[11px] text-slate-100"
              >
                <option value="upbeat_pulse">内置商业轻节奏（免费）</option>
                <option value="ambient_chill">内置高级极简氛围（免费）</option>
                {customBgm && (
                  <option value="custom">已上传：{customBgm.scene_title.slice(0, 18)}</option>
                )}
                <option value="none">不加背景音乐</option>
              </select>
              <label className="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-[11px] inline-flex items-center gap-1 cursor-pointer shrink-0">
                {bgmUploadBusy ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <Upload className="w-3 h-3 text-pink-400" />
                )}
                传 MP3
                <input
                  type="file"
                  accept="audio/*"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) handleUploadBgm(f);
                    e.target.value = "";
                  }}
                />
              </label>
            </div>
          </div>

          {showVoiceEditor && (
            <textarea
              rows={2}
              value={voiceoverText}
              onChange={(e) => setVoiceoverText(e.target.value)}
              placeholder="输入或修改配音口播文案（留空则自动使用本视频改写好的口播脚本）"
              className="w-full p-2 rounded-lg bg-slate-950 border border-slate-700 text-xs text-slate-200"
            />
          )}
        </div>

        {/* One-Click Batch Action Bar */}
        <div className="space-y-2.5 pt-2 border-t border-slate-800/80">
          {!isDirectorLocked && (
            <div className="flex items-start gap-2 rounded-xl bg-amber-500/10 border border-amber-500/30 px-3 py-2 text-[11px] text-amber-200 leading-relaxed">
              <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
              <span>
                <b>提示：</b>上方提示词尚未点击<b>「确认没问题，开始生成」</b>，建议先在上方核对并确认定稿后再生成。
              </span>
            </div>
          )}
          {studio.kling_configured && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] text-slate-400">可灵视频模型：</span>
              {[
                { id: "kling-v2-5-turbo", label: "Kling 2.5 Turbo（省钱推荐 ~¥1.4）" },
                { id: "kling-v2-6", label: "Kling 2.6" },
                { id: "kling-v3", label: "Kling 3.0（顶配旗舰）" },
                { id: "kling-v2-1", label: "Kling 2.1" },
              ].map((km) => (
                <button
                  key={km.id}
                  type="button"
                  onClick={() => setKlingModel(km.id)}
                  className={`px-2 py-1 rounded-lg text-[11px] border transition ${
                    klingModel === km.id
                      ? "bg-sky-500/25 border-sky-400 text-sky-100 font-semibold"
                      : "bg-slate-900 border-slate-800 text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {km.label}
                </button>
              ))}
              {(klingModel === "kling-v3" || klingModel === "kling-v2-6") && (
                <label className="inline-flex items-center gap-1 text-[11px] text-slate-300 ml-1 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={enableKlingSound}
                    onChange={(e) => setEnableKlingSound(e.target.checked)}
                    className="rounded border-slate-600 bg-slate-950 text-sky-500"
                  />
                  带可灵环境音效
                </label>
              )}
            </div>
          )}
          <div className="rounded-xl bg-sky-950/35 border border-sky-500/35 px-3 py-2 text-[11px] text-sky-100 leading-relaxed">
            🎯 <b>逐镜单步生成（推荐）：</b>下方已自动拆分为 <b>{storyboard.length} 个独立分镜卡片</b>。请按顺序<b>逐个分镜单独点击「生成首帧图」→ 满意后再单独点「用该图生成可灵视频」</b>（不满意可直接在图下写中文重绘），全部满意后再点右侧合成 9:16 成片！
          </div>
          <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={stitchBusy || !studio.ffmpeg_available}
            onClick={handleStitchFinal}
            className="px-4 py-2.5 rounded-xl bg-gradient-to-r from-purple-500 to-pink-500 hover:from-purple-400 hover:to-pink-400 disabled:opacity-50 text-white font-bold text-xs inline-flex items-center gap-1.5 shadow-lg shadow-purple-500/20"
          >
            {stitchBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Film className="w-4 h-4" />}
            🎬 合成 9:16 成片 MP4（已就绪 {readyShotCount}/{storyboard.length} 镜）
          </button>

          <button
            type="button"
            disabled={batchImgBusy}
            onClick={handleGenerateAllImages}
            className="px-3 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 border border-slate-700 disabled:opacity-60 text-slate-300 font-medium text-[11px] inline-flex items-center gap-1"
            title="如需一次性补齐剩余未生成的分镜首帧图可使用此备用按钮"
          >
            {batchImgBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wand2 className="w-3.5 h-3.5 text-emerald-400" />}
            备用：批量补齐未生图
          </button>

          <button
            type="button"
            disabled={batchVidBusy}
            onClick={handleGenerateAllVideos}
            className="px-3 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 border border-slate-700 disabled:opacity-60 text-slate-300 font-medium text-[11px] inline-flex items-center gap-1"
            title="如需一次性补齐剩余未生成的可灵视频可使用此备用按钮"
          >
            {batchVidBusy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Clapperboard className="w-3.5 h-3.5 text-sky-400" />}
            备用：批量补齐可灵视频
          </button>

          {hasProcessing && (
            <span className="text-xs text-sky-300 inline-flex items-center gap-1.5 ml-auto">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              后台正在生成中，自动刷新...
            </span>
          )}
          </div>
        </div>

        {!studio.kling_configured && (
          <div className="text-[11px] text-slate-400 bg-slate-900/70 rounded-xl px-3 py-2">
            💡 <b>省钱技巧</b>：即使暂未配置可灵 Kling Key，点完「1. 一键生成画面首帧图」后，直接点「3. 一键合成 9:16 成片 MP4」，系统会自动把所有画面图加上电影级平滑推拉运镜直接出完整 MP4 成片！
          </div>
        )}
      </div>

      {/* Visual Image Confirmation & Per-Image Chinese Refinement Grid */}
      {Object.keys(latestImageBySlot).length > 0 && (
        <div className="bg-slate-950 border border-emerald-500/35 rounded-2xl p-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-bold text-emerald-300 flex items-center gap-1.5">
                <ImageIcon className="w-4 h-4" />
                🖼️ 画面图确认与单图中文修正（满意后再点上方「2. 一键可灵生成动态视频」）
              </h3>
              <p className="text-[11px] text-slate-400 mt-0.5">
                点图片可放大细看；哪张人物长相、光线或商品位置不满意，直接在该图下方写中文意见点「按意见重绘」，只重画这一张！
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {[
              ...(latestImageBySlot[0] ? [{ slot: 0, label: "主视觉封面图", shot: undefined as StoryboardShot | undefined }] : []),
              ...storyboard
                .filter((s) => Boolean(latestImageBySlot[s.shot_no]))
                .map((s) => ({
                  slot: s.shot_no,
                  label: `画面 ${s.shot_no}（${s.time_range}）`,
                  shot: s,
                })),
            ].map(({ slot, label, shot }) => {
              const asset = latestImageBySlot[slot];
              const isBusy = busySlots[`img-${slot}`] || asset?.status === "processing";
              return (
                <div
                  key={slot}
                  className="bg-slate-900/80 border border-slate-800 rounded-xl p-3 flex flex-col gap-2.5"
                >
                  <div className="flex items-center justify-between gap-2 text-xs">
                    <span className="font-bold text-white">{label}</span>
                    {asset?.status === "completed" && (
                      <a
                        href={`${asset.file_url}?download=1`}
                        className="text-[11px] text-sky-400 hover:text-sky-300 inline-flex items-center gap-1"
                      >
                        <Download className="w-3 h-3" /> 下载
                      </a>
                    )}
                  </div>

                  {asset?.status === "completed" ? (
                    <img
                      src={asset.file_url}
                      alt={label}
                      onClick={() => setLightboxUrl(asset.file_url)}
                      className="w-full aspect-[9/16] max-h-72 object-cover rounded-lg border border-slate-700 cursor-zoom-in hover:border-sky-400 transition bg-black"
                    />
                  ) : isBusy ? (
                    <div className="w-full h-56 rounded-lg bg-slate-950 border border-slate-800 flex flex-col items-center justify-center gap-2 text-xs text-sky-300">
                      <Loader2 className="w-5 h-5 animate-spin" />
                      <span>正在生成/重绘画面...</span>
                    </div>
                  ) : (
                    <div className="w-full h-32 rounded-lg bg-rose-500/10 border border-rose-500/30 p-2.5 text-[11px] text-rose-300">
                      生成失败：{asset?.error_message || "未知错误"}
                    </div>
                  )}

                  {/* Direct Chinese Refinement Input for THIS Image */}
                  <div className="space-y-1.5 mt-auto">
                    <input
                      type="text"
                      value={imageFixInputs[slot] || ""}
                      onChange={(e) =>
                        setImageFixInputs((prev) => ({ ...prev, [slot]: e.target.value }))
                      }
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          handleRefineImage(slot, shot);
                        }
                      }}
                      placeholder="不满意？写修改意见（如：人物换28岁欧美金发美女、光线调亮...）"
                      className="w-full px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-700 focus:border-sky-400 focus:outline-none text-[11px] text-slate-100 placeholder-slate-500"
                    />
                    <div className="flex gap-1.5">
                      <button
                        type="button"
                        disabled={isBusy || !(imageFixInputs[slot] || "").trim()}
                        onClick={() => handleRefineImage(slot, shot)}
                        className="flex-1 py-1.5 px-2.5 rounded-lg bg-sky-500 hover:bg-sky-400 disabled:opacity-45 text-slate-950 font-bold text-[11px] inline-flex items-center justify-center gap-1"
                      >
                        {isBusy ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : (
                          <Wand2 className="w-3 h-3" />
                        )}
                        按意见重绘这张图
                      </button>
                      <button
                        type="button"
                        disabled={isBusy}
                        onClick={() => handleGenerateOneImage(slot, shot)}
                        className="py-1.5 px-2.5 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-45 text-slate-200 text-[11px] inline-flex items-center gap-1"
                        title="直接再抽一张"
                      >
                        <RefreshCw className="w-3 h-3" />
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Final Stitched Video Showcase */}
      {finalVideos.length > 0 && (
        <div className="bg-gradient-to-br from-purple-950/50 via-slate-950 to-sky-950/40 border border-purple-500/40 rounded-2xl p-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-5 h-5 text-emerald-400" />
              <div>
                <h3 className="text-sm font-bold text-white">
                  已合成 9:16 竖屏复刻成片：{finalVideos[0].scene_title}
                </h3>
                <p className="text-[11px] text-slate-300">
                  时长约 {finalVideos[0].duration_sec?.toFixed(1) || "-"} 秒 · 包含：{finalVideos[0].prompt_used}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <a
                href={`${finalVideos[0].file_url}?download=1`}
                download
                className="px-3.5 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs inline-flex items-center gap-1.5"
              >
                <Download className="w-3.5 h-3.5" />
                下载完整成片 MP4
              </a>
              <button
                type="button"
                onClick={() => handleDeleteAsset(finalVideos[0].id)}
                className="p-2 rounded-xl bg-slate-800 hover:bg-rose-500/20 text-slate-400 hover:text-rose-300"
                title="删除成片"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
          <div className="flex justify-center bg-black/60 rounded-xl p-2">
            <video
              key={finalVideos[0].id}
              src={finalVideos[0].file_url}
              controls
              playsInline
              preload="metadata"
              className="max-h-96 rounded-lg"
            />
          </div>
        </div>
      )}

      {/* Hero Poster Slot (Slot 0) */}
      {imgPrompts.length > 0 && (
        <div className="bg-slate-950 border border-slate-800 rounded-2xl p-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 text-xs font-bold">
                封面海报
              </span>
              <span className="text-sm font-semibold text-white">
                {getSlotPrompt(0).title}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setEditingSlot(editingSlot === 0 ? null : 0)}
                className="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs"
              >
                {editingSlot === 0 ? "收起提示词" : "微调提示词"}
              </button>
              <button
                type="button"
                disabled={busySlots["img-0"] || posterAsset?.status === "processing"}
                onClick={() => handleGenerateOneImage(0)}
                className="px-3 py-1.5 rounded-lg bg-emerald-500 hover:bg-emerald-400 disabled:opacity-60 text-slate-950 font-bold text-xs inline-flex items-center gap-1"
              >
                {busySlots["img-0"] || posterAsset?.status === "processing" ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : posterAsset?.status === "completed" ? (
                  <RefreshCw className="w-3.5 h-3.5" />
                ) : (
                  <Sparkles className="w-3.5 h-3.5" />
                )}
                {posterAsset?.status === "completed" ? "重新生成海报" : "一键生成海报"}
              </button>
            </div>
          </div>

          {editingSlot === 0 && (
            <textarea
              rows={3}
              value={getSlotPrompt(0).prompt}
              onChange={(e) => setEditedPrompts((prev) => ({ ...prev, 0: e.target.value }))}
              className="w-full p-2.5 rounded-xl bg-slate-900 border border-slate-700 text-xs text-slate-200 font-mono"
            />
          )}

          {posterAsset?.status === "completed" && (
            <div className="flex flex-col sm:flex-row items-start gap-3">
              <img
                src={posterAsset.file_url}
                alt={posterAsset.scene_title}
                onClick={() => setLightboxUrl(posterAsset.file_url)}
                className="w-32 aspect-[9/16] object-cover rounded-xl border border-slate-700 cursor-zoom-in hover:border-sky-400 transition"
              />
              <div className="space-y-2 text-xs">
                <div className="text-emerald-300 font-medium">
                  ✓ 已生成（{posterAsset.provider.toUpperCase()} · {posterAsset.model_name}）
                </div>
                <div className="flex flex-wrap gap-2">
                  <a
                    href={`${posterAsset.file_url}?download=1`}
                    className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-100 inline-flex items-center gap-1"
                  >
                    <Download className="w-3.5 h-3.5 text-sky-400" />
                    下载高清海报
                  </a>
                </div>
              </div>
            </div>
          )}
          {posterAsset?.status === "failed" && (
            <div className="text-xs text-rose-300 bg-rose-500/10 rounded-lg px-3 py-2">
              生成失败：{posterAsset.error_message}
            </div>
          )}
        </div>
      )}

      {/* Optional Collapsible Segment Asset Inspector */}
      <div className="space-y-3">
        <button
          type="button"
          onClick={() => setShowSegmentDetails((v) => !v)}
          className="w-full px-4 py-2.5 rounded-xl bg-slate-950 hover:bg-slate-900 border border-slate-800 flex items-center justify-between text-xs text-slate-300"
        >
          <span>
            🎬 逐镜独立生成面板（共 {storyboard.length} 个独立分镜 · 已就绪 {readyShotCount}/{storyboard.length} · 逐个出图确认再逐个生成视频）
          </span>
          <span className="text-sky-400 font-semibold">
            {showSegmentDetails || studio.assets.length > 0 ? (showSegmentDetails ? "收起明细 ▲" : "展开查看 / 单张重绘 ▼") : "展开明细 ▼"}
          </span>
        </button>

        {(showSegmentDetails || hasProcessing || studio.assets.length > 0) &&
          storyboard.map((shot) => {
          const mode = effectiveShotMode(shot);
          const imgAsset = latestImageBySlot[shot.shot_no];
          const vidAsset = latestVideoByShot[shot.shot_no];
          const upAsset = latestUploadByShot[shot.shot_no];
          const slotInfo = getSlotPrompt(shot.shot_no, shot);
          const isImgBusy = busySlots[`img-${shot.shot_no}`] || imgAsset?.status === "processing";
          const isVidBusy = busySlots[`vid-${shot.shot_no}`] || vidAsset?.status === "processing";
          const isUpBusy = busySlots[`up-${shot.shot_no}`];

          return (
            <div
              key={shot.shot_no}
              className="bg-slate-950 border border-slate-800 rounded-2xl p-4 space-y-3"
            >
              {/* Shot Header */}
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="px-2 py-0.5 rounded bg-sky-500/20 text-sky-300 text-xs font-bold">
                    分镜 {shot.shot_no}
                  </span>
                  <span className="text-xs font-mono text-slate-300">{shot.time_range}</span>
                  <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 text-[11px]">
                    {shot.shot_size} · {shot.camera_movement}
                  </span>
                  {shot.replication_action === "keep_scene" ? (
                    <span className="px-2 py-0.5 rounded bg-slate-800 border border-slate-600 text-slate-200 text-[11px]">
                      🔒 原样复刻（不强塞产品）
                    </span>
                  ) : shot.replication_action === "rewrite_scene" ? (
                    <span className="px-2 py-0.5 rounded bg-amber-500/20 border border-amber-500/40 text-amber-200 text-[11px]">
                      ✏️ 适度改写场景
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 text-[11px]">
                      🔄 植入你的产品
                    </span>
                  )}
                  {shot.has_person && (
                    <span className="px-2 py-0.5 rounded bg-sky-500/15 border border-sky-500/30 text-sky-200 text-[11px]">
                      👤 AI 人物替换
                    </span>
                  )}
                </div>

                {/* Per-Shot Mode Toggle */}
                <div className="flex items-center gap-1 bg-slate-900 p-1 rounded-xl border border-slate-800">
                  <button
                    type="button"
                    onClick={() =>
                      setShotModeOverrides((prev) => ({ ...prev, [shot.shot_no]: "ai" }))
                    }
                    className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold inline-flex items-center gap-1 transition ${
                      mode === "ai"
                        ? "bg-sky-500 text-slate-950"
                        : "text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <Bot className="w-3 h-3" />
                    AI 一键生成
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      setShotModeOverrides((prev) => ({ ...prev, [shot.shot_no]: "real_shoot" }))
                    }
                    className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold inline-flex items-center gap-1 transition ${
                      mode === "real_shoot"
                        ? "bg-amber-400 text-slate-950"
                        : "text-slate-400 hover:text-slate-200"
                    }`}
                  >
                    <Camera className="w-3 h-3" />
                    手机实拍
                  </button>
                </div>
              </div>

              <div className="space-y-1.5">
                <p className="text-xs text-slate-200 leading-relaxed bg-slate-900/70 rounded-xl px-3 py-2">
                  <span className="text-emerald-300 font-semibold">本镜画面：</span>
                  {shot.adapted_visual_for_product}
                </p>
                {shot.director_advice && (
                  <p className="text-[11px] text-purple-200/90 leading-relaxed bg-purple-950/30 border border-purple-500/20 rounded-xl px-3 py-1.5">
                    <span className="text-purple-300 font-semibold">🎬 导演建议：</span>
                    {shot.director_advice}
                  </p>
                )}
              </div>

              {mode === "ai" ? (
                /* AI Mode: 2 Columns (Generated First-Frame Image | Generated Video Clip) */
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {/* Left: Product-Fused First-Frame Image */}
                  <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-3 space-y-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-semibold text-emerald-300 flex items-center gap-1">
                        <ImageIcon className="w-3.5 h-3.5" />
                        {shot.replication_action === "keep_scene"
                          ? "步骤 A：AI 复刻场景首帧图"
                          : "步骤 A：AI 替换商品首帧图"}
                      </span>
                      <div className="flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() =>
                            setEditingSlot(editingSlot === shot.shot_no ? null : shot.shot_no)
                          }
                          className="text-[11px] text-slate-400 hover:text-slate-200"
                        >
                          {editingSlot === shot.shot_no ? "收起" : "改词"}
                        </button>
                        <button
                          type="button"
                          disabled={isImgBusy}
                          onClick={() => handleGenerateOneImage(shot.shot_no, shot)}
                          className="px-2.5 py-1 rounded-lg bg-emerald-500 hover:bg-emerald-400 disabled:opacity-60 text-slate-950 font-bold text-[11px] inline-flex items-center gap-1"
                        >
                          {isImgBusy ? (
                            <Loader2 className="w-3 h-3 animate-spin" />
                          ) : imgAsset?.status === "completed" ? (
                            <RefreshCw className="w-3 h-3" />
                          ) : (
                            <Sparkles className="w-3 h-3" />
                          )}
                          {imgAsset?.status === "completed" ? "重绘" : "一键生图"}
                        </button>
                      </div>
                    </div>

                    {editingSlot === shot.shot_no && (
                      <textarea
                        rows={3}
                        value={slotInfo.prompt}
                        onChange={(e) =>
                          setEditedPrompts((prev) => ({ ...prev, [shot.shot_no]: e.target.value }))
                        }
                        className="w-full p-2 rounded-lg bg-slate-950 border border-slate-700 text-[11px] text-slate-200 font-mono"
                      />
                    )}

                    {imgAsset?.status === "completed" ? (
                      <div className="flex items-start gap-3">
                        <img
                          src={imgAsset.file_url}
                          alt={imgAsset.scene_title}
                          onClick={() => setLightboxUrl(imgAsset.file_url)}
                          className="w-24 aspect-[9/16] object-cover rounded-lg border border-slate-700 cursor-zoom-in shrink-0"
                        />
                        <div className="space-y-1.5 text-[11px] text-slate-300">
                          <div className="text-emerald-300">✓ 商品首帧图已就绪</div>
                          <div className="text-slate-500">
                            {imgAsset.provider.toUpperCase()} · {imgAsset.model_name}
                          </div>
                          <div className="flex flex-wrap gap-1.5 pt-1">
                            <a
                              href={`${imgAsset.file_url}?download=1`}
                              className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 inline-flex items-center gap-1"
                            >
                              <Download className="w-3 h-3" /> 下载图片
                            </a>
                          </div>
                        </div>
                      </div>
                    ) : isImgBusy ? (
                      <div className="h-28 rounded-lg bg-slate-950/70 border border-slate-800 flex items-center justify-center gap-2 text-xs text-sky-300">
                        <Loader2 className="w-4 h-4 animate-spin" />
                        正在融合你的商品生成首帧图...
                      </div>
                    ) : imgAsset?.status === "failed" ? (
                      <div className="text-[11px] text-rose-300 bg-rose-500/10 rounded-lg p-2">
                        生图失败：{imgAsset.error_message}
                      </div>
                    ) : (
                      <div className="h-24 rounded-lg border border-dashed border-slate-800 flex items-center justify-center text-[11px] text-slate-500">
                        点击右上角「一键生图」自动替换为你的商品
                      </div>
                    )}
                  </div>

                  {/* Right: Kling AI Video Clip */}
                  <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-3 space-y-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-semibold text-sky-300 flex items-center gap-1">
                        <Clapperboard className="w-3.5 h-3.5" />
                        步骤 B：可灵 AI 动态镜头（5s）
                      </span>
                      <button
                        type="button"
                        disabled={isVidBusy || imgAsset?.status !== "completed"}
                        onClick={() => handleGenerateOneVideo(shot)}
                        className="px-2.5 py-1 rounded-lg bg-sky-500 hover:bg-sky-400 disabled:opacity-45 text-slate-950 font-bold text-[11px] inline-flex items-center gap-1"
                      >
                        {isVidBusy ? (
                          <Loader2 className="w-3 h-3 animate-spin" />
                        ) : (
                          <Clapperboard className="w-3 h-3" />
                        )}
                        {vidAsset?.status === "completed" ? "重新生成" : "可灵生视频"}
                      </button>
                    </div>

                    {vidAsset?.status === "completed" ? (
                      <div className="space-y-2">
                        <video
                          key={vidAsset.id}
                          src={vidAsset.file_url}
                          controls
                          playsInline
                          className="w-full max-h-44 rounded-lg bg-black"
                        />
                        <div className="flex items-center justify-between text-[11px]">
                          <span className="text-sky-300">
                            ✓ 可灵动态视频已就绪（{vidAsset.duration_sec || 5}s）
                          </span>
                          <a
                            href={`${vidAsset.file_url}?download=1`}
                            className="text-slate-300 hover:text-white inline-flex items-center gap-1"
                          >
                            <Download className="w-3 h-3" /> 下载片段
                          </a>
                        </div>
                      </div>
                    ) : isVidBusy ? (
                      <div className="h-28 rounded-lg bg-slate-950/70 border border-slate-800 flex items-center justify-center gap-2 text-xs text-sky-300">
                        <Loader2 className="w-4 h-4 animate-spin" />
                        可灵 AI 正在渲染动态视频（约 1~2 分钟）...
                      </div>
                    ) : vidAsset?.status === "failed" ? (
                      <div className="text-[11px] text-rose-300 bg-rose-500/10 rounded-lg p-2">
                        视频生成失败：{vidAsset.error_message}
                      </div>
                    ) : (
                      <div className="h-24 rounded-lg border border-dashed border-slate-800 px-3 flex flex-col items-center justify-center text-center text-[11px] text-slate-500 gap-1">
                        <span>
                          {imgAsset?.status === "completed"
                            ? studio.kling_configured
                              ? "首帧图已好，点「可灵生视频」生成 5s 动态画面"
                              : "首帧图已好！可直接点顶部「合成成片」自动转为推镜动态镜头"
                            : "先完成左侧步骤 A 生成首帧图"}
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              ) : (
                /* Real-Shoot Mode: Simple Smartphone Filming Card + Upload Clip + Escape Hatch to AI */
                <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-3.5 space-y-3 text-xs">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-bold text-amber-300 flex items-center gap-1.5">
                      <Camera className="w-4 h-4" />
                      手机实拍执行卡 · 分镜 {shot.shot_no}（{shot.time_range}）
                    </span>
                    <div className="flex items-center gap-2">
                      <label className="inline-flex items-center gap-1.5 text-amber-200 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={Boolean(checkedRealShots[shot.shot_no])}
                          onChange={(e) =>
                            setCheckedRealShots((prev) => ({
                              ...prev,
                              [shot.shot_no]: e.target.checked,
                            }))
                          }
                          className="rounded border-amber-400 bg-slate-950"
                        />
                        已拍完
                      </label>
                      <button
                        type="button"
                        onClick={() =>
                          setShotModeOverrides((prev) => ({ ...prev, [shot.shot_no]: "ai" }))
                        }
                        className="px-2.5 py-1 rounded-lg bg-sky-500/20 hover:bg-sky-500/30 border border-sky-400/40 text-sky-200 text-[11px] font-semibold"
                      >
                        懒得拍？改由 AI 一键生成
                      </button>
                    </div>
                  </div>

                  <div className="space-y-1.5 text-slate-100 leading-relaxed">
                    <div>
                      <span className="text-amber-300 font-semibold">怎么拍：</span>
                      {shot.real_shoot_guide ||
                        `手机竖屏 9:16，${shot.shot_size}，${shot.camera_movement}，按画面描述拍 ${shot.time_range} 即可。`}
                    </div>
                    {shot.spoken_line && (
                      <div className="bg-slate-950/70 rounded-lg px-2.5 py-1.5">
                        <span className="text-sky-300 font-semibold">本镜口播/字幕：</span>
                        「{shot.spoken_line}」
                      </div>
                    )}
                  </div>

                  <div className="flex flex-wrap items-center gap-3 pt-1">
                    <label className="px-3 py-1.5 rounded-lg bg-amber-400 hover:bg-amber-300 text-slate-950 font-bold text-xs inline-flex items-center gap-1.5 cursor-pointer">
                      {isUpBusy ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <Upload className="w-3.5 h-3.5" />
                      )}
                      {upAsset ? "重新上传手机实拍片段" : "上传手机实拍片段（参与自动混剪）"}
                      <input
                        type="file"
                        accept="video/*"
                        className="hidden"
                        onChange={(e) => {
                          const f = e.target.files?.[0];
                          if (f) handleUploadRealClip(shot, f);
                          e.target.value = "";
                        }}
                      />
                    </label>
                    {upAsset && (
                      <span className="text-emerald-300 text-[11px]">
                        ✓ 已上传实拍片段（{upAsset.model_name}）
                      </span>
                    )}
                  </div>

                  {upAsset && (
                    <video
                      key={upAsset.id}
                      src={upAsset.file_url}
                      controls
                      playsInline
                      className="max-h-44 rounded-lg bg-black"
                    />
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
      </div>
      )}

      {/* Lightbox Preview */}
      {lightboxUrl && (
        <div
          onClick={() => setLightboxUrl(null)}
          className="fixed inset-0 z-[70] bg-black/85 flex items-center justify-center p-4"
        >
          <button
            type="button"
            onClick={() => setLightboxUrl(null)}
            className="absolute top-4 right-4 p-2 rounded-full bg-slate-800 text-white"
          >
            <X className="w-5 h-5" />
          </button>
          <img
            src={lightboxUrl}
            alt="预览大图"
            className="max-h-[90vh] max-w-[90vw] rounded-2xl shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
    </div>
  );
};
