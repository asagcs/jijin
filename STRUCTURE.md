# 项目结构

```
G:\money\
├── web/              # Web 面板（静态页）
├── api/              # HTTP API + 业务核心
├── desktop/          # 桌面端 UI（tkinter）
├── tools/            # OCR PowerShell 脚本
├── pack/             # 打进 exe 的空白 config 模板
├── desktop.py        # 桌面入口
├── web.py            # 仅开浏览器面板时的入口
├── run.py            # 命令行 / today.txt
└── build_exe.ps1     # 打包
```

数据与产物仍在项目根：`config.json`、`state.json`、`data/`、`reports/`、`inbox/`（见 `.gitignore`）。