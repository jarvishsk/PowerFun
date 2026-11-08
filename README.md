# 🏃 PowerFun - 跑步数据分析（KimiWork 版）

> Garmin 跑步数据获取 + 确定性分析内核 + KimiWork 教练点评 + 本地 HTML 报告

本项目已从 OpenClaw 平台迁移至 KimiWork：保留经过验证的确定性分析内核，
模型编排改为 KimiWork 两阶段流程（prepare → 当前模型 → response → render），
报告资源全部本地化，取消 PDF 与 iCloud 同步。

## 功能特性

- **📊 智能拉取**: Garmin Connect 中国区 Personal API 增量更新，按 activity_id 去重、标题保护
- **🧹 数据清洗**: 完整的字段映射、类型转换、异常检测（Python 内核，不让模型算数）
- **❤️ 心率区间**: Karvonen HRR（心率储备法）Z1-Z5 五区间，使用 Garmin 原生 `hrTimeInZone_1~5`
- **⏱️ 跑分分类**: 轻松跑/节奏跑/LSD/赛事等自动分类与历史对比（同温区基线、180 天全量回归）
- **📈 可视化**: 10 个 Plotly 交互式图表，报告资源本地引用（无 CDN 依赖）
- **🔍 深度分析**: 单次跑步深析（分圈 P20-P80、Pa:Hr 有氧解耦、确定性问题清单）
- **🤖 教练点评**: 由 KimiWork 当前模型基于已计算的 analysis_data 生成，缓存复用（prompt_version 失效机制）

## 快速开始

```bash
# 安装（Python 3.14）
/opt/homebrew/bin/python3.14 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 增量更新跑步数据（中国区 Personal API，需 .secrets/garmin-personal-api-key）
.venv/bin/python main.py --fetch-new --stage .runtime/garmin-validation   # 隔离验证
.venv/bin/python main.py --fetch-new                                       # 正式写入（自动备份）

# 生成报告（综合 + 最新深析）
.venv/bin/python main.py --load-parquet

# 单次深析（两阶段：先 prepare，模型生成 response 后 render）
.venv/bin/python main.py --load-parquet --deep-analyze latest --user-note "<体感>" --prepare-llm
.venv/bin/python main.py --load-parquet --deep-analyze latest --user-note "<体感>" \
  --llm-response .runtime/llm/<activity_id>/response.md
```

详细触发语义见 [SKILL.md](SKILL.md)。回归测试：`.venv/bin/python -m pytest tests/`。

## 目录结构

```text
main.py / src/            # 分析内核与薄适配
tests/                    # 数据完整性 + 确定性场景 + 报告测试
data/                     # 主表 parquet、原始活动缓存、分圈、拉取状态（Git 排除）
reports/                  # 综合报告 + 深析报告 + 本地静态资源 assets/（Git 排除）
cache/llm/                # 教练点评缓存（Git 排除）
docs/                     # 经验、跑者画像、训练计划、外部 PRD
.secrets/                 # Garmin Personal API Key / bearer token（Git 排除）
.runtime/                 # 临时请求、隔离验证、备份（Git 排除）
```
