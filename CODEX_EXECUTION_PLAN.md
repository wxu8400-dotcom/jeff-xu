# 短视频爆款扫描与可替换性拆解雷达 — Codex 完整执行规范 (CODEX_EXECUTION_PLAN.md)

> **致 Codex 执行者**：请严格按照本规范端到端开发、测试并交付完整可运行的项目。不要跳过任何核心功能，不要用假数据替代真实 API 逻辑（Mock 模式仅作为显式开关 `ENABLE_MOCK_MODE=true` 供无 Key 测试使用），不要硬编码任何密钥。完成所有模块和自测后，必须在项目根目录生成 `DELIVERY_REPORT.md` 供审查验收。

---

## 1. 项目目标与核心需求

构建一个面向电商与短视频运营者的全栈 Web 应用 **Viral Video Radar（短视频扫描雷达）**，实现以下四大核心能力：

1. **三平台实时高热扫描**：根据用户指令，实时搜索 **TikTok、Instagram (Reels)、YouTube (Shorts)** 的高播放、高点赞短视频。
2. **产品资料解析与“可替换性”精准收录**：支持用户上传产品**图片、视频、文档（PDF/DOCX/TXT/MD）、文字描述**。系统先提炼《产品基因卡（Product DNA）》，在筛选视频时严格评估原视频核心展示物品是否可替换为用户的产品，**仅收录高可替换性视频**。
3. **原生多模态深度拆解 + 可直接复制的 AI 提示词**：
   - 拆解：视频结构（黄金3秒/节奏/CTA）、逐秒分镜表（含替换为用户产品后的画面设计）、拍摄要求（布光/机位/道具/剪辑/BGM）、视频文案（原文/中文翻译/适配用户产品的改写文案）。
   - 判定原视频是否为 AI 制作，并**为所有收录视频**输出可直接一键复制的提示词：
     - **ChatGPT Images 提示词**（用于结合用户产品图生成爆款封面海报及各分镜首帧图）
     - **可灵 Kling 提示词**（分镜级图生视频/首尾帧 Prompt + 运镜/时长/负向提示词）
4. **跨设备免费云端部署 + 历史记录持久化**：
   - 响应式 Web 界面（PC 端与手机端均可流畅使用）。
   - 内置**访问密码锁**保护公网实例防盗刷。
   - 历史记录持久化至云端 PostgreSQL（Neon，本地开发兼容 SQLite），自动按 **`YYYY-MM-DD HH:mm · 产品名称`** 分类归档，支持回看、搜索、删除、导出 Markdown/JSON。

---

## 2. 技术栈与项目目录结构

采用**单容器前后端一体架构**，完美适配 **Hugging Face Spaces 免费 Docker（2 vCPU / 16GB RAM / 端口 7860）**，同时支持本地开发一键运行。

- **后端**：Python 3.11+、FastAPI、Uvicorn、SQLAlchemy 2.0、Alembic（或启动自动建表 `Base.metadata.create_all`）、`psycopg[binary]`、`httpx`、`google-genai`、`openai`（兼容中转）、`pypdf`、`python-docx`、`Pillow`、`yt-dlp`、系统级 `ffmpeg`。
- **前端**：React 18 + Vite + TypeScript + Tailwind CSS + `lucide-react`。构建产物 `frontend/dist` 由 FastAPI 托管为静态文件与 SPA 回退路由。
- **数据库**：生产环境使用 Neon PostgreSQL（通过 `DATABASE_URL`）；未配置 `DATABASE_URL` 时自动降级使用本地 `sqlite:///./data/radar.db`。

### 强制目录结构

