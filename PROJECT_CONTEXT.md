# Viral Video Radar — 项目交接与全量上下文记忆 (PROJECT_CONTEXT.md)

> **供新对话中的 Agent 快速恢复全部上下文**：阅读本文件即可完整继承本项目的所有需求、架构、部署信息、已解决的问题及下一步 V2.0 规划。

---

## 1. 核心业务需求

1. **三平台高播高赞短视频扫描雷达**：支持 **TikTok / Instagram Reels / YouTube Shorts** 实时搜索高播放、高点赞短视频。
2. **跨品类“可替换性”精准收录**：
   - 用户上传产品资料（图片、视频、PDF/DOCX/TXT 文档、文字）。
   - **核心筛选哲学（重要！）**：不是死板地只搜“同品类产品安装/测评视频”，而是**双轨策略**：
     - 主力搜索**跨品类爆款视觉创意模板**（如画册翻开 3D 悬浮弹出、FOOH 户外巨物 CGI、AI 产品商业广告、极简美学开箱、前后空间改造——例如《家具产品悬浮》视频里的沙发可直接替换为用户的 LED 线性灯）；
     - 辅以 C 端泛场景高热词（**严禁**生成枯燥的 B2B 批发/工厂工程长尾词）。
3. **深度拆解 + 一键复制 AI 提示词**：
   - 输出：视频结构（黄金3秒/节奏/CTA）、逐秒分镜表（原片 vs 替换为我方产品）、拍摄要求、中英文改写可用文案。
   - **所有收录视频**（无论原片为 AI 制作还是实拍）均输出可直接一键复制的：
     - **ChatGPT Images** 海报 & 分镜首帧提示词（结合用户产品图融合）；
     - **可灵 Kling** 分镜级中文/英文/负向提示词 + 运镜与时长参数。
4. **跨设备免费云端部署 + 历史持久化**：
   - 网页端自适应 PC 与手机浏览器；
   - 历史记录按 **`YYYY-MM-DD HH:mm · 产品名称`** 归档并永久保存在 Neon PostgreSQL；
   - 公网访问密码锁（`APP_ACCESS_PASSWORD`）防盗刷。

---

## 2. 当前已上线环境信息（不含明文密钥）

- **本地项目目录**：`/Users/xujinfeng/Desktop/gemini/viral-video-radar`
- **GitHub 私有仓库**：`https://github.com/wxu8400-dotcom/jeff-xu.git`（分支 `main`，本机 macOS Keychain 已配置 `osxkeychain` 凭据，可直接 `git push origin main` 自动触发 Render 重建上线）
- **线上免费托管**：Render.com Free Web Service (Docker)
  - 线上访问网址：`https://video-radar-yoyp.onrender.com`
  - Render 控制台：`https://dashboard.render.com/web/srv-dc290sg8v5cc73buhqa0`
  - Render 环境变量页：`https://dashboard.render.com/web/srv-dc290sg8v5cc73buhqa0/env`
- **已配置并验证绿灯的 6 项能力**：
  1. `TIKHUB_API_KEY`（TikHub，支持支付宝充值，覆盖 TK + INS + YT）
  2. `YOUTUBE_API_KEY`（Google Cloud `video-radar` 项目免费 YouTube Data API v3）
  3. `GEMINI_API_KEY` + `GEMINI_FAST_MODEL=gemini-3.5-flash-lite` + `GEMINI_DEEP_MODEL=gemini-3.5-flash`（内置 404 自动降级链）
  4. `DATABASE_URL`（Neon PostgreSQL 永久免费云数据库）
  5. 容器内置 `ffmpeg`（`360p / 1fps / -threads 1 -preset ultrafast` 适配 Render 512MB 内存）
  6. `APP_ACCESS_PASSWORD` + `APP_SESSION_SECRET`

---

## 3. 历史关键迭代记录

- `098e14c`：V1.0 完整前后端交付（FastAPI + React Vite Tailwind + 四级省 Token 漏斗 + 5 项 pytest 全过 + Render Docker 首次 1m38s 部署成功）。
- `a98017f`：升级默认模型为 `gemini-3.5-flash-lite` / `gemini-3.5-flash` 并增加 404 自动降级容错。
- `e7ee173`：重构跨品类爆款视觉模板双轨搜索策略 + 放宽跨品类可替换初筛评分 + 对齐 TikHub 最新 OpenAPI 专用搜索路由（`fetch_video_search_result`、`v2/search_reels`、`web_v2/get_shorts_search_v2`）+ 递归字段解析 + 分平台抓取数量展示。
- `ba33e4b`：新增跨品类/混合/同品类搜索策略切换 + Gemini `503/429` 自动重试与多模型降级链。
- 本次迭代：代码级彻底解耦跨品类搜索与上传产品（新增 `viral_templates.py` 6 大爆款视觉创意模板词库 + 中英双语品类泄漏词硬拦截 + 初筛阶段同品类硬剔除与三平台均衡筛选 + 前端创意视觉模板多选标签 + 9 项 pytest 全过）。

---

## 4. 已规划的下一步功能：V2.0「一键生成同款商品图 & 同款 AI 短视频」

用户在 V1.0 扫描效果验证满意后，希望新增：
1. **一键生成同款商品海报 / 分镜首帧图**：将用户上传的商品实拍图 + 原爆款视频关键分镜构图 + ChatGPT Images 提示词，直接调用生图 API（`gpt-image-1` 或 Gemini 原生生图模型），先出图让用户审图确认商品 100% 还原。
2. **一键生成同款可灵 AI 短视频**：选中满意的同款首帧图，直接调用可灵 Kling I2V API（支持支付宝/微信的开放平台或中转），网页端在线播放 + 下载 MP4，并支持用 FFmpeg 自动拼接多镜头成片。
