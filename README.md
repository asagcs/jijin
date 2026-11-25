# G:\money · 基金持仓纪律系统

以 **2026-11-20 的持仓截图** 为基线（30 只基金，总市值 16,618.51 元），
按「总资金 3 万、科技仓位不超过 35%、现金预备金 30%」的框架，把每天的涨跌幅换算成**具体该做什么**。

**代码分三层**（见各目录下 `README.md`）：

| 目录 | 角色 |
| --- | --- |
| `web/` | **Web 面板**：HTML / CSS / JS，浏览器里操作 |
| `api/` | **API 与业务**：HTTP 服务、`engine` / `store` / `service`、行情与 DeepSeek |
| `desktop/` | **桌面端 UI**：tkinter 小窗，内嵌拉起 API |
| 根目录 `desktop.py` / `web.py` | 启动入口（打包 exe 仍用 `desktop.py`） |

- **API**：读当天市值/涨跌幅 → 算规则或 DeepSeek → 写进 SQLite / `state.json`。
- **Web**：展示 + 预计 / 最终 / 调仓 / 传图识别（写入都走 `/api/*`）。

## 每天怎么用（网页三按钮）

页面右上角三个按钮，对应三种真实场景：

1. **`预计录入 14:30`** —— 盘中按你估的收盘市值（或涨跌幅）先算一遍建议。
   **不入库、不写历史**，页面顶部会挂「预计模式 · 未入库」徽标，点「回到实际」或刷新即恢复。
   用途：14:30 看今天大概该不该动手。
