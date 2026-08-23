---
name: powerfun
description: "跑步数据分析。当用户要求分析跑步数据、跑分、查看跑步报告时使用。基于 Garmin Connect 数据，生成 HTML/PDF 综合报告和深度分析报告。"
metadata:
  {"openclaw": {"requires": {"bins": ["python3"]}}}
---

# PowerFun 跑步数据分析技能

完全独立的跑步数据分析技能，整合 Garmin Connect (China) 区域数据获取 + 跑步数据分析 + 可视化报告生成。

## 触发词

- `跑步分析`
- `分析今天跑步数据`
- `分析跑步数据`
- `跑分`
- `跑分PDF`
- `生成跑分PDF`
- `PowerFun`

> **注意**：`跑分PDF` / `生成跑分PDF` 是独立的 PDF 转换功能，直接从已有 HTML 报告生成 PDF，不重新分析数据。需要先运行过一次完整的分析流程生成 HTML 报告。

## 功能

- 🔐 **自动登录**: Garmin Connect (China 区域) SSO 登录
- 📊 **智能拉取**: 首次全部拉取，后续增量更新
- 🧹 **数据清洗**: 字段映射、类型转换、异常检测
- ❤️ **心率区间**: Karvonen HRR 法，Z1-Z5 五区间（百分比固定，不可更改）
- ⏱️ **配速趋势**: 移动平均、趋势判断
- 📈 **可视化**: 13个Plotly交互式图表（图例居中、心率分布等）
- 📄 **HTML/PDF 报告**: 综合分析报告 + 深度分析报告（含 AI 教练建议）

## 冷启动流程

当此技能被触发时，按以下顺序操作：

### 1. 检查认证状态

```bash
ls ~/Projects/skills/PowerFun/.data/garmin_tokens/
```

- **token 目录存在且非空** → 已登录，跳过密码
- **token 目录不存在或为空** → 需要用户提供 Garmin Connect 邮箱和密码

### 2. 选择运行模式

```bash
cd ~/Projects/skills/PowerFun
source venv/bin/activate   # 项目 venv（Python 3.14），以下命令的 python3 均为 venv 内解释器
```

| 场景 | 命令 |
|------|------|
| 拉取最新数据 + 生成完整报告（日常使用） | `python3 main.py` |
| 仅生成报告（跳过 API 拉取） | `python3 main.py --load-parquet` |
| 深析某一天的数据 | `python3 main.py --load-parquet --deep-analyze "YYYY-MM-DD"` |
| 深析 + 体感备注 | `python3 main.py --load-parquet --deep-analyze "YYYY-MM-DD" --user-note "今天天气很热…"` |
| 首次使用（输入账号密码） | `python3 main.py --email YOUR_EMAIL --password YOUR_PASSWORD` |
| 仅生成 PDF（从已有 HTML 转换） | `python3 main.py --pdf-only` |
| 仅拉取数据（不生成报告） | `python3 main.py --dry-run` |

> **执行要求**：所有 PowerFun 命令必须通过 `exec` 执行，且必须设置 `yieldMs=180000`（3分钟），确保 LLM 请求期间进程保持前台运行、日志实时返回。不得使用 `background` 模式或默认 yield 时间。

> 注意：`--load-parquet` 必须有已存在的 parquet 数据文件
> (`~/Documents/Run/running_data.parquet`) 才能正常工作。首次使用或
> parquet 不存在时，必须先完整运行一次 `python3 main.py` 拉取数据。

## 心率和功率参数

已在 `src/config.py` 中配置（当前值在 SKILL.md 发布时为准）：

```python
USER_CONFIG = {
    'max_hr': 188,        # 最大心率（实测值）
    'resting_hr': 60,     # 静息心率（实测值）
}
```

如用户的实测心率和配置不一致，需先修改此配置再运行。

## 输出

| 文件 | 路径 |
|------|------|
| 综合报告 (HTML) | `~/Documents/Run/PowerFun.html` |
| 深析报告 (HTML) | `~/Documents/Run/PowerFun_Reports/run_analysis_YYYYMMDD.html` |
| 综合报告 (iCloud) | `~/Library/Mobile Documents/com~apple~CloudDocs/RUN/PowerFun.html` |
| 深析报告 (iCloud) | `~/Library/Mobile Documents/com~apple~CloudDocs/RUN/深度分析报告_YYYYMMDD.html` |
| 清洗数据 (CSV) | `~/Documents/Run/running_data_cleaned.csv` |

## 自定义体感备注

通过 `--user-note` 参数，可以在生成深度分析报告时附加跑者的主观体感描述。LLM 会结合客观数据和体感描述进行综合分析，让教练点评更贴合实际体验。

- 仅 `--deep-analyze` 单次模式支持
- 体感描述会被放在 prompt 最前方，作为数据分析的「帽子」
- 过长备注（>800字符）会自动截断
- 不传 `--user-note` 时行为与原来完全一致（向后兼容）

示例：
```bash
python3 main.py --load-parquet --deep-analyze "2026-07-10" \
  --user-note "今天天气很热、湿度很高，体感很不好，第13公里和第15公里为了控心率，我停下来走了一会。"
```

## ⚠️ LLM 故障处理

深度分析报告依赖 **Kimi k3 云端 API**（`api.kimi.com/coding/v1/chat/completions`）生成教练点评，API Key 从环境变量 `KIMI_API_KEY` 读取（自动加载 `~/.openclaw/.env`）。

**执行方式**：必须用 `exec` + `yieldMs=180000`，进程全程前台运行，不做 poll。

**故障行为**：LLM 调用失败**不会中断报告生成**，深析报告照常产出，仅 AI 点评区域显示降级文案：
- `（API Key 未配置，跳过 AI 分析）` — `KIMI_API_KEY` 未设置
- `（AI 分析调用失败: …）` — API 请求失败，日志中有 `LLM API 调用失败: <具体原因>`

**故障时**：向用户报告日志中的具体错误，等处理后再继续。不自行换模型或改配置。


