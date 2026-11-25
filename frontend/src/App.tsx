import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  Download,
  LogOut,
  Menu,
  Radar,
  Sparkles,
} from "lucide-react";
import { api } from "./api/client";
import { ConfigStatusBadge } from "./components/ConfigStatusBadge";
import { HistorySidebar } from "./components/HistorySidebar";
import { LoginGate } from "./components/LoginGate";
import { ProductUploader } from "./components/ProductUploader";
import { RadarControls, type RadarFormParams } from "./components/RadarControls";
import { ScanProgressBar } from "./components/ScanProgressBar";
import { VideoCard } from "./components/VideoCard";
import { VideoDetailModal } from "./components/VideoDetailModal";
import type {
  AuthStatus,
  ConfigCheck,
  ScanSessionDetail,
  ScanSessionSummary,
  VideoRecord,
} from "./types/radar";

const DEFAULT_PARAMS: RadarFormParams = {
  mode: "direct_urls",
  searchStrategy: "cross_category",
  creativeStyles: [],
  platforms: ["tiktok", "instagram", "youtube"],
  minViews: 50000,
  minLikes: 2000,
  dateRangeDays: 90,
  targetCount: 5,
  autoRelax: true,
  userInstruction: "",
  directUrls: "",
  promptImages: [],
  promptText: "",
  storyboardText: "",
  requirementsFile: null,
  storyboardFile: null,
};

