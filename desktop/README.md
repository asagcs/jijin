# 桌面端 UI

`app.py`：tkinter 小窗口（总市值、密钥、总计划金额、分析 / 导出给 AI）。

- 点「分析」→ 拉起同进程内的 API 服务 → 打开浏览器中的 `web/` 面板
- 数据目录 = exe 或项目根目录（`FUNDLIFE_HOME`）

根目录 `desktop.py` 为启动入口；打包 exe 时 PyInstaller 入口仍是 `desktop.py`。