```text
viral-video-radar/
├── README.md                        # 含 Hugging Face Spaces YAML frontmatter (sdk: docker, app_port: 7860)
├── Dockerfile                       # 多阶段构建：Node 构建前端 + Python 3.11 + FFmpeg 运行后端
├── .env.example                     # 完整环境变量模板（禁止提交真实 .env）
├── .gitignore
├── DELIVERY_REPORT.md               # Codex 完成后输出的验收自测报告
├── backend/
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py                  # FastAPI 入口、静态文件托管、路由注册、生命周期管理
│   │   ├── config.py                # Pydantic Settings 环境变量管理
│   │   ├── database.py              # SQLAlchemy 引擎（自动兼容 Postgres 与 SQLite）
│   │   ├── models.py                # ScanSession, VideoRecord ORM 模型
│   │   ├── schemas.py               # Pydantic 请求/响应与严格 AI 输出 Schema
│   │   ├── auth.py                  # 访问密码锁（HMAC Cookie / Bearer Token 鉴权中间件）
│   │   ├── routers/
│   │   │   ├── auth.py              # /api/auth/*
│   │   │   ├── scans.py             # /api/scans/* (创建扫描、SSE进度、历史CRUD、单链直拆、导出)
│   │   │   └── system.py            # /api/health, /api/system/config-check
│   │   └── services/
│   │       ├── product_parser.py    # 文档/图片/视频抽帧解析 + Product DNA 生成
│   │       ├── collectors/
│   │       │   ├── base.py          # 标准化 CandidateVideo 与 BaseCollector 接口
│   │       │   ├── tikhub.py        # TikHub API 适配器（TK + INS + YT）
│   │       │   ├── youtube_api.py   # 可选 YouTube Data API v3 官方免费适配器
│   │       │   └── mock.py          # 仅 ENABLE_MOCK_MODE=true 时启用的逼真模拟数据
│   │       ├── filter_engine.py     # Stage 2 纯代码 0-Token 规则过滤、去重、热度排序
│   │       ├── ai_client.py         # 统一 AI 客户端（支持 Gemini 原生视频 + 自定义 Base URL + OpenAI 兼容模式 + Token 计数）
│   │       ├── video_processor.py   # 视频下载 + FFmpeg 低码率压缩 (360p/1fps) + 自动清理 /tmp
│   │       ├── pipeline.py          # 四级漏斗编排器 + SSE 事件总线
│   │       ├── prompts.py           # 所有系统 Prompt 模板（Product DNA / 粗筛 / 精拆 / Kling / ChatGPT Images）
│   │       └── exporter.py          # Markdown & JSON 报告导出器
│   └── tests/
│       ├── test_auth.py
│       ├── test_filter_and_parser.py
│       ├── test_pipeline_mock.py
│       └── test_exporter_and_history.py
└── frontend/
    ├── package.json
    ├── vite.config.ts
    ├── tailwind.config.js
    ├── index.html
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── api/client.ts            # 封装 fetch、Cookie 鉴权、SSE 订阅
        ├── types/radar.ts           # 与后端 schemas.py 严格对齐的 TS 类型
        ├── components/
        │   ├── LoginGate.tsx        # 访问密码锁页面（移动端/PC端优雅居中）
        │   ├── HistorySidebar.tsx   # 按「时间 · 产品名」分类的历史侧边栏（手机端抽屉）
        │   ├── ProductUploader.tsx  # 多格式文件拖拽上传 + 文字说明 + 产品基因卡展示
        │   ├── RadarControls.tsx    # 平台勾选、播放/点赞阈值、时间范围、收录条数、单链直拆切换
        │   ├── ScanProgressBar.tsx  # 四级漏斗实时进度 + 实时 Token 与费用估算看板
        │   ├── VideoCard.tsx        # 收录视频卡片（封面、直链、数据、可替换性评分、AI标签）
        │   ├── VideoDetailModal.tsx # 五大拆解 Tab + 独立一键复制 Kling / ChatGPT Images 提示词
        │   └── ConfigStatusBadge.tsx# 顶部环境就绪状态检测弹窗
        └── utils/copy.ts            # 一键复制与 Toast 提示
```

---

## 3. 环境变量契约（`.env.example`）

后端所有敏感凭证必须从环境变量读取，绝不可硬编码或下发明文给前端：

```env
# === 应用安全与服务 ===
PORT=7860
APP_ACCESS_PASSWORD=change_me_to_your_password
APP_SESSION_SECRET=auto_generated_if_empty_please_set_random_32_chars

# === 数据库（生产环境填 Neon PostgreSQL，留空自动使用本地 SQLite） ===
DATABASE_URL=

# === 三平台数据采集源（TikHub 一套打通 TK + INS + YT） ===
TIKHUB_API_KEY=
TIKHUB_BASE_URL=https://api.tikhub.io
# 可选：若填了官方 YouTube Data API v3 Key，YouTube 将优先走免费官方接口
YOUTUBE_API_KEY=

# === AI 大脑配置（默认 Gemini 2.5 Flash，原生看视频最省 Token） ===
AI_PROVIDER=gemini
GEMINI_API_KEY=
# 可选：支持填写兼容中转地址（如支持支付宝/微信的聚合中转站），留空直连 Google 官方
GEMINI_BASE_URL=
GEMINI_FAST_MODEL=gemini-2.5-flash-lite
GEMINI_DEEP_MODEL=gemini-2.5-flash

# 可选兜底：当 AI_PROVIDER=openai_compatible 时生效
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_FAST_MODEL=gpt-4o-mini
OPENAI_DEEP_MODEL=gpt-4o

# === 调试开关（生产环境必须为 false） ===
ENABLE_MOCK_MODE=false
```

