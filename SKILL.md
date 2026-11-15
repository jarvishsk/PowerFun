---
name: powerfun
description: 跑步数据分析（PowerFun）——Garmin 跑步数据更新、综合报告、最新或指定日期深度分析、跑者自述教练点评。触发：“跑步数据分析”＋跑者自述（常规完整流程：拉数据＋综合报告＋最新深析）、“深度分析11月6日跑步数据”（只更新或补跑指定日期深析，不更新综合报告），以及跑步分析、跑分、更新跑步数据、深度分析、体感。指定日期深析未写日期时不得执行，先要求补充日期。项目位于 /Users/jarvis/Projects/KimiWork/PowerFun。
---

# PowerFun 跑步分析（KimiWork 入口）

项目根：`/Users/jarvis/Projects/KimiWork/PowerFun`，解释器：`.venv/bin/python`（Python 3.14）。
所有命令在项目根执行。确定性分析由 Python 内核完成，模型只解释已计算事实，不重新推导数值。

## 触发语义与命令

### “跑步数据分析”＋跑者自述 / 常规完整流程

每次跑完收到此提示时，必须完成“增量拉数 → 正式更新 → 最新一次深析 → 综合分析报告”全流程，不得只读取旧 parquet 生成报告。将关键词后的完整跑者自述原样填入 `<跑者自述>`。

```bash
# 1. 中国区 Garmin Personal API 隔离增量拉取
.venv/bin/python main.py --fetch-new --stage .runtime/garmin-validation

# 2. 检查 fetch_stats.json 的新增、更新、缺失字段和分圈结果；异常则停止。
#    对照通过后正式写入，自动备份原数据到 .runtime/backups/<时间戳>/
.venv/bin/python main.py --fetch-new

# 3. 确认最新活动是本次跑步。第一阶段：计算分析数据并准备最新深析；
#    缓存未命中时输出 LLM_REQUEST_REQUIRED=<path> 并退出
.venv/bin/python main.py --load-parquet --deep-analyze latest --user-note "<跑者自述>" --prepare-llm

# 4. 缓存未命中时，KimiWork 会话读取 request.md，以当前模型生成六小节点评
#    （含 <<<BRIEF>>>...<<<END>>>），写入 .runtime/llm/<activity_id>/response.md。
#    模型只解释事实，不重新计算指标。

# 5. 第二阶段：校验 response 并渲染最新深析和综合分析报告
.venv/bin/python main.py --load-parquet --deep-analyze latest --user-note "<跑者自述>" \
  --llm-response .runtime/llm/<activity_id>/response.md
```

- 缓存命中时第一阶段直接输出 `LLM_CACHE_HIT`，并生成最新深析和综合分析报告，无需模型。
- 命中条件为 activity_id、`prompt_version` 与 `analysis_hash`（当次结构化分析数据的 SHA-256）一致，且体感备注语义不变。人工课型、Pa:Hr 工作段或参照结果变化后旧缓存自动失效，须重新 prepare；旧格式缓存安全未命中。
- 若没有拉到本次活动，明确告知，不得把旧活动当作刚完成的跑步生成新点评。
- 校验失败会指出问题并退出：修正 response.md 后重跑第二阶段；不会写缓存、不会生成正式报告。
- 六小节标题（顺序固定）：🔥 本次跑步小结 / 🏃 强度与负荷分析 / ⚙️ 技术效率分析 / 📈 能力变化趋势 / 🔄 分圈表现分析 / 🛠️ 问题与修正。
- 统计证据语义（第二批，只由 Python 内核计算，点评不得自行推翻）：短期总样本 n≥5 才进入方向判断，且心率、配速、效率按各指标自身有效样本 n≥5 且当前值有效逐项放行（总样本达标但某指标有效样本不足或当前值缺失时，仅该指标降级为「样本有限」并保留描述，不给方向结论；3—4 次只描述数值与差值，<3 次数据不足）；长期跨温区/全部 LSD 同池只作表现描述（不得写能力进步/退步），同温区且逐月剔除方向稳定才允许能力 verdict——全量分类「稳定」也不例外，全量稳定但逐月剔除方向不稳时不得输出确定「稳定」，应为「趋势待确认」；同比每指标 ≥3 有效样本才有中位数、≥3 有效月份（普通课型每月≥2、LSD 每月≥1）才有月斜率；历史百分位有效效率 n≥10 才排名。

