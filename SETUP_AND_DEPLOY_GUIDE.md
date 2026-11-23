# 短视频扫描雷达 — 小白保姆级配置与免费上线指南

这份手册专门为你准备，**不需要懂代码，也不需要买传统服务器**，按下面 5 步照着点，就能拿到所有 Key，并把 Codex 写好的网页免费部署到线上，在**任意电脑和手机浏览器**随时打开使用！

---

## 总览：一共只需准备 4 样东西（全程可用国内方式，免买服务器）

| 序号 | 平台 | 作用 | 费用说明 |
| :--- | :--- | :--- | :--- |
| 1 | **TikHub** | 实时搜索 TikTok + Instagram + YouTube 播放/点赞数据 | 支持**支付宝**，无月租，最低充 5 美元（约 36 元）可用几百次 |
| 2 | **Gemini API** | 看视频、拆解分镜、写可灵与 ChatGPT Images 提示词 | Google 官方有**免费额度**；大用量可配支持支付宝/微信的中转 |
| 3 | **Neon** | 永久保存你的历史记录（时间 + 产品名） | **完全免费**，免信用卡 |
| 4 | **Hugging Face** | 免费运行你的网页（电脑+手机随时访问） | **完全免费**（16GB 大内存），免信用卡 |

---

## 第一步：把执行文档交给 Codex 开发

1. 打开你的 Codex 工具，进入项目文件夹：`/Users/xujinfeng/Desktop/gemini/viral-video-radar`
2. 直接复制下面这段话发给 Codex，让它按规范自动写完整个项目并自测：

```text
请仔细阅读当前目录的 CODEX_EXECUTION_PLAN.md，严格按照文档中的所有架构、四级省 Token 漏斗逻辑、TikHub 与 Gemini 接口规范、可灵 Kling 与 ChatGPT Images 提示词结构、访问密码锁、PC+手机自适应 UI 以及 Hugging Face Spaces Docker 部署要求，端到端完整开发本项目。完成后运行全部 pytest 测试与前端 build 验证，并在根目录生成 DELIVERY_REPORT.md。
```

3. 等 Codex 全部开发完成并回复你后，可以先把代码发给我做**全面审查与验收**，确认零 Bug 后再执行下方上线步骤（也可以边等 Codex 边按下面第 2~4 步提前准备好 Key）。

---

## 第二步：开通 TikHub 账号并获取三平台采集 Key（支持支付宝）

TikHub 可以用一个账号同时抓取 **TikTok、Instagram Reels、YouTube Shorts**，省去折腾 3 个平台的麻烦。

1. 浏览器打开 TikHub 官网：`https://tikhub.io`（如果打不开请确认网络处于全局/海外访问状态）。
2. 点击右上角 **Sign Up / Register**，用邮箱注册并登录。
3. **领取/充值额度**：
   - 新账号通常会送少量免费测试额度，够跑几次测试；
   - 点击后台左侧菜单 **Billing / Balance（余额充值）** -> 选择 **Alipay（支付宝）** -> 充值最低档 **5 美元（约 36 元人民币）** 即可（纯按量扣费，不用不花钱，单次搜索仅几厘到一两分钱）。
4. **创建并复制 API Key**：
   - 在后台左侧找到 **API Keys** -> 点击 **Create New API Key**（名称可填 `video-radar`）。
   - 生成后立刻复制保存到一个记事本里，记作：**`TIKHUB_API_KEY`**。

---

## 第三步：获取 Gemini AI Key（看视频最省 Token）

你有两种方式任选其一（推荐先用方案 A 免费体验，以后用量大了随时切方案 B）：

### 方案 A：Google 官方免费额度（0 元上手）
1. 打开 Google AI Studio：`https://aistudio.google.com/apikey`
2. 登录你的 Google 账号。
3. 点击 **Create API key**（创建 API 密钥）-> 复制生成的字符串（一般以 `AIza` 开头），记作：**`GEMINI_API_KEY`**。
4. 此时 `GEMINI_BASE_URL` 留空即可。

### 方案 B：使用支持支付宝/微信的聚合中转 API（免海外信用卡）
如果你后面发现 Google 免费版频次不够，又不想绑海外信用卡，可以使用支持支付宝/微信按量充值的中转平台（例如 `302.ai` 等支持 Gemini 官方接口格式的中转）：
1. 用微信/支付宝小额充值（如 10~20 元）。
2. 在中转平台创建一个 API Key 填到 `GEMINI_API_KEY`。
3. 把中转平台提供的接口地址填入 `GEMINI_BASE_URL` 即可无缝切换，代码无需任何修改。

---

## 第四步：免费开通 Neon 云数据库（永久保存历史记录）

为了让你在手机、公司电脑、家里电脑看到的都是同一份历史记录（`时间 · 产品名称`），且永远不丢数据，我们用 Neon 免费数据库：

1. 打开 Neon 官网：`https://neon.tech`
2. 点击 **Sign Up**，直接选择 **Continue with GitHub**（或 Google 账号）免费登录，不需要绑信用卡。
3. 登录后会自动提示新建一个项目（Create Project）：
   - Project name 填：`viral-video-radar`
   - Region（区域）默认选离你近的或 US East 即可
   - 点击 **Create Project**