2. **`最终更新`** —— 收盘后填当天真实值，写入 `state.json` + 历史库 + `reports\`，成为当天正式记录。
   弹窗里可以 **上传支付宝/天天基金的持仓截图**（也能拖拽或 Ctrl+V 粘贴），系统做本地 OCR：
   - 配了 DeepSeek key → OCR 文字交给 DeepSeek 结构化，按基金 id 回填市值，行会标「待核对」；
   - 没配 key → 只给出 OCR 原文（「看 OCR 原文」按钮），你照着手工填。
   **识别结果一律人工核对后再保存。**
3. **`调仓`** —— 记录买入 / 卖出 / 转换，直接改持仓市值与成本，并在「最近调仓」里留痕。

首次使用可以完全没有数据：先 `python run.py --init` 建基线（或直接在网页填一次最终值）。

旧的手写流程仍然可用：`today.txt` + `运行.bat`，效果等同。

## 桌面端（双击即用）

双击桌面的 **「基金纪律面板」** 快捷方式（或 `启动桌面.bat`），弹出一个没有控制台的小窗口：

- 窗口里直接显示 **总市值 / 持仓盈亏 / 科技占比**，以及最新一天「必做 N 条、择机 N 条」和第一条风险提示；
- 中间只有一个 **「分 析」** 按钮：点一下 → 确保 Web 服务在跑 → 取最新数据 → **用默认浏览器打开面板**（带时间戳，不走缓存）；
- 「打开数据目录」「重启服务」「退出」三个小按钮备用；
- 启动时会自动把 Web 服务拉到后台，不需要再点 `启动网页.bat`。

桌面端只是外壳，所有写入仍由 Python 端完成（源码运行用 `pythonw desktop.py`，只依赖标准库 tkinter）。

## 打包成单个 exe

已经在 `G:\money` 生成 **`基金纪律面板.exe`（约 10.6 MB，单文件、双击无黑窗）**，桌面快捷方式也指向它。

要自己重新打包，双击 **`打包exe.bat`**（= `powershell -File build_exe.ps1`），脚本会：

1. 找到带 tkinter 的 Python（默认 `Python310`，找不到就退回 `py -3`）；
2. 没装 PyInstaller 就自动 `pip install pyinstaller`；
3. 用 `--onefile --noconsole` 打包，并把 `web\`、`tools\`、`config.json`、`README.md` 一起塞进去；
4. 把产物 `dist\基金纪律面板.exe` 复制到项目根目录，并刷新桌面快捷方式；
5. 打印 exe 大小和用法。

两条踩过的坑，已经写进代码：

- **数据目录**：打包后 `state.json` / `data\fundlife.db` / `reports\` 一律落在 **exe 所在文件夹**（用环境变量 `FUNDLIFE_HOME` 指定），静态页面从解包目录读（`FUNDLIFE_ASSETS`）。所以别把 exe 单独挪到别的空文件夹，否则会当成全新账本。
- **无控制台**：`--noconsole` 下 `sys.stderr` 是 `None`，访问日志一写就会把每个请求打断。`web.py` 的 `log_message` 已加判空，出问题也能从 `desktop.log` 里看启动与报错。

Web 服务和桌面窗口现在跑在**同一个进程**里（后台线程起 `ThreadingHTTPServer`），exe 不需要本机装 Python，也不会多弹一个命令行窗口。

## 两个端各自做什么

| | Python 端 | Web 端 |
| --- | --- | --- |
| 入口 | `运行.bat` / `run.py` | `启动网页.bat` / `web.py` |
| 职责 | 规则引擎、写库、生成当日报告、CLI 三种操作 | 展示 + 三个录入入口（预计 / 最终 / 调仓） |
| 依赖 | 仅 Python 标准库（sqlite3 内置） | 仅 Python 标准库 `http.server` + 原生 HTML/JS，不联网、无外部 CDN |
| 端口 | — | 127.0.0.1:8766（被占用会自动顺延） |
| 写入 | `data\fundlife.db`、`reports\`、`state.json` | 只通过 API 交给 Python 端写 |

## Web 面板里有什么

- **顶部三个按钮**：预计录入（14:30）/ 最终更新 / 调仓；另有「刷新」。
- **顶部指标卡**：总市值、持仓盈亏、科技相关占比（对比 35% 上限）、现金预备金（对比 30%）、持仓只数、历史天数。
- **组合市值曲线**：左轴总市值与持仓成本，右轴科技占比；历史天数越多曲线越完整。
- **持仓与今日动作**：每只基金的今日涨跌、持有收益、自低点反弹、市值、权重、当日动作（含金额）；
  支持按分类（清理 / 核心 / 海外 / 防守）、优先级（必做 / 择机 / 观察 / 持有）筛选，搜索与排序；点行展开理由。
- **组合体检**：科技超限、现金不足、回撤触发、持仓只数、单只上限。
- **历史记录**：按日期切换，右侧显示当天建议（持有组默认折叠）。
- **最近调仓**：最近的买卖/转换流水。
- **颜色约定**：红涨绿跌（A 股习惯）。

## DeepSeek 怎么接

打开 `config.json`，把 key 填进引号里（留空也能用，只是跳过 AI 复核）：

```json
"deepseek": {
  "api_key": "sk-xxxxxxxxxxxxxxxx",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-chat"
}
```

填了之后，本地规则结论会交给 DeepSeek 复核一次，固定输出三段：今日最该做的一件事 / 对清单有无异议 / 明天盯什么信号。
结果会写进当天的 Markdown 报告，Web 面板只展示规则清单（不展示 AI 文本）。
临时不调用：`python run.py --no-ai`。

截图识别也会用它：`/api/ocr` 先本地 OCR 出文字，再把文字 + 30 只基金清单交给 DeepSeek 还原「哪只基金 = 多少钱」，回填到「最终更新」弹窗。
注意：**DeepSeek 的对话模型不支持图片输入**，所以图片这一步必须留在本机，DeepSeek 只吃文字。

## 常用命令

```
python run.py                 # 读 today.txt，出今日建议并入库
python run.py --no-ai         # 只跑本地规则
python run.py --template      # 重新生成 today.txt 模板
python run.py --history       # 命令行查看历史（日期/市值/盈亏/科技占比/必做数）
python run.py --init          # 按 config.json 重建基线（自动备份 state.json）
python run.py --dca-off zs_chip,yh_jc   # 关闭定投并让系统记住
python web.py                 # 启动面板（--port 9000 / --no-open）