---

## 4. 数据库表结构设计（Neon PostgreSQL / SQLite 双兼容）

使用 SQLAlchemy ORM（使用 `JSON` 类型存储结构化字段，UUID 用 `String(36)` 以保证 Postgres 与 SQLite 100% 兼容）：

### 表 1：`scan_sessions`（扫描历史会话表）
| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| `id` | `String(36)` PK | UUID |
| `history_title` | `String(200)` Index | 格式固定为 `YYYY-MM-DD HH:mm · {product_name}`（使用东八区 `UTC+8` 时间格式化） |
| `product_name` | `String(120)` Index | 提取或用户填写的产品名称 |
| `mode` | `String(20)` | `radar`（三平台雷达扫描）或 `direct_urls`（手动链接直拆） |
| `status` | `String(32)` | `queued` / `extracting_product` / `collecting` / `filtering` / `screening` / `analyzing` / `completed` / `failed` |
| `progress_percent` | `Integer` | `0` ~ `100` |
| `progress_message` | `String(500)` | 当前步骤实时说明 |
| `error_message` | `Text` nullable | 失败原因 |
| `user_instruction` | `Text` | 用户输入的附加搜索指令 |
| `platforms` | `JSON` | 如 `["tiktok", "instagram", "youtube"]` |
| `filter_config` | `JSON` | `{"min_views": 100000, "min_likes": 5000, "date_range_days": 30, "target_count": 5, "auto_relax": true}` |
| `product_dna` | `JSON` | 提取后的《产品基因卡》 |
| `product_assets` | `JSON` | 已上传资料摘要列表（文件名、类型、压缩后 ≤ 40KB 的缩略图 DataURL，**严禁把原视频二进制存入数据库**） |
| `funnel_stats` | `JSON` | `{"collected": 60, "after_hard_filter": 18, "after_screening": 5, "analyzed": 5, "input_tokens": 0, "output_tokens": 0, "estimated_cost_cny": 0.0}` |
| `created_at` | `DateTime` Index | UTC 时间 |
| `updated_at` | `DateTime` | UTC 时间 |

### 表 2：`video_records`（正式收录的高可替换爆款视频表）
| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| `id` | `String(36)` PK | UUID |
| `session_id` | `String(36)` FK -> `scan_sessions.id` (CASCADE) | 所属历史会话 |
| `platform` | `String(20)` | `tiktok` / `instagram` / `youtube` |
| `platform_video_id` | `String(128)` | 平台原生视频 ID |
| `video_url` | `Text` | 可直接在浏览器/App 打开的原视频链接 |
| `download_url` | `Text` nullable | 临时无水印直链（若有） |
| `cover_url` | `Text` nullable | 封面图链接（或压缩缩略图 DataURL） |
| `author_name` | `String(120)` nullable | 创作者名称 |
| `title` | `Text` | 标题/简介 |
| `published_at` | `String(64)` nullable | 发布时间 |
| `duration_sec` | `Integer` nullable | 视频时长（秒） |
| `views` | `BigInteger` | 播放量 |
| `likes` | `BigInteger` | 点赞数 |
| `comments` | `BigInteger` | 评论数 |
| `shares` | `BigInteger` | 分享数 |
| `engagement_rate` | `Float` | 赞播比 `(likes / max(views, 1)) * 100` |
| `is_ai_generated` | `Boolean` | 是否判定为 AI 制作 |
| `ai_confidence` | `Integer` | `0` ~ `100` |
| `replaceability_score` | `Integer` | 最终可替换性评分 `0` ~ `100` |
| `original_featured_item` | `String(200)` | 原视频核心物品 |
| `analysis_mode` | `String(32)` | `native_video`（原生视频精拆）或 `fallback_frames`（无法下载时的降级拆解） |
| `analysis_json` | `JSON` | 完整结构化拆解与提示词 JSON（严格符合下方 Schema） |
| `token_usage` | `JSON` | `{"input_tokens": ..., "output_tokens": ...}` |
| `created_at` | `DateTime` | 收录时间 |

