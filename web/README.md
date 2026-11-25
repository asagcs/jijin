# Web · 浏览器面板

本目录是**纯前端**：`index.html`、`style.css`、`app.js`。

- 只读展示与表单录入，写入一律走 `POST /api/*`
- 由 `api/server.py` 在 `127.0.0.1:8766` 提供页面与接口
- 开发时可执行根目录 `启动网页.bat` 或 `python web.py`