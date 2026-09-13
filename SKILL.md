---
name: powerfun
description: "跑步数据分析。当用户要求分析跑步数据、跑分、查看跑步报告时使用。基于 Garmin Connect 数据，生成 HTML/PDF 综合报告和深度分析报告。"
metadata:
  {"openclaw": {"requires": {"bins": ["python3"]}}}
---

# PowerFun 跑步数据分析技能

基于 Garmin Connect (China) 数据的跑步分析：报告生成 + 单次跑步深度分析（含 AI 教练点评）。

## 执行约定

- 所有命令必须用项目 venv：`cd ~/Projects/skills/PowerFun && source venv/bin/activate`
- 必须用 `exec` + `yieldMs=180000`（3 分钟）前台运行，LLM 期间日志实时返回；不用 background
- `KIMI_API_KEY` 从 `~/.openclaw/.env` 自动加载，无需手动设置

**「跑步分析」类触发**：直接跑 `python3 main.py --load-parquet --deep-analyze latest --user-note "<体感>"`。不手动查日期、不打印数据行。`latest` 自动解析为 parquet 中最新一次跑步；当天重复运行会自动复用 LLM 缓存（秒回），需要重新生成时加 `--force`。

## 运行模式

| 场景 | 命令 |
|------|------|
| 拉取最新数据 + 生成完整报告 | `python3 main.py` |
| 仅生成报告（跳过 API 拉取） | `python3 main.py --load-parquet` |
| 深析某一天 | `python3 main.py --load-parquet --deep-analyze YYYY-MM-DD` |
| 深析最新一次 + 体感备注 | `python3 main.py --load-parquet --deep-analyze latest --user-note "<体感>"` |
| 强制重新生成（覆盖缓存） | 以上命令加 `--force` |
| 首次使用（需账号密码） | `python3 main.py --email EMAIL --password PASSWORD` |
| 仅生成 PDF（从已有 HTML 转换） | `python3 main.py --pdf-only` |

> `--load-parquet` 需要已存在的 `~/Documents/Run/running_data.parquet`，首次使用先完整跑一次 `python3 main.py`。
> 冷启动：先看 `~/Projects/skills/PowerFun/.data/garmin_tokens/` 是否有 token，没有则需用户提供 Garmin 账号密码。

## 心率和功率参数

在 `src/config.py` 的 `USER_CONFIG` 中配置：`max_hr`（当前 188）、`resting_hr`（当前 60）。用户实测心率不一致时先改配置再运行。

## 输出

| 文件 | 路径 |
|------|------|
| 综合报告 (HTML) | `~/Documents/Run/PowerFun.html` |
| 深析报告 (HTML) | `~/Documents/Run/PowerFun_Reports/run_analysis_YYYYMMDD_<activity_id>.html` |
| iCloud 同步 | `~/Library/Mobile Documents/com~apple~CloudDocs/RUN/`（PowerFun.html + 深度分析报告_*.html） |

## ⚠️ LLM 故障处理

深度分析依赖 Kimi Code API（`api.kimi.com/coding/v1/chat/completions`，模型 `kimi-for-coding`）。
LLM 调用失败不中断报告，AI 点评区显示降级文案（`API Key 未配置` / `AI 分析调用失败: …`），日志有具体错误。
故障时向用户报告错误原因，不自行换模型或改配置。
