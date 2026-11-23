---
title: Viral Video Radar
emoji: 📡
colorFrom: indigo
colorTo: cyan
sdk: docker
app_port: 7860
pinned: false
---

# Viral Video Radar · 短视频爆款扫描与可替换性拆解雷达

支持 **TikTok / Instagram Reels / YouTube Shorts** 实时高播放、高点赞短视频扫描，基于用户上传的产品资料（图片、视频、文档、文字）按**可替换性**精准收录，并自动完成结构拆解、逐秒分镜、拍摄要求、改写文案，以及可直接一键复制的 **ChatGPT Images（海报/首帧）** 与 **可灵 Kling（视频生成）** 提示词。

## 核心特性

- **四级省 Token 漏斗**：产品解析缓存 → 0-Token 三平台实时采集 → 0-Token 播放/点赞过滤 → 低清封面可替换性粗筛 → 仅对入选爆款执行 FFmpeg 360p/1fps 极速压缩与原生视频深度拆解。
- **双模式支持**：三平台爆款实时雷达 + 指定链接直接拆解。
- **跨设备云端持久化**：PC 与手机浏览器自适应；历史记录按 `YYYY-MM-DD HH:mm · 产品名称` 永久保存在云端 PostgreSQL（Neon），内置公网访问密码锁防盗刷。

## 配置与免费部署

请查看项目内完整保姆级文档：[SETUP_AND_DEPLOY_GUIDE.md](./SETUP_AND_DEPLOY_GUIDE.md)