# 不开网页也能用（CLI 三种操作）
python run.py --estimate --values est.json                    # 预估，不落库
python run.py --final    --values final.json                  # 最终值，入库+报告
python run.py --trade --fund pa_sat --side sell --amount 300  # 卖
python run.py --trade --fund gf_bdt --side buy  --amount 200  # 买
python run.py --trade --fund gf_bdt --side switch --amount 200 --to fg_hk   # 转换
```

`--values` 的 JSON 长这样（`mode` 可填 `amount` 市值 或 `pct` 涨跌幅）：

```json
{"date":"2026-11-21","mode":"amount","values":{"gf_bdt":2331.63,"fg_hk":1112.20}}
```

## 关掉定投后让系统记住

建议里的「关闭定投」在 App 里真的关掉之后，执行 `python run.py --dca-off <id>`，
`id` 就是 `today.txt` 每行开头方括号里的那串，多个用逗号隔开。系统会写回 `config.json` 与 `state.json`，之后不再每天提醒。

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `config.json` | 30 只基金的清单、分类、金额、持有收益率、定投开关，以及全部规则参数 |
| `state.json` | 当日状态：净值指数、阶段低点、成本、当前市值、提醒标记 |
| `data\fundlife.db` | **历史库**：snapshot（每日组合）、nav_daily（每日净值）、advice（每日建议）、run_log、trades（调仓流水） |
| `today.txt` | 旧流程的涨跌幅输入（网页三按钮可替代它） |
| `run.py` / `engine.py` / `service.py` / `store.py` / `ai.py` / `ocr.py` | 入口 / 规则引擎 / 三种操作 / 入库 / DeepSeek / 截图 OCR |
| `desktop.py` + `启动桌面.bat` | 桌面端源码（先装 Python 再用的方式） |
| `build_exe.ps1` + `打包exe.bat` | 一键打包单文件 exe 的脚本 |
| `基金纪律面板.exe` | 打包产物，双击即用；数据就在它旁边的目录 |
| `desktop.log` | 桌面端启动/报错日志（出问题先看它） |
| `web.py` + `web\` | Web 服务与前端（`index.html`、`style.css`、`app.js`） |
| `tools\ocr_words.ps1` | 调 Windows 自带 OCR 的小脚本（结果用 UTF-8 回传，避免中文乱码） |
| `inbox\` | 上传的截图留底（`upload_<时间戳>.png`），可随手清 |
| `reports\` | 每日建议 Markdown 存档 |
| `daily_inputs\` | 每天填过的输入留底 |
| `运行.bat` / `启动网页.bat` / `重置基线.bat` / `生成今日模板.bat` | 双击即可用 |

## 四类基金，四套规则

| 分类 | 基金 | 规则 |
| --- | --- | --- |
| `CORE` 科技核心 | 广发半导体材料设备、富国港股互联网 | 底仓不动，只做小额定投；单日跌 ≥3% 加码 1.5 倍定投一次，单日涨 ≥5% 暂停定投，持有收益 ≥20% 分批止盈 |
| `CORE_OPT` 可选仓 | 富国创业板AI | 精简时优先砍，先关定投 |
| `CLEAR` 清理名单 | 其余 20 只（卫星、芯片设计、中欧信息科技、建信新兴A/C、机床、传媒、财通系、边角料…） | 立刻关定投（首次提醒算必做，之后转观察）；**自低点累计反弹 ≥5% 卖一半，≥8% 清干净**；单日涨 ≥5% 先卖 30%；单日跌 ≥3% 不卖等反弹 |
| `HOLD` 海外宽基 | 标普500、广发全球精选、纳指100 | 持有不追加 |
| `HOLD_DEF` 防守 | 生物医药、绿色主题、两只黄金 | 持有不动 |

## 参数怎么改

都在 `config.json` 的 `rules` 里，例如觉得反弹 5% 才卖太慢：

```json
"clear": { "rebound_tier1": 3.0, "rebound_tier2": 6.0, "sell_tier1": 0.5 }
```

改完直接运行即生效，不用重建状态（`state.json` 已累计各只基金的阶段低点）。
**只有改了持仓金额 / 增删基金**，才需要双击 `重置基线.bat`（会自动备份旧状态）。

## 四个注意点

1. 规则算的是「纪律」，不是「行情预测」。它不会让弱势基金变强，只是防止你在低点割、在高点追、给亏钱的标的继续输血。
2. 买入确认中的钱、货币基金不统计，`cash` 按「3 万 − 持仓市值」估算，中途加减资金请改 `config.json` 里的 `capital_total`。
3. 持仓盈亏由各只收益率反推成本，和 App 可能差几十元（以 App 为准）；比例和触发条件不受影响。
4. 历史库从 2026-11-20 开始记录，之前的日子没有数据；曲线天数随每天点一次「最终更新」（或 `run.py`）增长。Web 是本地只读面板，不对外网开放。
5. 「预计录入」的数据只存在内存里，**不写库、不留痕**，刷新就没了；要留记录必须走「最终更新」。
6. 截图识别是「辅助预填」不是「自动记账」：金额小数点/千分位常丢，必须对着 App 核对一眼再保存。

所有输出仅为个人纪律提示，不构成投资建议。
