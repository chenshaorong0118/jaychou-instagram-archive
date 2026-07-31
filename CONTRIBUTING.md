# 贡献指南 / Contributing

欢迎修正静态前端、验证器、Schema 与文档。本仓库不通过 Issue 或 Pull Request
接收媒体文件、截图、录屏或归档条目投稿；生成的数据文件也不应手工修改。

Corrections to the static frontend, verifiers, schemas, and documentation are
welcome. Media files, screenshots, recordings, and archive-item submissions are
not accepted through issues or pull requests. Generated data files should not be
edited by hand.

提交内容不得包含 Cookie、Token、签名 URL、原始接口响应、日志、本地数据库、
绝对路径或授权材料。

Never submit cookies, tokens, signed URLs, raw API responses, logs, local
databases, absolute paths, or authorization material.

提交前请运行：

```bash
python3 -m unittest discover -s tests -v
python3 tools/verify_index.py .
npm ci
npm run build
```