---

## 5. 核心四级漏斗省 Token 流水线（必须严格执行）

> **铁律**：绝不允许跳过漏斗直接把大量原始视频送给大模型！每个阶段必须记录耗时、剩余条数和 Token 消耗，并通过 SSE 实时推送给前端。

### Stage 0：产品资料解析与《产品基因卡》生成（仅运行 1 次）
1. 接收用户上传的多模态文件 + 文本：
   - **文档**（`.pdf`, `.docx`, `.txt`, `.md`）：分别用 `pypdf`、`python-docx`、UTF-8 解码在本地提取纯文本（0 Token），超过 6000 字符智能截断保留关键信息。
   - **产品图片**（`.jpg`, `.jpeg`, `.png`, `.webp`）：Pillow 缩放到长边 ≤ 768px 传给 AI，同时生成长边 ≤ 320px JPEG (quality=70) 的轻量缩略图用于历史存档。
   - **产品视频**（`.mp4`, `.mov`, `.webm`）：存入 `/tmp` 后使用 FFmpeg 均匀抽取 4 张关键帧（≤ 768px）传给 AI，取第 1 张生成缩略图存入历史，**抽帧完毕立即删除 `/tmp` 原视频**。
2. 调用 `GEMINI_FAST_MODEL`（强制 JSON 输出）生成 `ProductDNA`：
   ```json
   {
     "product_name": "产品简短名称（用于历史分类命名）",
     "category": "细分类目",
     "physical_form": "体积、形态、材质、视觉特征（如：掌心大小磨砂白色手持风扇）",
     "core_selling_points": ["核心卖点1", "核心卖点2", "核心卖点3"],
     "target_audience": "目标受众画像",
     "usage_scenarios": ["使用场景1", "使用场景2"],
     "replaceable_visual_slots": ["适合替换的视频物品类型，如：手持小家电展示、桌面开箱特写、户外便携对比"],
     "avoid_patterns": ["应排除的视频类型，如：纯口播无道具、大型家具、强IP剧情"],
     "search_queries": {
       "tiktok": ["2-3个高转化英文/爆款搜索词"],
       "instagram": ["2-3个适合Reels的关键词或标签词"],
       "youtube": ["2-3个适合YouTube Shorts的爆款搜索词"]
     }
   }
   ```
3. 立即将 `product_name` 和 `history_title = "{YYYY-MM-DD HH:mm} · {product_name}"` 写入 `scan_sessions`。

### Stage 1：三平台实时数据采集（0 Token）
- 所有采集器返回统一对象 `CandidateVideo`：`platform`, `platform_video_id`, `video_url`, `download_url`, `cover_url`, `author_name`, `title`, `caption`, `published_at`, `duration_sec`, `views`, `likes`, `comments`, `shares`。
- **TikHub API 适配器（`backend/app/services/collectors/tikhub.py`）**：
  - 使用 `Authorization: Bearer {TIKHUB_API_KEY}` 请求 `TIKHUB_BASE_URL`。
  - **实现健壮的多路径容错与响应解析**（因为社交平台接口响应结构嵌套深且 TikHub 有 v1/v2/v3 路由）：
    - **TikTok 搜索**：优先调用 `/api/v1/tiktok/app/v3/fetch_general_search_result` 或 `/api/v1/tiktok/web/fetch_search_video`（按 `keyword`，支持 `sort_type` 热度排序），兼容解析 `aweme_list` / `data` 字段，提取 `statistics.play_count`、`statistics.digg_count`、`video.play_addr.url_list[0]`、标准分享链接 `https://www.tiktok.com/@{unique_id}/video/{aweme_id}`。
    - **Instagram Reels 搜索**：优先调用 `/api/v1/instagram/v2/search_reels` / `/api/v1/instagram/v1/fetch_hashtag_posts`（若关键词含空格自动派生无空格 hashtag 备选），兼容解析 `play_count` / `view_count`、`like_count`、`video_versions[0].url`、标准链接 `https://www.instagram.com/reel/{code}/`。
    - **YouTube Shorts 搜索**：若配置了 `YOUTUBE_API_KEY`，优先使用 `youtube_api.py`（官方免费 API：`search.list` 带 `videoDuration=short` + `order=viewCount` -> 再批量调用 `videos.list` 获取精确 `viewCount`/`likeCount`/`contentDetails.duration`）；未配置时自动回退调用 TikHub `/api/v1/youtube/web/search_video`（关键词自动拼接 `#shorts` 或筛选时长 ≤ 75s）。
  - 对网络超时、429 限流做最多 2 次指数退避重试；单平台报错时记录警告并继续其他平台，**不能因单个平台故障导致整次扫描失败**。
