import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clapperboard,
  Download,
  Film,
  Image as ImageIcon,
  Loader2,
  Lock,
  Music,
  RefreshCw,
  Sparkles,
  Trash2,
  Upload,
  Volume2,
  Wand2,
  X,
} from "lucide-react";
import { api } from "../api/client";
import { DirectorCoCreatePanel } from "./DirectorCoCreatePanel";
import type {
  GeneratedAsset,
  StoryboardShot,
  StudioState,
  VideoDeepAnalysis,
  VideoRecord,
} from "../types/radar";

interface Props {
  video: VideoRecord;
  onAnalysisUpdated?: (nextAnalysis: VideoDeepAnalysis) => void;
  onToast: (msg: string) => void;
}

const PLACEHOLDER_HINTS = [
  "Photorealistic vertical 9:16 cinema keyframe...",
  "Keep the exact product from the uploaded reference images...",
  "展示并抛出：人物在主场景展示迷你版产品并抛出",
];

function isWeakPlaceholder(s?: string | null): boolean {
  const t = (s || "").trim();
  if (!t) return true;
  if (PLACEHOLDER_HINTS.some((p) => t.includes(p))) return true;
  if (t.endsWith("...") && t.length < 95) return true;
  return false;
}

export const StudioWorkbench: React.FC<Props> = ({
  video,
  onAnalysisUpdated,
  onToast,
}) => {
  const [studio, setStudio] = useState<StudioState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // 4-Step Guided Wizard State: 1=分析提示词, 2=生成关键图片, 3=生成视频, 4=合成并且下载
  const [activeStep, setActiveStep] = useState<1 | 2 | 3 | 4>(1);
  const [stepInitialized, setStepInitialized] = useState(false);

  // Generation settings
  const [imageProvider, setImageProvider] = useState<"gemini" | "openai">("openai");
  const [openaiModel, setOpenaiModel] = useState<string>("doubao-seedream-4-5-251128");
  const [klingModel, setKlingModel] = useState<string>("kling-v2-5-turbo");
  const [enableKlingSound, setEnableKlingSound] = useState<boolean>(false);
  const [useCharacterRef, setUseCharacterRef] = useState<boolean>(true);

  // Step 4 audio & trim settings
  const [trimToPlannedDuration, setTrimToPlannedDuration] = useState<boolean>(true);
  const [sfxMode, setSfxMode] = useState<
    "auto_match_source" | "source_audio_only" | "kling_v2a" | "none"
  >("auto_match_source");
  const [sfxPrompt, setSfxPrompt] = useState<string>("");
  const [enableVoiceover, setEnableVoiceover] = useState<boolean>(false);
  const [voiceoverVoice, setVoiceoverVoice] = useState<string>("zh-CN-YunxiNeural");
  const [voiceoverText, setVoiceoverText] = useState<string>(
    () => video.analysis_json?.copywriting?.adapted_script_cn || ""
  );
  const [bgmMode, setBgmMode] = useState<"none" | "ambient_chill" | "upbeat_pulse" | "custom">(
    "none"
  );
  const [bgmUploadBusy, setBgmUploadBusy] = useState(false);

  // Per-slot UI state
  const [busySlots, setBusySlots] = useState<Record<string, boolean>>({});
  const [batchImgBusy, setBatchImgBusy] = useState(false);
  const [batchVidBusy, setBatchVidBusy] = useState(false);
  const [stitchBusy, setStitchBusy] = useState(false);
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);
  const [editingSlot, setEditingSlot] = useState<number | null>(null);
  const [editedPrompts, setEditedPrompts] = useState<Record<number, string>>({});
  const [imageFixInputs, setImageFixInputs] = useState<Record<number, string>>({});
  const [allowStaticFallback, setAllowStaticFallback] = useState<boolean>(false);

  const refInputRef = useRef<HTMLInputElement | null>(null);

  const a = video.analysis_json;
  const storyboard = useMemo(() => a?.storyboard || [], [a]);
  const imgPrompts = useMemo(() => a?.chatgpt_images_prompts || [], [a]);
  const klingPrompts = useMemo(() => a?.kling_prompts || [], [a]);
  const isDirectorLocked = a?.director_plan?.revision_status === "locked";

  const loadState = useCallback(
    async (silent = false) => {
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
        if (!silent) {
          setError(err instanceof Error ? err.message : "加载工坊状态失败");
        }
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [video.id, sfxPrompt]
  );

  useEffect(() => {
    setStepInitialized(false);
    loadState(false);
  }, [video.id]);

  // Poll while any asset is processing
  const hasProcessing = useMemo(
    () => (studio?.assets || []).some((item) => item.status === "processing" || item.status === "pending"),
    [studio]
  );

  useEffect(() => {
    if (!hasProcessing) return;
    const timer = window.setInterval(() => {
      loadState(true);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [hasProcessing, loadState]);

  // Latest asset lookup by shot_no
  const { latestImageBySlot, latestVideoByShot, latestUploadByShot, finalVideos, customBgm } =
    useMemo(() => {
      const imgMap: Record<number, GeneratedAsset> = {};
      const vidMap: Record<number, GeneratedAsset> = {};
      const upMap: Record<number, GeneratedAsset> = {};
      const finals: GeneratedAsset[] = [];
      let bgm: GeneratedAsset | null = null;
      for (const item of studio?.assets || []) {
        if (item.asset_type === "image") {
          if (!(item.slot_index in imgMap)) imgMap[item.slot_index] = item;
        } else if (item.asset_type === "video_clip" && item.shot_no) {
          if (!(item.shot_no in vidMap)) vidMap[item.shot_no] = item;
        } else if (item.asset_type === "uploaded_clip" && item.shot_no) {
          if (!(item.shot_no in upMap)) upMap[item.shot_no] = item;
        } else if (item.asset_type === "final_video") {
          finals.push(item);
        } else if (item.asset_type === "bgm_audio" && !bgm) {
          bgm = item;
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

  const completedImageCount = useMemo(
    () =>
      storyboard.filter((s) => latestImageBySlot[s.shot_no]?.status === "completed").length,
    [storyboard, latestImageBySlot]
  );

  const completedVideoCount = useMemo(
    () =>
      storyboard.filter((s) => {
        const v = latestVideoByShot[s.shot_no];
        const u = latestUploadByShot[s.shot_no];
        return v?.status === "completed" || u?.status === "completed";
      }).length,
    [storyboard, latestVideoByShot, latestUploadByShot]
  );

  // Auto-select appropriate initial step once studio loads
  useEffect(() => {
    if (stepInitialized || !studio) return;
    if (finalVideos.length > 0) {
      setActiveStep(4);
    } else if (completedVideoCount > 0) {
      setActiveStep(3);
    } else if (completedImageCount > 0 || isDirectorLocked) {
      setActiveStep(2);
    } else {
      setActiveStep(1);
    }
    setStepInitialized(true);
  }, [studio, stepInitialized, finalVideos.length, completedVideoCount, completedImageCount, isDirectorLocked]);

  // Step gating rules (strict sequential progression)
  const step2Unlocked = isDirectorLocked || completedImageCount > 0 || completedVideoCount > 0;
  const step3Unlocked = completedImageCount > 0 || completedVideoCount > 0;
  const step4Unlocked =
    completedVideoCount > 0 || (allowStaticFallback && completedImageCount > 0) || finalVideos.length > 0;

  const getSlotPrompt = (shot: StoryboardShot, idx: number) => {
    const slotIndex = shot.shot_no;
    const item = imgPrompts[idx + 1] || imgPrompts[slotIndex] || null;
    const rawEn = item?.prompt_en || "";
    const rawCn = item?.prompt_cn || "";
    const bestBase = !isWeakPlaceholder(rawEn)
      ? rawEn
      : !isWeakPlaceholder(rawCn)
      ? rawCn
      : shot.adapted_visual_for_product || shot.original_visual;
    return {
      title: item?.scene_title || `镜头 ${String(shot.shot_no).padStart(2, "0")}（${shot.time_range}）`,
      prompt: editedPrompts[slotIndex] ?? bestBase,
      ratio: item?.aspect_ratio || "9:16",
    };
  };

  const getKlingPrompt = (shot: StoryboardShot, idx: number) => {
    const kp = klingPrompts.find((k) => k.shot_no === shot.shot_no) || klingPrompts[idx];
    const neg =
      kp?.negative_prompt ||
      a?.director_plan?.negative_constraints ||
      "变形, 模糊, 穿模, 多余手指, 闪烁, 水印, 文字";
    return {
      title: kp?.scene_title || `镜头 ${String(shot.shot_no).padStart(2, "0")} 动态视频`,
      prompt: kp?.prompt_cn || kp?.prompt_en || shot.adapted_visual_for_product,
      negative: neg,
    };
  };

  const handleAnalysisUpdated = (nextAnalysis: VideoDeepAnalysis) => {
    setEditedPrompts({});
    onAnalysisUpdated?.(nextAnalysis);
  };

  const handleUploadProductRef = async (file: File) => {
    try {
      await api.uploadProductReference(video.id, file);
      onToast("商品参考图已更新！");
      await loadState(true);
    } catch (err) {
      onToast(err instanceof Error ? err.message : "上传商品参考图失败");
    }
  };

  const handleGenerateOneImage = async (shot: StoryboardShot, idx: number) => {
    const key = `img-${shot.shot_no}`;
    setBusySlots((prev) => ({ ...prev, [key]: true }));
    try {
      const info = getSlotPrompt(shot, idx);
      await api.generateStudioImage(video.id, {
        slot_index: shot.shot_no,
        shot_no: shot.shot_no,
        scene_title: info.title,
        prompt: info.prompt,
        provider: imageProvider,
        model_override: imageProvider === "openai" ? openaiModel : "",
        aspect_ratio: info.ratio,
        use_character_ref: useCharacterRef,
      });
      onToast(`已提交生图：${info.title}`);
      await loadState(true);
    } catch (err) {
      onToast(err instanceof Error ? err.message : "生图失败");
    } finally {
      setBusySlots((prev) => ({ ...prev, [key]: false }));
    }
  };

  const handleRefineImage = async (shot: StoryboardShot, idx: number) => {
    const fb = (imageFixInputs[shot.shot_no] || "").trim();
    if (!fb) {
      onToast("请先输入中文修改意见（如：人物换年轻点、光线调亮、不要菱格改波浪纹...）");
      return;
    }
    const key = `img-${shot.shot_no}`;
    setBusySlots((prev) => ({ ...prev, [key]: true }));
    try {
      const info = getSlotPrompt(shot, idx);
      await api.refineStudioImage(video.id, {
        slot_index: shot.shot_no,
        shot_no: shot.shot_no,
        scene_title: info.title,
        base_prompt: info.prompt,
        feedback: fb,
        provider: imageProvider,
        model_override: imageProvider === "openai" ? openaiModel : "",
        aspect_ratio: info.ratio,
        use_character_ref: useCharacterRef,
      });
      setImageFixInputs((prev) => ({ ...prev, [shot.shot_no]: "" }));
      onToast(`🎨 已按意见重绘：${info.title}`);
      await loadState(true);
    } catch (err) {
      onToast(err instanceof Error ? err.message : "单图重绘失败");
    } finally {
      setBusySlots((prev) => ({ ...prev, [key]: false }));
    }
  };

  const handleInheritPrevLastFrame = async (targetShotNo: number, prevVideoId: string) => {
    const key = `img-${targetShotNo}`;
    setBusySlots((prev) => ({ ...prev, [key]: true }));
    try {
      await api.extractLastFrameForNextShot(video.id, {
        target_shot_no: targetShotNo,
        source_video_asset_id: prevVideoId,
        scene_title: `镜头 ${String(targetShotNo).padStart(2, "0")} 首帧（继承上一镜尾帧）`,
      });
      onToast(`🔗 已提取镜头 ${targetShotNo - 1} 尾帧作为镜头 ${targetShotNo} 首帧！`);
      await loadState(true);
    } catch (err) {
      onToast(err instanceof Error ? err.message : "提取尾帧失败");
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
        include_real_shoot_shots: true,
        include_poster: false,
        use_character_ref: useCharacterRef,
      });
      if (created.length === 0) {
        onToast("全部关键帧图均已生成完毕！");
      } else {
        onToast(`✨ 已启动一键生成 ${created.length} 张关键帧图，完成后自动显示...`);
      }
      await loadState(true);
    } catch (err) {
      onToast(err instanceof Error ? err.message : "一键生图失败");
    } finally {
      setBatchImgBusy(false);
    }
  };

  const handleGenerateOneVideo = async (shot: StoryboardShot, idx: number) => {
    const imgAsset = latestImageBySlot[shot.shot_no];
    if (!imgAsset || imgAsset.status !== "completed") {
      onToast(`请先在步骤 2 生成镜头 ${shot.shot_no} 的关键帧图`);
      return;
    }
    const key = `vid-${shot.shot_no}`;
    setBusySlots((prev) => ({ ...prev, [key]: true }));
    try {
      const kp = getKlingPrompt(shot, idx);
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
      onToast(`🎬 镜头 ${shot.shot_no} 已提交可灵 AI 生成，完成后自动显示`);
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
        include_real_shoot_shots: true,
        model_override: klingModel,
        enable_sound: enableKlingSound,
      });
      onToast(`🎬 已一键提交 ${created.length} 个镜头至可灵 AI 渲染，请稍候...`);
      await loadState(true);
    } catch (err) {
      onToast(err instanceof Error ? err.message : "一键生成视频失败");
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
        `镜头 ${shot.shot_no} 上传视频`
      );
      onToast(`镜头 ${shot.shot_no} 视频片段已上传`);
      await loadState(true);
    } catch (err) {
      onToast(err instanceof Error ? err.message : "上传视频失败");
    } finally {
      setBusySlots((prev) => ({ ...prev, [key]: false }));
    }
  };

  const handleUploadBgm = async (file: File) => {
    setBgmUploadBusy(true);
    try {
      await api.uploadCustomBgm(video.id, file);
      setBgmMode("custom");
      onToast(`已上传 BGM：${file.name}`);
      await loadState(true);
    } catch (err) {
      onToast(err instanceof Error ? err.message : "上传 BGM 失败");
    } finally {
      setBgmUploadBusy(false);
    }
  };

  const handleStitchFinal = async () => {
    setStitchBusy(true);
    try {
      const orderedIds: string[] = [];
      for (const shot of storyboard) {
        const up = latestUploadByShot[shot.shot_no];
        const aiVid = latestVideoByShot[shot.shot_no];
        const img = latestImageBySlot[shot.shot_no];
        if (up?.status === "completed") {
          orderedIds.push(up.id);
        } else if (aiVid?.status === "completed") {
          orderedIds.push(aiVid.id);
        } else if (allowStaticFallback && img?.status === "completed") {
          orderedIds.push(img.id);
        }
      }
      if (orderedIds.length === 0) {
        onToast("请先在步骤 3 生成至少 1 段动态视频（或勾选允许用静态图替代未生视频的镜头）");
        return;
      }

      await api.stitchFinalVideo(video.id, {
        asset_ids: orderedIds,
        include_images_as_motion: allowStaticFallback,
        image_clip_duration: 3.0,
        trim_to_planned_duration: trimToPlannedDuration,
        sfx_mode: sfxMode,
        sfx_prompt: sfxPrompt,
        enable_voiceover: enableVoiceover,
        voiceover_text: voiceoverText,
        voiceover_voice: voiceoverVoice,
        bgm_mode: bgmMode,
        bgm_asset_id: bgmMode === "custom" ? customBgm?.id || "" : "",
        bgm_volume: 0.2,
      });
      onToast("🎉 9:16 成品短视频已合成完毕，可直接播放或点击下载！");
      await loadState(true);
    } catch (err) {
      onToast(err instanceof Error ? err.message : "合成成片失败");
    } finally {
      setStitchBusy(false);
    }
  };

  const handleDeleteAsset = async (assetId: string) => {
    try {
      await api.deleteStudioAsset(assetId);
      onToast("已删除该素材");
      await loadState(true);
    } catch {
      onToast("删除失败");
    }
  };

  if (loading) {
    return (
      <div className="py-12 flex items-center justify-center gap-2 text-sm text-slate-400">
        <Loader2 className="w-4 h-4 animate-spin text-sky-400" />
        正在加载创作工坊...
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

  const stepsMeta = [
    {
      num: 1 as const,
      title: "1. 分析提示词",
      sub: storyboard.length > 0 ? `已拆出 ${storyboard.length} 镜` : "上传双文件拆镜",
      done: isDirectorLocked,
      unlocked: true,
    },
    {
      num: 2 as const,
      title: "2. 生成关键图片",
      sub: `${completedImageCount}/${storyboard.length} 张已就绪`,
      done: storyboard.length > 0 && completedImageCount >= storyboard.length,
      unlocked: step2Unlocked,
    },
    {
      num: 3 as const,
      title: "3. 生成视频",
      sub: `${completedVideoCount}/${storyboard.length} 段动态视频`,
      done: storyboard.length > 0 && completedVideoCount >= storyboard.length,
      unlocked: step3Unlocked,
    },
    {
      num: 4 as const,
      title: "4. 合成并且下载",
      sub: finalVideos.length > 0 ? `已出 ${finalVideos.length} 版成片` : "精剪+音效导出",
      done: finalVideos.length > 0,
      unlocked: step4Unlocked,
    },
  ];

  return (
    <div className="space-y-4">
      {/* Minimalist 4-Step Guided Stepper Bar */}
      <div className="bg-slate-950 border border-slate-800 rounded-2xl p-2.5">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
          {stepsMeta.map((st) => {
            const isCurrent = activeStep === st.num;
            return (
              <button
                key={st.num}
                type="button"
                disabled={!st.unlocked}
                onClick={() => st.unlocked && setActiveStep(st.num)}
                className={`px-3 py-2.5 rounded-xl border text-left transition flex items-center justify-between gap-2 ${
                  isCurrent
                    ? "bg-sky-500/20 border-sky-400 text-white shadow-sm shadow-sky-500/20"
                    : st.done
                    ? "bg-emerald-950/30 border-emerald-500/40 text-emerald-100 hover:bg-emerald-950/50"
                    : st.unlocked
                    ? "bg-slate-900/70 border-slate-800 text-slate-200 hover:border-slate-700"
                    : "bg-slate-950/60 border-slate-800/60 text-slate-500 cursor-not-allowed opacity-60"
                }`}
              >
                <div className="min-w-0">
                  <div className="text-xs font-bold truncate">{st.title}</div>
                  <div className="text-[10px] opacity-80 truncate mt-0.5">{st.sub}</div>
                </div>
                {st.done ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                ) : !st.unlocked ? (
                  <Lock className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                ) : null}
              </button>
            );
          })}
        </div>
        {hasProcessing && (
          <div className="mt-2 px-2 flex items-center gap-1.5 text-[11px] text-sky-300">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            后台正在渲染素材中，页面会自动刷新显示最新结果...
          </div>
        )}
      </div>

      {/* ================= STEP 1: 分析提示词 ================= */}
      {activeStep === 1 && (
        <DirectorCoCreatePanel
          video={video}
          onAnalysisUpdated={handleAnalysisUpdated}
          onConfirmedGenerate={() => setActiveStep(2)}
          onToast={onToast}
        />
      )}

      {/* ================= STEP 2: 生成关键图片 ================= */}
      {activeStep === 2 && (
        <div className="space-y-4">
          {/* Clean Top Action Card */}
          <div className="bg-slate-950 border border-slate-800 rounded-2xl p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2.5 min-w-0">
                {studio.product_reference_previews && studio.product_reference_previews.length > 0 ? (
                  <div className="flex items-center gap-1 shrink-0">
                    {studio.product_reference_previews.slice(0, 4).map((src, i) => (
                      <img
                        key={i}
                        src={src}
                        alt={`商品图 ${i + 1}`}
                        onClick={() => setLightboxUrl(src)}
                        className="w-10 h-10 rounded-lg object-cover border border-sky-500/40 cursor-zoom-in"
                      />
                    ))}
                  </div>
                ) : null}
                <div>
                  <div className="text-sm font-bold text-white">
                    步骤 2：生成关键帧图片（已就绪 {completedImageCount}/{storyboard.length} 张）
                  </div>
                  <p className="text-[11px] text-slate-400">
                    无成品镜头已自动跳过商品图防串镜；出图后可放大核对，哪张不满意直接在图下写中文意见单张重绘。
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2 shrink-0">
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
                  className="px-3 py-1.5 rounded-xl bg-slate-900 hover:bg-slate-800 border border-slate-700 text-slate-200 text-xs inline-flex items-center gap-1"
                >
                  <Upload className="w-3.5 h-3.5 text-sky-400" />
                  补传/更换商品图
                </button>
              </div>
            </div>

            {/* Compact Model & Consistency Row */}
            <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-slate-800/80 text-[11px]">
              <span className="text-slate-400">生图模型：</span>
              {[
                { id: "doubao-seedream-4-5-251128", label: "Seedream 4.5（写实推荐）" },
                { id: "gpt-image-2.6-flare", label: "GPT 2.6 Flare" },
                { id: "gpt-image-2.6-sunburst", label: "GPT 2.6 Sunburst" },
              ].map((m) => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => {
                    setImageProvider("openai");
                    setOpenaiModel(m.id);
                  }}
                  className={`px-2.5 py-1 rounded-lg border transition ${
                    imageProvider === "openai" && openaiModel === m.id
                      ? "bg-emerald-500/20 border-emerald-400 text-emerald-200 font-semibold"
                      : "bg-slate-900 border-slate-800 text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {m.label}
                </button>
              ))}
              <label className="inline-flex items-center gap-1.5 text-slate-300 ml-auto cursor-pointer">
                <input
                  type="checkbox"
                  checked={useCharacterRef}
                  onChange={(e) => setUseCharacterRef(e.target.checked)}
                  className="rounded border-slate-600 bg-slate-950 text-sky-500"
                />
                跨镜锁定同一人物
              </label>
            </div>

            {/* Primary One-Click & Next Step Buttons */}
            <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
              <button
                type="button"
                disabled={batchImgBusy}
                onClick={handleGenerateAllImages}
                className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-400 hover:from-emerald-400 hover:to-teal-300 disabled:opacity-50 text-slate-950 font-bold text-xs inline-flex items-center gap-1.5 shadow-lg shadow-emerald-500/20"
              >
                {batchImgBusy ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Wand2 className="w-4 h-4" />
                )}
                ✨ 一键生成全部 {storyboard.length} 张关键帧图
              </button>

              <button
                type="button"
                disabled={!step3Unlocked}
                onClick={() => setActiveStep(3)}
                className="px-5 py-2.5 rounded-xl bg-sky-500 hover:bg-sky-400 disabled:opacity-40 disabled:cursor-not-allowed text-slate-950 font-bold text-xs inline-flex items-center gap-1.5"
              >
                下一步：进入步骤 3 生成视频（{completedImageCount}/{storyboard.length}）
                <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Clean Per-Shot Keyframe Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5">
            {storyboard.map((shot, idx) => {
              const imgAsset = latestImageBySlot[shot.shot_no];
              const isBusy = busySlots[`img-${shot.shot_no}`] || imgAsset?.status === "processing";
              const info = getSlotPrompt(shot, idx);
              const prevVid =
                shot.shot_no >= 2
                  ? latestVideoByShot[shot.shot_no - 1] || latestUploadByShot[shot.shot_no - 1]
                  : null;

              return (
                <div
                  key={shot.shot_no}
                  className="bg-slate-950 border border-slate-800 rounded-2xl p-3 space-y-2.5 flex flex-col"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-xs font-bold text-white truncate">{info.title}</div>
                      <div className="flex flex-wrap gap-1 mt-1">
                        <span className="px-1.5 py-0.5 rounded bg-slate-900 border border-slate-700 text-[10px] text-slate-300">
                          {shot.time_range}
                        </span>
                        {shot.replication_action === "insert_product" ? (
                          <span className="px-1.5 py-0.5 rounded bg-emerald-500/15 border border-emerald-500/30 text-[10px] text-emerald-300">
                            🔄 挂成品商品图
                          </span>
                        ) : (
                          <span className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-600 text-[10px] text-slate-300">
                            🚫 不传成品图
                          </span>
                        )}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() =>
                        setEditingSlot(editingSlot === shot.shot_no ? null : shot.shot_no)
                      }
                      className="text-[11px] text-slate-400 hover:text-sky-300 shrink-0"
                    >
                      {editingSlot === shot.shot_no ? "收起词" : "查看/改词"}
                    </button>
                  </div>

                  {editingSlot === shot.shot_no && (
                    <textarea
                      rows={4}
                      value={info.prompt}
                      onChange={(e) =>
                        setEditedPrompts((prev) => ({ ...prev, [shot.shot_no]: e.target.value }))
                      }
                      className="w-full p-2 rounded-lg bg-slate-900 border border-slate-700 text-[11px] text-slate-200 leading-relaxed"
                    />
                  )}

                  {/* Image Preview */}
                  <div className="aspect-[9/16] max-h-72 w-full rounded-xl bg-slate-900 border border-slate-800 overflow-hidden flex items-center justify-center relative">
                    {imgAsset?.status === "completed" ? (
                      <img
                        src={imgAsset.file_url}
                        alt={info.title}
                        onClick={() => setLightboxUrl(imgAsset.file_url)}
                        className="w-full h-full object-cover cursor-zoom-in"
                      />
                    ) : isBusy ? (
                      <div className="flex flex-col items-center gap-2 text-xs text-sky-300">
                        <Loader2 className="w-6 h-6 animate-spin" />
                        <span>正在绘制关键帧...</span>
                      </div>
                    ) : imgAsset?.status === "failed" ? (
                      <div className="p-3 text-center text-[11px] text-rose-300">
                        生成失败：{imgAsset.error_message || "请重试"}
                      </div>
                    ) : (
                      <div className="p-3 text-center text-[11px] text-slate-500">
                        <ImageIcon className="w-6 h-6 mx-auto mb-1 opacity-50" />
                        尚未生成关键帧图
                      </div>
                    )}
                  </div>

                  {/* Single-shot Generate / Inherit Last Frame */}
                  <div className="flex flex-wrap gap-1.5">
                    <button
                      type="button"
                      disabled={isBusy}
                      onClick={() => handleGenerateOneImage(shot, idx)}
                      className="flex-1 py-1.5 px-2.5 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/40 disabled:opacity-50 text-emerald-200 font-semibold text-[11px] inline-flex items-center justify-center gap-1"
                    >
                      {imgAsset?.status === "completed" ? (
                        <RefreshCw className="w-3 h-3" />
                      ) : (
                        <Sparkles className="w-3 h-3" />
                      )}
                      {imgAsset?.status === "completed" ? "重绘本镜" : "单镜生图"}
                    </button>
                    {prevVid?.status === "completed" && (
                      <button
                        type="button"
                        disabled={isBusy}
                        onClick={() => handleInheritPrevLastFrame(shot.shot_no, prevVid.id)}
                        className="py-1.5 px-2 rounded-lg bg-sky-500/20 hover:bg-sky-500/30 border border-sky-400/40 text-sky-200 text-[11px] font-semibold"
                        title={`提取镜头 ${shot.shot_no - 1} 视频尾帧作为本镜首帧`}
                      >
                        🔗 继承尾帧
                      </button>
                    )}
                  </div>

                  {/* Per-Image Chinese Visual Fix */}
                  {imgAsset?.status === "completed" && (
                    <div className="flex gap-1.5 pt-1 border-t border-slate-800/80">
                      <input
                        type="text"
                        value={imageFixInputs[shot.shot_no] || ""}
                        onChange={(e) =>
                          setImageFixInputs((prev) => ({
                            ...prev,
                            [shot.shot_no]: e.target.value,
                          }))
                        }
                        placeholder="不满意？写中文修改意见重绘..."
                        className="flex-1 min-w-0 px-2 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500"
                      />
                      <button
                        type="button"
                        disabled={isBusy || !(imageFixInputs[shot.shot_no] || "").trim()}
                        onClick={() => handleRefineImage(shot, idx)}
                        className="px-2.5 py-1.5 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 border border-amber-400/40 disabled:opacity-40 text-amber-200 font-semibold text-[11px] shrink-0"
                      >
                        修图
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ================= STEP 3: 生成视频 ================= */}
      {activeStep === 3 && (
        <div className="space-y-4">
          <div className="bg-slate-950 border border-slate-800 rounded-2xl p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-sm font-bold text-white">
                  步骤 3：逐镜 / 一键生成可灵动态视频（已完成 {completedVideoCount}/{storyboard.length} 段动态视频）
                </div>
                <p className="text-[11px] text-slate-400 mt-0.5">
                  每个镜头只发送当前镜头的独立动作提示词；如需相邻镜头无缝衔接，出完上一镜视频后可回到步骤 2 点「🔗 继承尾帧」。
                </p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-1.5 pt-2 border-t border-slate-800/80 text-[11px]">
              <span className="text-slate-400">可灵模型：</span>
              {[
                { id: "kling-v2-5-turbo", label: "Kling 2.5 Turbo（省钱推荐）" },
                { id: "kling-v2-6", label: "Kling 2.6" },
                { id: "kling-v3", label: "Kling 3.0（旗舰）" },
              ].map((km) => (
                <button
                  key={km.id}
                  type="button"
                  onClick={() => setKlingModel(km.id)}
                  className={`px-2.5 py-1 rounded-lg border transition ${
                    klingModel === km.id
                      ? "bg-sky-500/20 border-sky-400 text-sky-100 font-semibold"
                      : "bg-slate-900 border-slate-800 text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {km.label}
                </button>
              ))}
              {(klingModel === "kling-v3" || klingModel === "kling-v2-6") && (
                <label className="inline-flex items-center gap-1 text-slate-300 ml-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={enableKlingSound}
                    onChange={(e) => setEnableKlingSound(e.target.checked)}
                    className="rounded border-slate-600 bg-slate-950 text-sky-500"
                  />
                  带可灵原生音效
                </label>
              )}
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
              <button
                type="button"
                disabled={batchVidBusy || completedImageCount === 0}
                onClick={handleGenerateAllVideos}
                className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-sky-500 to-cyan-400 hover:from-sky-400 hover:to-cyan-300 disabled:opacity-50 text-slate-950 font-bold text-xs inline-flex items-center gap-1.5 shadow-lg shadow-sky-500/20"
              >
                {batchVidBusy ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Clapperboard className="w-4 h-4" />
                )}
                🎬 一键生成全部待渲染的可灵视频
              </button>

              <button
                type="button"
                disabled={!step4Unlocked}
                onClick={() => setActiveStep(4)}
                className="px-5 py-2.5 rounded-xl bg-purple-500 hover:bg-purple-400 disabled:opacity-40 disabled:cursor-not-allowed text-white font-bold text-xs inline-flex items-center gap-1.5"
              >
                下一步：进入步骤 4 合成并下载（{completedVideoCount}/{storyboard.length}）
                <ArrowRight className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Clean Shot-by-Shot Video Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5">
            {storyboard.map((shot, idx) => {
              const imgAsset = latestImageBySlot[shot.shot_no];
              const vidAsset = latestVideoByShot[shot.shot_no] || latestUploadByShot[shot.shot_no];
              const isBusy =
                busySlots[`vid-${shot.shot_no}`] ||
                busySlots[`up-${shot.shot_no}`] ||
                vidAsset?.status === "processing";
              const kp = getKlingPrompt(shot, idx);

              return (
                <div
                  key={shot.shot_no}
                  className="bg-slate-950 border border-slate-800 rounded-2xl p-3 space-y-2.5 flex flex-col"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-bold text-white truncate">{kp.title}</span>
                    <span className="px-1.5 py-0.5 rounded bg-slate-900 border border-slate-700 text-[10px] text-slate-300 shrink-0">
                      计划 {shot.time_range}
                    </span>
                  </div>

                  {/* Video or First-Frame Preview */}
                  <div className="aspect-[9/16] max-h-72 w-full rounded-xl bg-slate-900 border border-slate-800 overflow-hidden flex items-center justify-center">
                    {vidAsset?.status === "completed" ? (
                      <video
                        src={vidAsset.file_url}
                        controls
                        playsInline
                        className="w-full h-full object-cover bg-black"
                      />
                    ) : isBusy ? (
                      <div className="flex flex-col items-center gap-2 text-xs text-sky-300 p-3 text-center">
                        <Loader2 className="w-6 h-6 animate-spin" />
                        <span>可灵正在渲染动态视频（约 1~2 分钟）...</span>
                      </div>
                    ) : imgAsset?.status === "completed" ? (
                      <div className="relative w-full h-full">
                        <img
                          src={imgAsset.file_url}
                          alt={kp.title}
                          className="w-full h-full object-cover opacity-75"
                        />
                        <span className="absolute bottom-2 left-2 px-2 py-0.5 rounded bg-black/75 text-[10px] text-slate-200">
                          首帧图已就绪 · 待生成动态视频
                        </span>
                      </div>
                    ) : (
                      <div className="p-3 text-center text-[11px] text-slate-500">
                        请先在步骤 2 生成本镜首帧图
                      </div>
                    )}
                  </div>

                  <p className="text-[11px] text-slate-400 line-clamp-2 leading-relaxed">
                    {kp.prompt}
                  </p>

                  <div className="flex items-center gap-1.5">
                    <button
                      type="button"
                      disabled={isBusy || imgAsset?.status !== "completed"}
                      onClick={() => handleGenerateOneVideo(shot, idx)}
                      className="flex-1 py-1.5 px-2.5 rounded-lg bg-sky-500/20 hover:bg-sky-500/30 border border-sky-400/50 disabled:opacity-40 text-sky-200 font-semibold text-[11px] inline-flex items-center justify-center gap-1"
                    >
                      <Clapperboard className="w-3 h-3" />
                      {vidAsset?.status === "completed" ? "重做本镜视频" : "生成本镜视频"}
                    </button>
                    <label className="py-1.5 px-2 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-700 text-slate-300 text-[11px] cursor-pointer shrink-0">
                      传视频
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
                    {vidAsset?.status === "completed" && (
                      <a
                        href={`${vidAsset.file_url}?download=1`}
                        className="p-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-700 text-slate-300"
                        title="下载单镜视频"
                      >
                        <Download className="w-3.5 h-3.5" />
                      </a>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ================= STEP 4: 合成并且下载 ================= */}
      {activeStep === 4 && (
        <div className="space-y-4">
          <div className="bg-slate-950 border border-purple-500/35 rounded-2xl p-4 space-y-3.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-sm font-bold text-white">
                  步骤 4：一键合成 9:16 成品短视频并下载
                </div>
                <p className="text-[11px] text-slate-400 mt-0.5">
                  当前动态视频就绪：<b>{completedVideoCount}/{storyboard.length}</b> 段（关键帧图 {completedImageCount}/{storyboard.length} 张）。
                </p>
              </div>
              {studio.has_source_audio && (
                <span className="px-2.5 py-1 rounded-full bg-emerald-500/20 border border-emerald-400/40 text-emerald-200 text-[11px] font-semibold">
                  ✓ 已存档原片真实音轨
                </span>
              )}
            </div>

            {completedVideoCount < storyboard.length && (
              <div className="rounded-xl bg-amber-500/10 border border-amber-500/35 px-3 py-2 text-[11px] text-amber-200 flex flex-wrap items-center justify-between gap-2">
                <span className="flex items-center gap-1.5">
                  <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
                  还有 {storyboard.length - completedVideoCount} 个镜头尚未生成动态视频，建议先回步骤 3 全部生成完毕再合成。
                </span>
                <label className="inline-flex items-center gap-1.5 cursor-pointer text-amber-100">
                  <input
                    type="checkbox"
                    checked={allowStaticFallback}
                    onChange={(e) => setAllowStaticFallback(e.target.checked)}
                    className="rounded border-amber-400/50 bg-slate-950 text-amber-400"
                  />
                  允许缺失镜暂用关键帧图替代
                </label>
              </div>
            )}

            {/* Clean Trim + Sound Settings */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs bg-slate-900/60 border border-slate-800 rounded-xl p-3">
              <div className="space-y-2">
                <label className="flex items-start gap-2 text-slate-100 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={trimToPlannedDuration}
                    onChange={(e) => setTrimToPlannedDuration(e.target.checked)}
                    className="mt-0.5 rounded border-emerald-500/50 bg-slate-950 text-emerald-500"
                  />
                  <span>
                    <b>✂️ 按分镜计划时长自动精剪</b>（把每段 5 秒素材自动剪成紧凑节奏，避免 35 秒拖沓与音轨错位）
                  </span>
                </label>

                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-emerald-300 font-semibold inline-flex items-center gap-1">
                    <Volume2 className="w-3.5 h-3.5" /> 音效匹配：
                  </span>
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
                    className="flex-1 px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-[11px] text-slate-100"
                  >
                    <option value="auto_match_source">🎬 自动匹配原片风格音效（推荐）</option>
                    <option value="source_audio_only">🎵 仅用原视频真实音轨对齐</option>
                    <option value="kling_v2a">✨ AI 逐帧拟音（Kling V2A）</option>
                    <option value="none">仅保留视频原声，不额外叠音效</option>
                  </select>
                </div>
              </div>

              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-pink-300 font-semibold inline-flex items-center gap-1">
                    <Music className="w-3.5 h-3.5" /> BGM：
                  </span>
                  <select
                    value={bgmMode}
                    onChange={(e) =>
                      setBgmMode(
                        e.target.value as "none" | "ambient_chill" | "upbeat_pulse" | "custom"
                      )
                    }
                    className="flex-1 px-2.5 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-[11px] text-slate-100"
                  >
                    <option value="none">不加额外 BGM（推荐）</option>
                    <option value="upbeat_pulse">内置商业轻节奏（免费）</option>
                    <option value="ambient_chill">内置极简氛围（免费）</option>
                    {customBgm && (
                      <option value="custom">已上传：{customBgm.scene_title.slice(0, 16)}</option>
                    )}
                  </select>
                  <label className="px-2.5 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-[11px] cursor-pointer">
                    {bgmUploadBusy ? "上传中..." : "传 MP3"}
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

                <label className="inline-flex items-center gap-1.5 text-slate-300 cursor-pointer text-[11px]">
                  <input
                    type="checkbox"
                    checked={enableVoiceover}
                    onChange={(e) => setEnableVoiceover(e.target.checked)}
                    className="rounded border-slate-600 bg-slate-950 text-emerald-500"
                  />
                  附加免费 AI 口播配音（纯视觉奇幻广告建议不勾）
                </label>
                {enableVoiceover && (
                  <div className="flex gap-1.5">
                    <select
                      value={voiceoverVoice}
                      onChange={(e) => setVoiceoverVoice(e.target.value)}
                      className="px-2 py-1 rounded-lg bg-slate-950 border border-slate-700 text-[11px] text-slate-100"
                    >
                      <option value="zh-CN-YunxiNeural">中文男声</option>
                      <option value="zh-CN-XiaoxiaoNeural">中文女声</option>
                      <option value="en-US-AndrewNeural">英文男声</option>
                    </select>
                    <input
                      type="text"
                      value={voiceoverText}
                      onChange={(e) => setVoiceoverText(e.target.value)}
                      placeholder="口播文案..."
                      className="flex-1 px-2 py-1 rounded-lg bg-slate-950 border border-slate-700 text-[11px] text-slate-100"
                    />
                  </div>
                )}
              </div>
            </div>

            {/* Big One-Click Stitch CTA */}
            <button
              type="button"
              disabled={stitchBusy || !studio.ffmpeg_available}
              onClick={handleStitchFinal}
              className="w-full py-3 rounded-xl bg-gradient-to-r from-purple-500 via-fuchsia-500 to-pink-500 hover:from-purple-400 hover:to-pink-400 disabled:opacity-50 text-white font-bold text-sm inline-flex items-center justify-center gap-2 shadow-lg shadow-purple-500/25"
            >
              {stitchBusy ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Film className="w-4 h-4" />
              )}
              {stitchBusy
                ? "正在精剪并匹配音效合成 9:16 成片..."
                : "🎉 一键合成 9:16 成品短视频 MP4"}
            </button>
          </div>

          {/* Final Video Output & Download Cards */}
          {finalVideos.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {finalVideos.map((fv) => (
                <div
                  key={fv.id}
                  className="bg-slate-950 border border-emerald-500/40 rounded-2xl p-4 space-y-3"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-sm font-bold text-emerald-300 truncate">
                        {fv.scene_title}
                      </div>
                      <div className="text-[11px] text-slate-400">
                        时长：{fv.duration_sec ? `${fv.duration_sec.toFixed(1)} 秒` : "9:16 竖屏"}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleDeleteAsset(fv.id)}
                      className="p-1.5 rounded-lg bg-slate-900 hover:bg-rose-500/20 text-slate-400 hover:text-rose-300"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>

                  <video
                    src={fv.file_url}
                    controls
                    playsInline
                    className="w-full max-h-[420px] rounded-xl bg-black border border-slate-800"
                  />

                  <a
                    href={`${fv.file_url}?download=1`}
                    className="w-full py-2.5 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-400 hover:from-emerald-400 hover:to-teal-300 text-slate-950 font-bold text-xs inline-flex items-center justify-center gap-1.5"
                  >
                    <Download className="w-4 h-4" />
                    ⬇️ 一键下载成片 MP4
                  </a>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Fullscreen Image Lightbox */}
      {lightboxUrl && (
        <div
          onClick={() => setLightboxUrl(null)}
          className="fixed inset-0 z-50 bg-black/85 backdrop-blur-sm flex items-center justify-center p-4"
        >
          <button
            type="button"
            onClick={() => setLightboxUrl(null)}
            className="absolute top-4 right-4 p-2 rounded-full bg-slate-900/90 text-white hover:bg-slate-800"
          >
            <X className="w-5 h-5" />
          </button>
          <img
            src={lightboxUrl}
            alt="放大预览"
            className="max-h-[90vh] max-w-[92vw] rounded-2xl border border-slate-700 object-contain"
          />
        </div>
      )}
    </div>
  );
};
