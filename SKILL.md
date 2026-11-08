---
name: powerfun
description: 跑步数据分析（PowerFun）——Garmin 跑步数据更新、单次深析、跑分查询、体感自述教练点评。触发词：跑步分析、跑分、更新跑步数据、深度分析、体感。项目位于 /Users/jarvis/Projects/KimiWork/PowerFun。
---

# PowerFun 跑步分析（KimiWork 入口）

项目根：`/Users/jarvis/Projects/KimiWork/PowerFun`，解释器：`.venv/bin/python`（Python 3.14）。
所有命令在项目根执行。确定性分析由 Python 内核完成，模型只解释已计算事实，不重新推导数值。

## 触发语义与命令

### “跑步分析，体感：……” / 单次深析（两阶段模型编排）

```bash
# 第一阶段：计算分析数据；缓存未命中时输出 LLM_REQUEST_REQUIRED=<path> 并退出
.venv/bin/python main.py --load-parquet --deep-analyze latest --user-note "<体感>" --prepare-llm

# KimiWork 会话读取 request.md，以当前模型生成六小节点评（含 <<<BRIEF>>>...<<<END>>>），
# 写入 .runtime/llm/<activity_id>/response.md —— 模型只解释事实，不重新计算指标

# 第二阶段：校验 response（activity_id/体感哈希/Prompt 版本、六小节顺序、BRIEF 块）并渲染
.venv/bin/python main.py --load-parquet --deep-analyze latest --user-note "<体感>" \
  --llm-response .runtime/llm/<activity_id>/response.md
```

- 缓存命中时第一阶段直接输出 `LLM_CACHE_HIT` 并渲染报告，无需模型。
- 校验失败会指出问题并退出：修正 response.md 后重跑第二阶段；不会写缓存、不会生成正式报告。
- 六小节标题（顺序固定）：🔥 本次跑步小结 / 🏃 强度与负荷分析 / ⚙️ 技术效率分析 / 📈 能力变化趋势 / 🔄 分圈表现分析 / 🛠️ 问题与修正。

### “跑分 2026-11-06”

`.venv/bin/python main.py --load-parquet --deep-analyze 2026-11-06`（日期、latest 或标题关键词；匹配多条会列出候选要求更精确条件）。

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
- LLM 缓存：`cache/llm/llm_<activity_id>.md`（frontmatter 含 user_note_hash / model / prompt_version）

## 禁止事项

- 不得读取 OpenClaw 环境（`~/.openclaw/.env`）、不得使用任何外部模型 API Key。
- 不得生成 PDF、不得安装 Playwright/Chromium。
- 不得访问、写入或清理任何 iCloud 文件或目录。
- 不得让模型替代 Python 重新计算指标；数值一律来自确定性分析内核。
- 不得创建定时任务；不得把数据、报告或凭据上传到公开仓库。