- **并发执行**：三个平台使用 `asyncio.gather` 并发采集，降低总耗时。

### Stage 2：纯代码规则硬过滤与排序（0 Token）
- 去重：按 `(platform, platform_video_id)` 去重。
- 时长过滤：优先保留 `5s <= duration_sec <= 120s`（若接口未返回时长则放行）。
- 指标过滤：严格过滤 `views >= min_views` 且 `likes >= min_likes`，以及发布时间在 `date_range_days` 范围内（无发布时间字段时放行）。
- 若 `auto_relax=true` 且严格阈值下总候选数 `< target_count`，允许阶梯放宽阈值（70% -> 40%）并在 `progress_message` 和前端结果摘要中透明告知用户“已自动放宽阈值以补充候选”。
- 综合热度分排序：按 `log10(views + 1) * 0.5 + log10(likes + 1) * 0.35 + engagement_rate * 0.15` 排序，每个平台最多保留前 10 条（总上限 ≤ 25 条）进入 Stage 3。

### Stage 3：可替换性低成本粗筛（极省 Token）
- **严禁在此阶段下载视频！**
- 仅将最多 25 条候选视频的 `id + platform + title + caption(前250字) + duration_sec + 压缩封面图(≤384px，下载失败则仅发文本)` 按每批 5 条打包发送给 `GEMINI_FAST_MODEL`。
- 对照 `ProductDNA` 严格评估：
  1. 原视频是否以“具体实体物品演示/开箱/对比/场景使用”为核心？（纯脱口秀、新闻播报、无实物剧情直接判低分）
  2. 物品槽位是否能自然替换为用户上传的产品？（体积、形态、交互动作是否匹配）
  3. 画面是否具备可复刻性？（强绑定大明星脸、超高成本电影特效或无法替换的特定版权角色直接淘汰）
- 强制过滤规则：**只保留 `preliminary_score >= 65` 的视频**，按分数降序截取前 `target_count` 条（默认 5 条，上限 10 条）进入 Stage 4！若全部低于 65 分，返回友好提示并建议用户调整关键词或放宽条件，**绝不强行收录不可替换的垃圾视频**。

### Stage 4：原生视频深度拆解 & 提示词生成（仅对最终收录 Top N 执行）
1. **视频极速压缩（核心省 Token 策略）**：
   - 下载入选视频到 `/tmp/radar_{uuid}.mp4`（优先 `download_url`，失败则用 `yt-dlp -f "worst[height>=360]/best[height<=480]"`）。
   - 使用 **FFmpeg** 强制转码压缩：
     ```bash
     ffmpeg -y -i input.mp4 -t 60 -vf "scale=-2:360,fps=1" -c:v libx264 -preset veryfast -crf 30 -ac 1 -ar 16000 -b:a 48k output.mp4
     ```
   - 压缩后通常仅 0.8MB ~ 2.5MB，上传给 Gemini Files API 或内联 bytes 进行原生视频+音频理解。
   - 分析完成后在 `finally` 块中**强制删除所有 `/tmp` 临时视频与抽帧文件**。
   - **降级兜底**：如果某条视频因平台防盗链无法下载，自动降级为“封面图 + 标题文案 + 产品基因卡”深度推演拆解，并将 `analysis_mode` 设为 `fallback_frames` 告知用户。
2. **严格结构化 JSON 输出（`VideoDeepAnalysis` Schema）**：
   每条视频一次调用 `GEMINI_DEEP_MODEL`（要求严格 JSON 输出并做 Pydantic 校验，解析失败自动重试 1 次），必须包含以下全部字段：

