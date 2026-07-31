# Jay Chou Instagram 公开归档 / Public Archive

非官方的 Posts 与 Stories 静态画廊。媒体链接固定到 Git commit，便于稳定浏览与完整性校验。

An unofficial static gallery of archived Posts and Stories. Media URLs are pinned
to Git commits for stable browsing and integrity verification.

[打开公开画廊 / Open the gallery](https://chenshaorong0118.github.io/jaychou-instagram-archive/)

## 功能 / Features

- 按年月浏览，支持瀑布流与网格视图
- 简繁中文穿透搜索及媒体类型筛选
- 列表仅延迟加载 WebP 缩略图
- 灯箱轮播原图，并内嵌播放视频
- 纯静态 GitHub Pages，不依赖运行时 API

## 数据 / Data

- `index/items.jsonl`：画廊条目和固定媒体引用
- `index/search-items.json`：浏览器端轻量搜索数据
- `index/metadata/YYYY-MM.json`：按月内容与媒体描述

媒体文件位于
[jaychou-instagram-archive-media-0001](https://github.com/chenshaorong0118/jaychou-instagram-archive-media-0001)。

## 验证 / Verification

```bash
python3 -m unittest discover -s tests -v
python3 tools/verify_index.py .
npm ci
npm run build
```

媒体权利不由代码许可证覆盖。请阅读 [MEDIA_RIGHTS.md](MEDIA_RIGHTS.md)。

Archived media is not covered by the code license. See [MEDIA_RIGHTS.md](MEDIA_RIGHTS.md).