export default function App() {
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [bootError, setBootError] = useState<string>("");
  const [config, setConfig] = useState<ConfigCheck | null>(null);

  const [history, setHistory] = useState<ScanSessionSummary[]>([]);
  const [historyQuery, setHistoryQuery] = useState("");
  const [activeSession, setActiveSession] = useState<ScanSessionDetail | null>(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // New scan form state
  const [files, setFiles] = useState<File[]>([]);
  const [productName, setProductName] = useState("");
  const [productText, setProductText] = useState("");
  const [params, setParams] = useState<RadarFormParams>(DEFAULT_PARAMS);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");
  const [showDna, setShowDna] = useState(true);

  const [selectedVideo, setSelectedVideo] = useState<VideoRecord | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const unsubRef = useRef<(() => void) | null>(null);
  const autoOpenedSessionRef = useRef<string | null>(null);

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast((curr) => (curr === msg ? null : curr)), 2400);
  }, []);

  const refreshHistory = useCallback(async (q = "") => {
    try {
      const list = await api.listHistory(q);
      setHistory(list);
    } catch {
      // ignore
    }
  }, []);

  const bootstrap = useCallback(async () => {
    try {
      setBootError("");
      const status = await api.authStatus();
      setAuth(status);
      if (status.authenticated) {
        const [cfg, list] = await Promise.all([api.configCheck(), api.listHistory("")]);
        setConfig(cfg);
        setHistory(list);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "连接服务器失败";
      if (msg.includes("401")) {
        setAuth({ password_required: true, authenticated: false });
      } else {
        // During Render deploy restarts, keep retrying instead of rendering an empty broken page
        setBootError(`服务器正在更新或唤醒中（${msg}），3 秒后自动重连...`);
        setTimeout(() => {
          bootstrap();
        }, 3000);
      }
    }
  }, []);

  useEffect(() => {
    bootstrap();
    return () => {
      unsubRef.current?.();
    };
  }, [bootstrap]);

  useEffect(() => {
    if (!auth?.authenticated) return;
    const t = setTimeout(() => {
      refreshHistory(historyQuery);
    }, 250);
    return () => clearTimeout(t);
  }, [historyQuery, auth?.authenticated, refreshHistory]);

  // Reliable 3-second polling safety net alongside SSE so Render proxy / mobile network
  // SSE drops NEVER freeze the progress bar at 10%.
  const activeSessionId = activeSession?.id || null;
  const activeSessionStatus = activeSession?.status || null;
  useEffect(() => {
    if (!activeSessionId || !activeSessionStatus) return;
    if (activeSessionStatus === "completed" || activeSessionStatus === "failed") return;
    const timer = setInterval(() => {
      api
        .getScanDetail(activeSessionId)
        .then((detail) => {
          setActiveSession((prev) => (prev && prev.id === detail.id ? detail : prev));
          if (detail.status === "completed" || detail.status === "failed") {
            refreshHistory(historyQuery);
          }
        })
        .catch(() => {});
    }, 3000);
    return () => clearInterval(timer);
  }, [activeSessionId, activeSessionStatus, historyQuery, refreshHistory]);

  // Auto-open the Studio Workbench right away when a prompt_import session finishes
  useEffect(() => {
    if (
      activeSession &&
      activeSession.mode === "prompt_import" &&
      activeSession.status === "completed" &&
      activeSession.videos.length === 1 &&
      autoOpenedSessionRef.current !== activeSession.id
    ) {
      autoOpenedSessionRef.current = activeSession.id;
      setSelectedVideo(activeSession.videos[0]);
    }
  }, [activeSession]);

  const subscribeToSession = useCallback(
    (sessionId: string) => {
      unsubRef.current?.();
      unsubRef.current = api.subscribeEvents(
        sessionId,
        (ev) => {
          setActiveSession((prev) => {
            if (!prev || prev.id !== sessionId) return prev;
            return {
              ...prev,
              status: ev.status,
              progress_percent: ev.progress_percent,
              progress_message: ev.progress_message,
              error_message: ev.error_message,
              product_name: ev.product_name || prev.product_name,
              history_title: ev.history_title || prev.history_title,
              funnel_stats: ev.funnel_stats || prev.funnel_stats,
            };
          });
          if (ev.status === "completed" || ev.status === "failed") {
            api.getScanDetail(sessionId).then(setActiveSession).catch(() => {});
            refreshHistory(historyQuery);
          }
        },
        () => {
          api.getScanDetail(sessionId).then(setActiveSession).catch(() => {});
          refreshHistory(historyQuery);
        }
      );
    },
    [historyQuery, refreshHistory]
  );

  const openSession = async (id: string) => {
    unsubRef.current?.();
    try {
      const detail = await api.getScanDetail(id);
      setActiveSession(detail);
      if (detail.status !== "completed" && detail.status !== "failed") {
        subscribeToSession(id);
      }
    } catch (err) {
      showToast(err instanceof Error ? err.message : "加载历史记录失败");
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await api.deleteScan(id);
      if (activeSession?.id === id) {
        unsubRef.current?.();
        setActiveSession(null);
      }
      refreshHistory(historyQuery);
      showToast("已删除该历史记录");
    } catch {
      showToast("删除失败");
    }
  };

  const handleStartScan = async () => {
    setFormError("");
    if (params.mode === "prompt_import") {
      if (
        params.promptImages.length === 0 &&
        !params.promptText.trim() &&
        !params.storyboardText.trim() &&
        !params.requirementsFile &&
        !params.storyboardFile
      ) {
        setFormError("请上传「视频要求提示词」和/或「分镜内容」文件（或粘贴文本/上传截图）");
        return;
      }
    } else {
      if (files.length === 0 && !productText.trim() && !productName.trim()) {
        setFormError("请先上传至少一份产品资料（图片/视频/文档）或输入产品说明");
        return;
      }
      if (params.mode === "direct_urls" && !params.directUrls.trim()) {
        setFormError("请粘贴至少 1 条 TikTok / Instagram / YouTube 视频链接");
        return;
      }
    }

    setSubmitting(true);
    try {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f));
      fd.append("product_text", productText);
      fd.append("product_name_override", productName);

      let resp: { session_id: string; history_title: string };
      if (params.mode === "prompt_import") {
        params.promptImages.forEach((img) => fd.append("prompt_images", img));
        fd.append("prompt_text", params.promptText);
        fd.append("storyboard_text", params.storyboardText);
        if (
          params.requirementsFile &&
          (params.requirementsFile.name.toLowerCase().endsWith(".docx") || !params.promptText.trim())
        ) {
          fd.append("requirements_file", params.requirementsFile);
        }
        if (
          params.storyboardFile &&
          (params.storyboardFile.name.toLowerCase().endsWith(".docx") ||
            !params.storyboardText.trim())
        ) {
          fd.append("storyboard_file", params.storyboardFile);
        }
        resp = await api.startPromptImport(fd);
      } else if (params.mode === "direct_urls") {
        fd.append("user_instruction", params.userInstruction);
        fd.append("urls", params.directUrls);
        resp = await api.startDirectUrlScan(fd);
      } else {
        fd.append("user_instruction", params.userInstruction);
        fd.append("platforms", JSON.stringify(params.platforms));
        fd.append("min_views", String(params.minViews));
        fd.append("min_likes", String(params.minLikes));
        fd.append("date_range_days", String(params.dateRangeDays));
        fd.append("target_count", String(params.targetCount));
        fd.append("auto_relax", String(params.autoRelax));
        fd.append("search_strategy", params.searchStrategy);
        fd.append("creative_styles", JSON.stringify(params.creativeStyles));
        resp = await api.startRadarScan(fd);
      }

      const detail = await api.getScanDetail(resp.session_id);
      setActiveSession(detail);
      subscribeToSession(resp.session_id);
      refreshHistory(historyQuery);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "启动扫描失败");
    } finally {
      setSubmitting(false);
    }
  };

  if (!auth) {
    return (
      <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center gap-3 px-4 text-center">
        <div className="text-slate-300 text-sm">
          {bootError || "正在连接雷达引擎..."}
        </div>
        {bootError && (
          <button
            type="button"
            onClick={bootstrap}
            className="px-4 py-2 rounded-xl bg-sky-500 hover:bg-sky-400 text-slate-950 font-semibold text-xs"
          >
            立即重试连接
          </button>
        )}
      </div>
    );
  }

  if (auth.password_required && !auth.authenticated) {
    return <LoginGate onSuccess={bootstrap} />;
  }

  return (
    <div className="h-screen flex flex-col bg-slate-950 text-slate-100 overflow-hidden">
      {/* Top Navbar */}
      <header className="h-14 shrink-0 border-b border-slate-800 bg-slate-900/90 backdrop-blur px-3 sm:px-5 flex items-center justify-between gap-2 z-30">
        <div className="flex items-center gap-2.5 min-w-0">
          <button
            type="button"
            onClick={() => setMobileMenuOpen(true)}
            className="lg:hidden p-2 rounded-lg text-slate-300 hover:bg-slate-800"
            aria-label="打开历史记录"
          >
            <Menu className="w-5 h-5" />
          </button>
          <div className="w-8 h-8 rounded-xl bg-sky-500/20 border border-sky-400/40 flex items-center justify-center shrink-0">
            <Radar className="w-4 h-4 text-sky-400" />
          </div>
          <div className="min-w-0">
            <h1 className="text-sm sm:text-base font-bold text-white truncate">
              短视频爆款扫描雷达
            </h1>
            <p className="hidden sm:block text-[11px] text-slate-400 truncate">
              TK · INS · YouTube 高播高赞可替换拆解 & 可灵 / ChatGPT Images 提示词工作台
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <ConfigStatusBadge config={config} />
          {auth.password_required && (
            <button
              type="button"
              onClick={async () => {
                await api.logout();
                setAuth({ password_required: true, authenticated: false });
              }}
              title="退出登录"
              className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800"
            >
              <LogOut className="w-4 h-4" />
            </button>
          )}
        </div>
      </header>

      {/* Main Split Area */}
      <div className="flex-1 flex min-h-0">
        <HistorySidebar
          items={history}
          activeId={activeSession?.id || null}
          searchQuery={historyQuery}
          onSearchChange={setHistoryQuery}
          onSelect={openSession}
          onNewScan={() => {
            unsubRef.current?.();
            setActiveSession(null);
          }}
          onDelete={handleDelete}
          mobileOpen={mobileMenuOpen}
          onCloseMobile={() => setMobileMenuOpen(false)}
        />

        <main className="flex-1 overflow-y-auto p-3 sm:p-6">
          <div className="max-w-6xl mx-auto space-y-5 pb-12">
            {/* New Scan Form Panel (visible when no active session selected) */}
            {!activeSession ? (
              <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-4 sm:p-6 space-y-5 shadow-xl">
                <div>
                  <h2 className="text-base sm:text-lg font-bold text-white flex items-center gap-2">
                    <Sparkles className="w-5 h-5 text-sky-400" />
                    上传产品资料，开启四级省 Token 爆款雷达
                  </h2>
                  <p className="text-xs text-slate-400 mt-1">
                    系统先提炼《产品基因卡》→ 0 Token 三平台实时抓高播高赞 → 低成本淘汰不可替换视频 → 仅对入选爆款做原生视频深度拆解与提示词生成
                  </p>
                </div>

                <ProductUploader
                  files={files}
                  onFilesChange={setFiles}
                  productName={productName}
                  onProductNameChange={setProductName}
                  productText={productText}
                  onProductTextChange={setProductText}
                />

                {formError && (
                  <div className="text-xs text-rose-300 bg-rose-500/10 border border-rose-500/30 rounded-xl px-3.5 py-2.5">
                    {formError}
                  </div>
                )}

                <RadarControls
                  params={params}
                  onChange={setParams}
                  submitting={submitting}
                  onSubmit={handleStartScan}
                />
              </div>
            ) : (
              <>
                {/* Active Session Header */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-slate-900/90 border border-slate-800 rounded-2xl p-4">
                  <div className="min-w-0">
                    <div className="text-xs text-sky-400 font-medium mb-0.5">
                      当前历史归档
                    </div>
                    <h2 className="text-base sm:text-lg font-bold text-white break-words">
                      {activeSession.history_title}
                    </h2>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 shrink-0">
                    <a
                      href={api.exportUrl(activeSession.id, "md")}
                      className="px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-100 inline-flex items-center gap-1.5"
                    >
                      <Download className="w-3.5 h-3.5 text-sky-400" />
                      导出 Markdown 手册
                    </a>
                    <a
                      href={api.exportUrl(activeSession.id, "json")}
                      className="px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-300 inline-flex items-center gap-1.5"
                    >
                      <Download className="w-3.5 h-3.5" />
                      JSON
                    </a>
                  </div>
                </div>

                {/* Live Progress & Funnel Bar */}
                <ScanProgressBar
                  status={activeSession.status}
                  progressPercent={activeSession.progress_percent}
                  progressMessage={activeSession.progress_message}
                  errorMessage={activeSession.error_message}
                  stats={activeSession.funnel_stats}
                />

                {/* Product DNA Card */}
                {activeSession.product_dna && (
                  <div className="bg-slate-900/80 border border-slate-800 rounded-2xl overflow-hidden">
                    <button
                      type="button"
                      onClick={() => setShowDna((v) => !v)}
                      className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-slate-800/40"
                    >
                      <div className="text-xs sm:text-sm font-semibold text-sky-300">
                        《产品基因卡》 · {activeSession.product_dna.product_name}（
                        {activeSession.product_dna.category}）
                      </div>
                      {showDna ? (
                        <ChevronUp className="w-4 h-4 text-slate-400" />
                      ) : (
                        <ChevronDown className="w-4 h-4 text-slate-400" />
                      )}
                    </button>
                    {showDna && (
                      <div className="px-4 pb-4 pt-1 border-t border-slate-800/80 space-y-3 text-xs">
                        {activeSession.product_assets.some((a) => a.thumbnail) && (
                          <div className="flex flex-wrap gap-2">
                            {activeSession.product_assets
                              .filter((a) => a.thumbnail)
                              .map((a, i) => (
                                <img
                                  key={i}
                                  src={a.thumbnail || ""}
                                  alt={a.filename}
                                  className="w-16 h-16 rounded-lg object-cover border border-slate-700"
                                />
                              ))}
                          </div>
                        )}
                        <p className="text-slate-300">
                          <span className="text-slate-500">外观与形态：</span>
                          {activeSession.product_dna.physical_form}
                        </p>
                        <div className="flex flex-wrap gap-1.5">
                          {(activeSession.product_dna.core_selling_points || []).map(
                            (sp, i) => (
                              <span
                                key={i}
                                className="px-2.5 py-1 rounded-full bg-sky-500/10 border border-sky-500/30 text-sky-200"
                              >
                                {sp}
                              </span>
                            )
                          )}
                        </div>
                        {activeSession.filter_config?.search_strategy === "cross_category" && (
                          <div className="text-[11px] text-emerald-300 bg-emerald-500/10 border border-emerald-500/30 rounded-lg px-2.5 py-1.5">
                            ✨ 跨品类爆款解耦模式：下方三平台搜索词已与上传产品完全解耦（严禁搜同品类），并会在初筛阶段自动剔除同品类视频，仅精选全网高创意爆款模板来替换你的产品。
                          </div>
                        )}
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 pt-1 text-[11px] text-slate-400">
                          <div>
                            <b className="text-cyan-300">TK 词：</b>
                            {(activeSession.product_dna.search_queries?.tiktok || []).join(" / ")}
                          </div>
                          <div>
                            <b className="text-pink-300">INS 词：</b>
                            {(activeSession.product_dna.search_queries?.instagram || []).join(" / ")}
                          </div>
                          <div>
                            <b className="text-rose-300">YT 词：</b>
                            {(activeSession.product_dna.search_queries?.youtube || []).join(" / ")}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Results Grid */}
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-sm sm:text-base font-bold text-white">
                      已收录高可替换爆款视频（{activeSession.videos.length} 条）
                    </h3>
                    <span className="text-xs text-slate-400">
                      按可替换性评分由高到低排序
                    </span>
                  </div>

                  {activeSession.videos.length === 0 ? (
                    <div className="bg-slate-900/60 border border-dashed border-slate-800 rounded-2xl py-14 text-center text-sm text-slate-400">
                      {activeSession.status === "completed" || activeSession.status === "failed"
                        ? "本轮未收录到符合高可替换门槛的视频，可点击左侧「新建产品雷达扫描」调整条件重试。"
                        : "雷达正在高速扫描与深度拆解中，收录结果完成后将自动呈现在这里..."}
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                      {activeSession.videos.map((v) => (
                        <VideoCard
                          key={v.id}
                          video={v}
                          onOpenDetail={setSelectedVideo}
                        />
                      ))}
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        </main>
      </div>

      {/* Video Detail Modal */}
      {selectedVideo && (
        <VideoDetailModal
          video={selectedVideo}
          onVideoUpdated={(updated) => {
            setSelectedVideo(updated);
            setActiveSession((prev) =>
              prev
                ? {
                    ...prev,
                    videos: prev.videos.map((item) =>
                      item.id === updated.id ? updated : item
                    ),
                  }
                : prev
            );
          }}
          onClose={() => setSelectedVideo(null)}
          onToast={showToast}
        />
      )}

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-5 left-1/2 -translate-x-1/2 z-[60] px-4 py-2.5 rounded-full bg-emerald-500 text-slate-950 font-semibold text-xs sm:text-sm shadow-xl">
          ✓ {toast}
        </div>
      )}
    </div>
  );
}
