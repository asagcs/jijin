# API · 本地 HTTP 与业务

| 文件 | 职责 |
| --- | --- |
| `server.py` | `ThreadingHTTPServer`，`/api/data`、`/api/final`、OCR 等 |
| `service.py` | 预计 / 最终 / 调仓 / 截图对齐持仓 / 导出给 AI |
| `engine.py` | 规则与 `config.json` / `state.json` |
| `store.py` | SQLite `data/fundlife.db` |
| `ai.py` | DeepSeek |
| `quotes.py` | 新浪估值、东财净值、基金代码搜索 |
| `ocr.py` | 本地 OCR（`tools/*.ps1`） |
| `keybox.py` | DeepSeek 密钥（DPAPI） |
| `paths.py` | 项目根、打包资源路径 |

根目录 `web.py` 为启动入口；桌面端在后台线程调用 `api.server.make_server`。