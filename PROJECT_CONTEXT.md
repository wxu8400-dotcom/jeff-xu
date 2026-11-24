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
- `08a54fb`：代码级彻底解耦跨品类搜索与上传产品（新增 `viral_templates.py` 6 大爆款视觉创意模板词库 + 中英双语品类泄漏词硬拦截 + 初筛阶段同品类硬剔除与三平台均衡筛选 + 前端创意视觉模板多选标签）。
- **V2.0 一键复刻工坊**：
  - 网页内新增「🚀 一键复刻工坊」作为视频详情默认首屏，自动记忆用户上传的商品高清参考图，无需切换任何外部网站重复传图；
  - 支持 **全片 100% 由 AI 生成（完全免实拍免上传）** 与 **AI + 手机实拍混剪** 双模式及单镜自由切换；
  - 支持 **Gemini 原生生图**（复用现有 `GEMINI_API_KEY`）与 **ChatGPT (`gpt-image-1`)** 在网页端一键切换，支持单镜生成/重绘及一键生成全部分镜商品图；
  - 接入 **可灵 Kling I2V API**（兼容官方 AK/SK JWT 自动签名与支付宝中转 Bearer Key），同时未配可灵时也可通过 **FFmpeg 图转平滑推镜动态 + 实拍混剪** 直接合成 9:16 竖屏 MP4 成片并在线播放下载；
  - 升级极简「📋 实拍分镜执行清单」卡片（逐镜标明拍摄动作、机位、口播台词、打勾状态与上传实拍入口）。

---

## 4. V2.0 新增可选环境变量（在 Render 环境变量页按需补充）

1. **一键生图**：默认直接复用已配好的 `GEMINI_API_KEY`（无需新加任何 Key）；如需在网页切换 ChatGPT `gpt-image-1`，补充 `OPENAI_IMAGE_API_KEY`（或 `OPENAI_API_KEY`）与可选 `OPENAI_IMAGE_BASE_URL`。
2. **可灵 Kling 一键图生视频**：官方开放平台填 `KLING_ACCESS_KEY` + `KLING_SECRET_KEY`（默认 `KLING_API_BASE_URL=https://api-beijing.klingai.com`）；若使用支付宝中转站，只需填 `KLING_API_KEY` + 中转站 `KLING_API_BASE_URL`。
