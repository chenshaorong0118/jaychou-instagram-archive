# 贡献指南 / Contributing

本项目接受对 Schema、验证器、时间线生成器和文档的修正。不要通过 Pull Request 提交 Cookie、Token、原始接口响应、日志、本地数据库、签名 CDN URL、授权证明或其他敏感材料。

Corrections to schemas, verifiers, timeline generators, and documentation are welcome. Do not submit cookies, tokens, raw API responses, logs, local databases, signed CDN URLs, permission records, or other sensitive material.

媒体或元数据修正必须：

Media or metadata corrections must:

1. 指明条目 PK 和固定的媒体 commit / identify the item PK and pinned media commit;
2. 说明可验证的依据 / describe the verifiable basis;
3. 保留原始 caption、visible text、用户名和音乐标题，不做机器翻译 / preserve original captions, visible text, usernames, and music titles without machine translation;
4. 通过 `python3 tools/verify_index.py .` 和 `python3 tools/generate_timeline.py . --check`。

媒体再分发资格由发布者负责确认；不要在公开 Issue 或 PR 中上传敏感授权材料。

Publishers are responsible for confirming the basis for media redistribution. Do not upload sensitive permission evidence to a public issue or pull request.