```json
{
  "is_ai_generated": false,
  "ai_confidence": 85,
  "ai_detection_reason": "说明判断依据（画面物理规律、光影材质、字幕/标签特征等）",
  "replaceability": {
    "score": 90,
    "original_featured_item": "原视频中展示的核心物品",
    "replacement_strategy": "详细说明如何把原视频物品替换为用户上传的产品，以及保留哪些爆款视觉钩子",
    "replacement_difficulty": "低",
    "recommended_workflow": "实拍复刻 + AI复刻双方案皆可"
  },
  "structure": {
    "hook_3s": "黄金3秒画面+文案钩子解析",
    "pacing_curve": "整体节奏与情绪曲线（如：0-3s痛点冲击 -> 3-12s产品演示 -> 12-20s效果对比 -> 20-25s行动号召）",
    "conversion_cta": "结尾转化话术与视觉引导",
    "viral_reasons": ["爆款原因1", "爆款原因2", "爆款原因3"]
  },
  "storyboard": [
    {
      "shot_no": 1,
      "time_range": "00:00-00:03",
      "shot_size": "特写",
      "camera_movement": "快速推镜",
      "original_visual": "原视频画面内容",
      "adapted_visual_for_product": "替换为【用户产品】后的具体画面设计",
      "audio_sfx": "音效、人声与BGM变化"
    }
  ],
  "shooting_requirements": {
    "lighting": "布光方案（自然光/柔光箱/逆光轮廓光等）",
    "camera_setup": "机位角度、景深与手机/相机拍摄参数建议",
    "props_and_scene": "场景布置与辅助道具清单",
    "editing_rhythm": "剪辑切点、转场、花字/字幕节奏要求",
    "bgm_style": "推荐音乐情绪、BPM 节奏与卡点方式"
  },
  "copywriting": {
    "original_transcript": "原视频语音转录与画面文字",
    "chinese_translation": "原视频文案准确中文翻译",
    "adapted_script_cn": "结合用户产品核心卖点改写的【直接可用中文口播/字幕文案】",
    "adapted_script_en": "结合用户产品核心卖点改写的【出海直接可用英文口播/字幕文案】",
    "caption_and_hashtags": "推荐发布标题 + 8~10个精准流量标签"
  },
  "chatgpt_images_prompts": [
    {
      "scene_title": "爆款主视觉海报 / 分镜1首帧参考图",
      "usage_note": "在 ChatGPT 中上传你的产品实拍图，然后直接复制下方提示词发送",
      "aspect_ratio": "9:16",
      "prompt_en": "完整详尽、可直接复制的英文自然语言提示词：明确要求100%还原所上传参考图中的产品外观、材质、颜色与Logo细节，详细描述构图、摆放位置、真实商业摄影光影、景深、背景元素与海报留白排版",
      "prompt_cn": "对应的完整中文提示词，方便理解与微调"
    }
  ],
  "kling_prompts": [
    {
      "shot_no": 1,
      "scene_title": "分镜1：黄金3秒产品亮相",
      "mode": "图生视频 (I2V) — 配合上方分镜1首帧图使用",
      "recommended_params": "时长: 5s | 画质: 高品质 | 运镜: 缓慢推进 | 创意相关性: 0.5",
      "prompt_cn": "可直接复制到可灵 Kling 中文版的完整提示词（严格遵循：主体与细节 + 流畅自然动作 + 运镜方式 + 真实光影材质 + 电影级质感）",
      "prompt_en": "可直接复制到可灵 Kling 国际版的完整英文提示词",
      "negative_prompt": "变形, 模糊, 产品Logo扭曲, 穿模, 多余手指, 闪烁, 画面撕裂, 水印, 杂乱文字"
    }
  ]
}
```

> **提示词质量硬性要求**：
> - `chatgpt_images_prompts` 必须至少生成 **1 条爆款宣传海报提示词 + 对应核心分镜的首帧图提示词（总计 3~6 条）**，每条都必须结合用户上传的产品特征具体描述，绝不允许出现 `[这里填你的产品]` 之类的敷衍占位符！
> - `kling_prompts` 必须与核心分镜对应（3~6 条），明确适配可灵 Kling 的图生视频逻辑，给出具体物理动作与运镜，避免让 AI 生成扭曲文字。
> - 无论原视频是 AI 制作还是实拍，**均必须完整输出 `chatgpt_images_prompts` 和 `kling_prompts`**；并在 UI 明确区分“AI 原片复刻提示词”与“实拍转 AI 复刻提示词”。

---

## 6. API 接口与安全门禁契约

