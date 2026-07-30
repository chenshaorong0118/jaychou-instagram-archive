# Jay Chou Instagram 公开归档 / Public Archive

一个非官方、可验证、固定到 Git commit 的 Posts 与 Stories 静态画廊。

An unofficial, verifiable static gallery of archived Posts and Stories pinned to immutable Git commits.

- Posts: 16
- Stories: 54
- Media positions / 媒体位置: 102
- Date range / 时间范围: 2026-07-04T23:08:41+08:00 — 2026-07-29T22:50:19+08:00

## 浏览 / Browse

GitHub Pages 画廊按年月浏览，并支持瀑布流/网格切换、简繁穿透搜索、
媒体类型过滤、灯箱轮播和内嵌视频播放。列表只请求本地生成的 WebP
缩略图；原图和视频只在打开灯箱后按固定 commit 加载。

[打开公开画廊 / Open the gallery](https://chenshaorong0118.github.io/jaychou-instagram-archive/)

## 无冲突发布协议 / Conflict-free publishing

采集设备只执行单向的 `archive publish sync`：本地生成缩略图、FFprobe
音轨标记和 UUID batch，然后向两个仓库推送同名
`archive-batch/<client_id>/<batch_id>` 无父分支。客户端不会读取或修改远端
聚合索引，也不会同步 SQLite。

索引仓库的串行 GitHub Action 是共享 `main` 的唯一写入者。它先验证并幂等
写入媒体仓库，再确定性重建 JSONL、搜索索引和月度安全元数据镜像，最后部署
Pages 并删除成功 batch 的两个临时分支。失败 batch 会写入 `rejected/` 且保留
临时分支。

数据接口：

- `index/items.jsonl`：完整画廊索引
- `index/search-items.json`：紧凑前端搜索索引
- `index/metadata/YYYY-MM.json`：按月安全元数据镜像
- `processed/YYYY/MM/*.json`：已聚合 batch 回执
- `rejected/YYYY/MM/*.json`：被拒绝 batch 回执

## 媒体分库 / Media shard

[chenshaorong0118/jaychou-instagram-archive-media-0001](https://github.com/chenshaorong0118/jaychou-instagram-archive-media-0001)
是当前固定活动分库。设备配置显式指定它，封存换库时人工更新配置，不从远端发现。

## 验证 / Verification

```bash
python3 -m unittest discover -s tests -v
python3 tools/verify_index.py .
npm ci
npm run build
```

媒体权利不由代码许可证覆盖。请阅读 [MEDIA_RIGHTS.md](MEDIA_RIGHTS.md)。

Archived media is not covered by the code license. See [MEDIA_RIGHTS.md](MEDIA_RIGHTS.md).
