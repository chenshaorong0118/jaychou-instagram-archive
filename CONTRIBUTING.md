# 贡献指南 / Contributing

本项目接受对 Schema、验证器、时间线生成器和文档的修正。不要通过 Pull Request 提交 Cookie、Token、原始接口响应、日志、本地数据库、签名 CDN URL、授权证明或其他敏感材料。

Corrections to schemas, verifiers, timeline generators, and documentation are welcome. Do not submit cookies, tokens, raw API responses, logs, local databases, signed CDN URLs, permission records, or other sensitive material.

本项目不接受通过 Issue 或 Pull Request 提交的媒体、录屏、截屏、无 Instagram
PK 的内容或补索引请求。公开媒体只由维护者本地的规范采集与发布流程写入。

This project does not accept media, screen recordings, screenshots, content without
an Instagram PK, or index-backfill requests through issues or pull requests. Public
media is written only by the maintainer's canonical local collection and publication
workflow.

代码、Schema、时间线或文档修改应通过
`python3 tools/verify_index.py .` 和
`python3 tools/generate_timeline.py . --check`。不要在公开 Issue 或 PR 中上传
敏感授权材料。
