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
- **🏷️ 人工课型覆盖**: `config/activity_overrides.toml` 以人工训练目的覆盖节奏跑/间歇跑（保留 `category_auto`/`category_source`，不回写 parquet）
- **📏 统计证据门槛**: 证据等级只由 Python 内核计算（`directional`/`descriptive`/`insufficient`）——短期总样本 n≥5 才进入方向判断，且心率、配速、效率各自要求有效样本 n≥5 且当前值有效才给该项方向结论（总样本达标但某指标不足时仅该指标降级为「样本有限」并保留描述，其他达标指标不受影响；3—4 仅作描述、<3 数据不足）；长期跨温池只作表现描述不给能力 verdict，同温池方向判断须逐月剔除方向稳定支持，全量分类「稳定」也不例外——全量稳定但逐月剔除方向不稳时同样降级为「趋势待确认」；同比按指标 ≥3 有效样本与 ≥3 有效月份出中位数/月斜率；历史百分位按有效效率 n≥10 排名
- **📈 可视化**: 10 个 Plotly 交互式图表，报告资源本地引用（无 CDN 依赖）
- **🔍 深度分析**: 单次跑步深析（分圈 P20-P80、Pa:Hr 有氧解耦、确定性问题清单）；Pa:Hr 双轨口径——普通课型整场、节奏跑只算人工工作段、间歇跑默认不适用，负向漂移（≤ -5%）正确触发
- **🤖 教练点评**: 由 KimiWork 当前模型基于已计算的 analysis_data 生成，缓存复用（prompt_version + analysis_hash 双重失效机制）

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

5.0 审查与分批执行入口：[总体优化方案与 PRD 索引](docs/prd/powerfun-5.0-master-plan.md)。

## 目录结构

```text
main.py / src/            # 分析内核与薄适配
config/activity_overrides.toml  # 人工课型覆盖（节奏跑/间歇跑，Git 跟踪）
tests/                    # 数据完整性 + 确定性场景 + 报告测试
data/                     # 主表 parquet、原始活动缓存、分圈、拉取状态（Git 排除）
reports/                  # 综合报告 + 深析报告 + 本地静态资源 assets/（Git 排除）
cache/llm/                # 教练点评缓存（Git 排除）
docs/                     # 经验、跑者画像、训练计划、外部 PRD
.secrets/                 # Garmin Personal API Key / bearer token（Git 排除）
.runtime/                 # 临时请求、隔离验证、备份（Git 排除）
```