### 访问密码门禁（公网防盗刷）
- 若环境变量 `APP_ACCESS_PASSWORD` 非空：
  - 除 `/api/health`、`/api/auth/login`、`/api/auth/status` 以及前端静态页面外，所有 `/api/*` 请求必须校验已签名的 HttpOnly Cookie（`radar_session`）或 `X-Access-Token`，未登录返回 `401`。
  - 前端检测到未登录时，渲染简洁美观的 `LoginGate` 密码输入页，验证通过后长期保持会话（默认 30 天）。

### 业务 API 列表
1. `GET /api/health` — 健康检查（返回 `{"status": "ok"}`）。
2. `GET /api/system/config-check` — 检查 TikHub、YouTube API、Gemini/AI、数据库连接类型（Postgres/SQLite）、FFmpeg、Mock 模式是否就绪（**仅返回布尔状态与模型名，严禁泄露任何 Key 字符**）。
3. `POST /api/auth/login` / `POST /api/auth/logout` / `GET /api/auth/status`。
4. `POST /api/scans` — `multipart/form-data` 提交：
   - `files`: 多文件上传（图片/视频/PDF/DOCX/TXT/MD）
   - `product_text`: 产品文字描述
   - `product_name_override`: 可选产品名（不填由 AI 自动提取）
   - `user_instruction`: 搜索与筛选指令
   - `platforms`: JSON 数组（默认 `["tiktok","instagram","youtube"]`）
   - `min_views`, `min_likes`, `date_range_days`, `target_count`, `auto_relax`
   - 立即创建 `scan_sessions` 记录并在后台 `asyncio.create_task` 启动流水线，返回 `{"session_id": "..."}`。
5. `POST /api/scans/analyze-urls` — **单链直拆模式**：上传产品资料 + 粘贴 1~5 条 TK/INS/YT 视频链接，直接进行可替换性评分与全套拆解。
6. `GET /api/scans/{session_id}/events` — **SSE 实时流**：推送进度百分比、当前漏斗阶段、实时漏斗数字（已抓取 -> 硬过滤 -> 初筛 -> 精拆）、实时 Token 与估算人民币费用，直到 `completed` 或 `failed`。
7. `GET /api/scans?q=&limit=50` — 历史记录列表（按 `created_at DESC` 排序，支持按产品名或 `history_title` 搜索）。
8. `GET /api/scans/{session_id}` — 获取完整会话详情（含 `product_dna`、`funnel_stats` 和全部 `video_records`）。
9. `DELETE /api/scans/{session_id}` — 删除指定历史记录（级联删除关联视频）。
10. `GET /api/scans/{session_id}/export?format=md|json` — 下载排版精美的完整拆解与提示词文件（文件名：`{history_title}.md`）。

---

## 7. 前端界面与交互规范（PC + 手机自适应）

1. **视觉风格**：现代科技感深蓝/深灰专业工作台（或清爽高对比浅色主题），清晰信息层级，中文界面为主。
2. **移动端（手机浏览器）强适配**：
   - 屏幕宽度 `< 768px` 时，左侧历史记录栏自动折叠为顶部菜单抽屉；
   - 上传区、参数表单、视频卡片、详情弹窗全屏自适应，按钮热区 ≥ 44px，**手机端单指即可一键复制提示词与跳转原视频链接**。
3. **核心交互区块**：
   - **左侧历史记录栏**：按 **`YYYY-MM-DD HH:mm · 产品名称`** 清晰分组列出，显示收录条数与状态标签；支持搜索过滤、一键切换回看、删除、导出 Markdown。
   - **顶部控制与上传区**：
     - 模式切换 Tab：「三平台雷达扫描」 / 「指定链接直拆」。
     - 支持拖拽或点选上传图片、视频、文档（显示已选文件图标与大小），下方附带产品文字说明框。
     - 雷达参数栏（提供快捷预设：如「十万播放起」「百万爆款」「近7天飙升」，也可手填最低播放量、最低点赞数、目标收录条数 3~10）。
     - 显眼的 **「启动雷达扫描」** 主按钮。
   - **四级漏斗实时进度条**：扫描进行中时可视化展示每一步状态（产品解析 -> 三平台采集 -> 0-Token硬过滤 -> 可替换性初筛 -> 原生视频深度拆解），同步显示实时消耗 Token 与估算成本（人民币）。
   - **收录结果区**：
     - 顶部先展示可折叠的《产品基因卡》与本次搜索使用的跨平台关键词。
     - 下方为高可替换爆款视频卡片网格：封面、平台彩色徽章（TK/INS/YT）、播放/点赞/赞播比、**可替换性得分徽章（绿色 ≥85 / 蓝色 65-84）**、**「AI制作」或「实拍」标签**、原视频直链按钮（新标签页打开）、「查看完整拆解与提示词」按钮。
   - **详情拆解抽屉/弹窗（5 个清晰 Tab）**：
     1. **概览 & 可替换方案**：原视频核心物品、替换成我产品的落地方案、结构拆解（黄金3秒/节奏/CTA/爆款原因）。
     2. **逐秒分镜表**：表格/时间轴卡片对比展示「原片画面」vs「替换为你产品后的新画面」+ 景别/运镜/音效。
     3. **拍摄与制作要求**：布光、机位、道具场景、剪辑节奏、BGM 风格。
     4. **视频文案**：原声文案、中文翻译、**中文改写文案（一键复制）**、**英文出海文案（一键复制）**、标题与标签（一键复制）。
     5. **AI 提示词工坊（重点打磨）**：
        - 分区 A：**ChatGPT Images 提示词（海报 & 分镜首帧图）** — 每条带使用提示、比例徽章、中英文切换、**独立一键复制按钮**。
        - 分区 B：**可灵 Kling 视频提示词** — 按分镜排列，展示推荐模式与运镜/时长参数、中文/英文 Prompt、负向提示词，每条均带**独立一键复制按钮**，顶部提供**「一键复制全部 Kling 分镜提示词」**按钮。