### “深度分析11月6日跑步数据” / 只更新或补跑指定日期深析

只生成该日深析报告，不得生成或更新综合报告 `PowerFun.html`。将自然语言日期转换为 `YYYY-MM-DD`，并始终使用 `--deep-only`：

```bash
# 例如“深度分析11月6日跑步数据”在当前语境下映射为 2026-11-06
.venv/bin/python main.py --load-parquet --deep-analyze 2026-11-06 --deep-only

# 若输出 LLM_REQUEST_REQUIRED，由当前 KimiWork 模型生成 response.md 后执行：
.venv/bin/python main.py --load-parquet --deep-analyze 2026-11-06 --deep-only \
  --llm-response .runtime/llm/<activity_id>/response.md
```

- 未写年份但已写月日时，在现有数据范围内选择最近的一个该月日；语境明确指向其他年份时使用对应年份。
- 完全未写日期（如“深度分析跑步数据”）时，不得执行任何数据更新或报告命令，不得默认 `latest`；先要求补充日期。
- 同日匹配多次活动时列出候选并要求更精确条件，不得自行猜测。
- “跑分 2026-11-06”保留为同义入口，同样只生成指定日期深析。

### “更新跑步数据并生成报告”

```bash
# 增量拉取（中国区 Garmin Personal API），先写隔离目录验证
.venv/bin/python main.py --fetch-new --stage .runtime/garmin-validation
# 字段与分圈对照通过后，正式写入（自动备份原数据到 .runtime/backups/<时间戳>/）
.venv/bin/python main.py --fetch-new
# 再生成报告（最新深析 + 综合报告）
.venv/bin/python main.py --load-parquet
```

在线步骤前置条件：`.secrets/garmin-personal-api-key`（中国区 Personal API Key，权限 600）。
密钥文件不存在时停止在线步骤，请老板在本机写入，不要在聊天中发送 Key。

## 产物位置

- 综合报告：`reports/PowerFun.html`（10 个图表，本地静态资源 `reports/assets/`）
- 深析报告：`reports/PowerFun_Reports/run_analysis_*.html`
- LLM 缓存：`cache/llm/llm_<activity_id>.md`（frontmatter 含 user_note_hash / model / prompt_version / analysis_hash）；命中需四者一致，旧三行格式缓存安全未命中（不报错、不删除）

## 人工课型覆盖（5.0 第一批）

`config/activity_overrides.toml` 以人工训练目的把指定活动覆盖为 `tempo_run`（节奏跑）或
`intensity_run`（间歇跑），可选 `pa_hr_laps = [起, 止]` 指定 Pa:Hr 人工工作段（两端包含）：

```toml
schema_version = 1

[activities."659451010"]
category = "tempo_run"
pa_hr_laps = [4, 9]
```

- 覆盖只在报告入口生效：每行保留 `category_auto`（原自动分类）与 `category_source`（auto/manual），不回写 parquet，自动分类逻辑不变。
- 节奏跑只按 `pa_hr_laps` 计算 Pa:Hr；缺段或选段失败不计算且不回退整场。间歇跑默认不计算整场 Pa:Hr，明确指定连续稳态段才计算该段。普通课型整场口径不变。
- 配置非法（无法解析、category 不允许、段落非两个正整数或起点大于终点）时报告前报错停止；配置中不存在的 activity_id 只警告不阻断。

## 禁止事项

- 不得读取 OpenClaw 环境（`~/.openclaw/.env`）、不得使用任何外部模型 API Key。
- 不得生成 PDF、不得安装 Playwright/Chromium。
- 不得访问、写入或清理任何 iCloud 文件或目录。
- 不得让模型替代 Python 重新计算指标；数值一律来自确定性分析内核。
- 不得创建定时任务；不得把数据、报告或凭据上传到公开仓库。
