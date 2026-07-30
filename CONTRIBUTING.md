# 贡献指南 / Contributing

本项目接受对 Schema、验证器、静态前端和文档的修正。不要通过 Pull Request
提交 Cookie、Token、原始接口响应、日志、本地数据库、签名 CDN URL、授权证明
或其他敏感材料。

Corrections to schemas, verifiers, the static frontend, and documentation are
welcome. Do not submit cookies, tokens, raw API responses, logs, local databases,
signed CDN URLs, permission records, or other sensitive material.

本项目不接受通过 Issue 或 Pull Request 提交的媒体、录屏、截屏、无 Instagram
PK 的内容或补索引请求。公开媒体只由维护者本地的规范采集与发布流程写入。

This project does not accept media, screen recordings, screenshots, content without
an Instagram PK, or index-backfill requests through issues or pull requests. Public
media is written only by the maintainer's canonical local collection and publication
workflow.

代码、Schema、前端或文档修改应通过：

```bash
python3 -m unittest discover -s tests -v
python3 tools/verify_index.py .
npm ci
npm run build
```

公开媒体只能由维护者本地生成的 UUID batch 进入
`archive-batch/<client_id>/<batch_id>` 临时分支，再由聚合 Action 写入共享
`main`。不要直接修改 `index/items.jsonl`、搜索索引、元数据镜像或媒体仓库
`main`，也不要在公开 Issue 或 PR 中上传敏感授权材料。