---

## 8. Hugging Face Spaces 部署规范

1. 项目根目录 `README.md` 顶部**必须**包含如下 YAML Frontmatter：
   ```yaml
   ---
   title: Viral Video Radar
   emoji: 📡
   colorFrom: indigo
   colorTo: cyan
   sdk: docker
   app_port: 7860
   pinned: false
   ---
   ```
2. 项目根目录 `Dockerfile` 采用多阶段构建：
   - Stage 1 (`node:20-alpine`)：安装前端依赖并执行 `npm run build` 生成 `/frontend/dist`。
   - Stage 2 (`python:3.11-slim`)：安装系统依赖 `ffmpeg`、`curl`，安装 `backend/requirements.txt`，复制后端代码与 Stage 1 构建的 `frontend/dist`；创建可写非 root 友好目录（`/app/data`、`/tmp`），暴露 `7860` 端口，启动命令：
     ```dockerfile
     CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
     ```
3. 注意 HF Spaces 容器运行用户权限问题（UID 1000），确保 `/app/data` 与临时目录有写权限（如 `chmod -R 777 /app/data` 或使用 `/tmp`）。

---

## 9. Codex 开发执行顺序与强制自测清单

请按以下顺序推进，每一步自测通过后再进入下一步：

1. **阶段 1（后端基础与数据库）**：搭建 FastAPI、Config、SQLAlchemy（Postgres/SQLite 双兼容）、访问密码锁鉴权、`config-check` 接口。
2. **阶段 2（四级漏斗引擎与采集器）**：实现 `product_parser.py`、`tikhub.py`、`youtube_api.py`、`mock.py`、`filter_engine.py`、`video_processor.py`、`ai_client.py`、`prompts.py`、`pipeline.py`、`exporter.py`。
3. **阶段 3（前端完整开发与构建）**：实现全部页面与手机/PC 自适应 UI，确保 `npm run build` 零 TypeScript / Vite 报错。
4. **阶段 4（前后端联调与自动化测试）**：
   - 编写并运行 `pytest` 覆盖：
     1. 密码锁鉴权拦截与正常登录；
     2. PDF/DOCX/TXT/图片解析与缩略图生成；
     3. 0-Token 规则硬过滤与阈值自动放宽；
     4. Mock 模式下完整四级漏斗端到端扫描、SSE 事件流、可替换性低分淘汰验证、结构化拆解与 Kling/ChatGPT Images 提示词字段完整性校验；
     5. 历史记录 `YYYY-MM-DD HH:mm · 产品名` 命名、搜索、详情回看、删除、Markdown/JSON 导出。
   - 在 `ENABLE_MOCK_MODE=true` 下启动 FastAPI 服务，验证前端静态页面可正常打开且所有接口返回预期数据。
5. **阶段 5（输出验收报告 `DELIVERY_REPORT.md`）**：
   - 在根目录生成 `DELIVERY_REPORT.md`，列出：已完成功能清单、已运行的测试命令与通过结果、Dockerfile 构建说明、以及任何需要注意的配置项，供后续审查人员验收。