4. 进入项目首页后，点击 **Connect** 按钮 -> 选择 **Connection string** -> 复制那一长串以 `postgresql://` 开头的链接（记得勾选显示密码），保存下来，记作：**`DATABASE_URL`**。

---

## 第五步：免费部署到 Hugging Face Spaces（电脑 + 手机随时打开）

部署完你会得到一个类似 `https://你的用户名-viral-video-radar.hf.space` 的专属网址，永久免费托管，手机和任意电脑打开就能用！

### 1. 注册并创建 Space
1. 打开 Hugging Face：`https://huggingface.co`，点击 **Sign Up** 免费注册账号。
2. 登录后点击右上角头像旁的 **`+ New`** -> 选择 **Space**。
3. 填写信息：
   - **Space name**：`viral-video-radar`
   - **Select the Space SDK**：点击 **Docker** -> 下面模板选 **Blank**
   - **Space hardware**：保持默认免费的 **CPU basic · 2 vCPU · 16 GB RAM · Free**
   - **Visibility**：选 **Public**（选 Public 才能免登录在手机浏览器直接打开；别担心安全，我们已经内置了你专属的访问密码锁！）
4. 点击 **Create Space**。

### 2. 填入你的私密 Key 与访问密码（非常重要）
1. 进入刚建好的 Space 页面，点击顶部菜单 **Settings**（设置）。
2. 往下滚动找到 **Variables and secrets** -> 点击 **New secret**，依次添加以下 5 项（**一定要加在 Secrets 里，不要加在公开的 Variables 里**）：

| Secret 名称（严格照抄） | 你填写的值 | 说明 |
| :--- | :--- | :--- |
| `APP_ACCESS_PASSWORD` | 你自己设一个密码（如 `MyRadar2026!`） | **打开网页的登录密码**，防别人盗刷 |
| `APP_SESSION_SECRET` | 随便敲 32 位以上乱码字母数字 | 登录加密签名用 |
| `DATABASE_URL` | 第四步复制的 `postgresql://...` | Neon 历史记录数据库 |
| `TIKHUB_API_KEY` | 第二步复制的 TikHub Key | 三平台数据采集 |
| `GEMINI_API_KEY` | 第三步复制的 Gemini Key | AI 视频拆解大脑 |

*(如果你用了国内中转 AI，再额外加一条 Secret：`GEMINI_BASE_URL`，填入中转地址即可。)*

### 3. 上传代码触发自动部署
有两种方式把 Codex 写好的代码传上去（选最顺手的）：
- **方式一（最推荐，用 Git 一行命令推送）**：在 Hugging Face 网页右上角头像 -> `Settings` -> `Access Tokens` 生成一个带 Write 权限的 Token，然后让 Codex 或在终端把项目推送到你的 Space Git 仓库地址。
- **方式二（网页点选上传）**：在 Space 顶部点 **Files** -> **Add file** -> **Upload files**，把整个项目文件拖进去提交。

上传完成后，页面顶部状态会变成 **Building（构建中）**，大约等待 **2~4 分钟**，变成绿色的 **Running** 就彻底上线成功！

---

## 第六步：在电脑和手机上使用

1. 点击 Hugging Face Space 页面右上角菜单 `⋮` -> **Embed this Space** -> 复制 **Direct URL**（格式为 `https://你的用户名-viral-video-radar.hf.space`）。
2. **电脑端**：直接把网址收藏到浏览器书签栏，输入你设定的 `APP_ACCESS_PASSWORD` 密码即可使用。
3. **手机端（像 App 一样使用）**：
   - 苹果 iPhone：用 Safari 打开你的专属网址 -> 点底部中间的分享图标 -> 选择 **「添加到主屏幕」**。
   - 安卓手机：用 Chrome/自带浏览器打开 -> 点右上角菜单 -> 选择 **「添加到主屏幕」**。
4. 登录后，先点右上角的 **「系统状态检测」** 指示灯，确认 TikHub、AI、数据库、FFmpeg 全部显示绿色 ✅，就可以上传产品资料开始雷达扫描了！

---

## 常见问题快速排错

- **Q：两天没用，再次打开网页时等了十几秒才出来？**
  - A：正常现象！免费版 Hugging Face Space 超过 48 小时没人访问会自动休眠省电，打开网址等 10~20 秒会自动唤醒，**Neon 云数据库里的历史记录一条都不会丢**。
- **Q：想修改访问密码怎么办？**
  - A：去 Hugging Face Space 的 `Settings` -> `Variables and secrets` 修改 `APP_ACCESS_PASSWORD`，保存后 Space 会自动重启生效。
- **Q：搜出来的结果太少怎么办？**
  - A：在网页参数里适当调低「最低播放量 / 最低点赞数」，或者把「时间范围」从 7 天放宽到 30 天，也可以直接在「指定链接直拆」里把你平时刷到的好视频链接贴进去直接拆解！
