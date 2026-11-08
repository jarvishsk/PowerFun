# PowerFun Token 优化 PRD

- **日期**：2026-09-13
- **项目**：`~/Projects/skills/PowerFun`
- **目标**：降低单次跑步数据分析的 token 消耗（实施讨论稿中的第 ①③⑤⑥ 项）
- **不做**：换模型（GLM-4.7-Flash 当前不可用，见下文「背景确认」）

## 背景确认（主 Agent 已实测，直接采信）

1. **GLM-4.7-Flash 不可用**：`ZHIPU_API_KEY` 存在于 `~/.openclaw/.env`（49 字符），端点 `open.bigmodel.cn/api/paas/v4/chat/completions` 可达，但 4 次实测全部 429（`1302 账户速率限制` / `1305 模型访问量过大`）。**结论：本次不换模型**，保持 `kimi-for-coding` 不变。
2. **现状每次深析 2 次 LLM 调用**：
   - `DeepRunAnalyzer._generate_brief_summary`（deep_analyzer.py:75）— 独立的 100 字简报调用，`max_tokens=2000`
   - `LLMReportGenerator.generate` → `_build_prompt` + `_call_api`（deep_analyzer.py:1149/1171/1350）— 主点评调用
3. **brief_summary 消费方**：仅 `src/analysis_report.py:174-175, 615`（深析报告模板），主综合报告不用。
4. **prompt 体积**：`_build_prompt` 的指令部分约占 40%，且格式要求逐条重复（6 个小标题各写一遍格式 + 末尾「要求」段复述）。
5. **LLM 输出契约**（瘦身时不可破坏）：
   - 6 个 `## emoji 标题` 小节：🔥 本次跑步小结 / 🏃 强度与负荷分析 / ⚙️ 技术效率分析 / 📈 能力变化趋势 / 🔄 分圈表现分析 / 🎯 改进建议
   - 分圈段内 `- **前段（X-Y km）**：` 加粗列表格式
   - 改进建议编号列表 `1. **【最高优先】标题**：内容`
   - 总字数 ≤1500 字
6. **现有缓存/文件命名**：深析报告 `~/Documents/Run/PowerFun_Reports/run_analysis_{YYYYMMDD}_{activity_id}.html`。

## 需求

### ① 合并两次 LLM 调用为一次

- 删除 `_generate_brief_summary` 的独立 LLM 调用。
- 在 `_build_prompt` 输出要求末尾追加第 7 项：在报告最后输出一行 `<<<BRIEF>>>100字以内的简要总结（突出训练重点和特点，语言专业简洁，80-120字）<<<END>>>` 包裹的简报。
- `LLMReportGenerator.generate()` 解析该分隔块：`llm_report` 去掉该块，简报存入 `analysis_data['brief_summary']`（由 main.py 在 `generate()` 返回后回填，analysis_report.py 消费方不变）。
- 解析失败（模型没按格式输出）时降级：brief_summary 留空字符串，llm_report 用全文，不报错、不中断。
- 单次模式（`--deep-analyze`）与日常全量模式（main.py 默认流程，main.py:536 附近同样调用 analyze）两条路径都要生效。

### ③ Prompt 瘦身（目标：指令部分 -30% 以上字符）

- 重构 `_build_prompt` 的「请生成包含以下内容」与「要求」两段：
  - 6 个小标题的格式约定合并为一条统一规则（如「每个小节标题格式为 `## emoji 空格 标题`，全篇共 6 个小节，标题文本必须与下列清单一致」+ 清单）。
  - 删除重复表述：分圈格式和改进建议在「内容要求」里详述一次即可，「要求」段不再复述。
  - 保留全部输出契约（见背景确认第 5 条）和 `user_note` 前置逻辑、气温/Pa:Hr 段、分圈表格、历史对比段的**数据内容不动**。
- 在 `generate()` 中 log 一次 `prompt 字符数`，便于验收对比。

### ⑤ 同日复用缓存（跳过 LLM 调用）

- 深析 LLM 输出落盘缓存：`~/Documents/Run/PowerFun_Reports/cache/llm_{activity_id}.md`，内容为 `llm_report` 全文 + 文件内 frontmatter 两行（`user_note_hash:`、`model:`）。
- `--deep-analyze DATE` 命中条件：缓存文件存在 **且** `--force` 未传 **且**（本次未传 `--user-note` 或 hash 与缓存一致）→ 跳过 LLM 调用，直接读缓存生成 HTML，log 打印「复用 LLM 缓存，跳过 API 调用」。
- 新增 `--force` 参数（仅对 deep-analyze 生效）：强制重新调用 LLM 并覆盖缓存。
- 无 `activity_id` 的跑次（activity_id 为空/unknown/None）不缓存，行为同现状。
- LLM 调用失败（降级文案）时不写缓存。

### ⑥ `--deep-analyze latest` + SKILL.md 精简

- main.py：`--deep-analyze` 接受字面量 `latest`，解析为 parquet 中最新一次跑步的 `date`（取 `df['date'].max()` 对应行）。`--deep-analyze-all` 路径不受影响。
- SKILL.md 从 5.3KB 精简到 ~2KB：
  - 保留：触发词、运行模式命令表、`--user-note` 说明、输出文件表、LLM 故障降级说明（压缩为 3 行）、心率参数配置说明。
  - 删除：重复示例（体感备注示例、首次使用示例中与命令表重复的部分）、与命令表冗余的文字展开、冷启动流程细节（token 检查一行带过）。
  - 触发词补充：`跑步分析` 类触发时主 Agent 直接跑 `python3 main.py --load-parquet --deep-analyze latest --user-note "<体感>"`，**不再手动查日期、不打印数据行**（此条写进 SKILL.md 顶部「执行约定」）。

## 验收标准

1. **基准数据**：先记录修改前 prompt 字符数（跑一次现有代码，或从代码静态估算并在报告中注明）。
2. **功能回归**：`python3 main.py --load-parquet --deep-analyze 2026-09-12 --user-note "体感舒适"` 正常产出 HTML，6 个小节齐全，分圈/建议格式符合契约，brief_summary 非空且出现在报告中。
3. **缓存命中**：紧接着再跑一次同命令（不加 --force）→ 日志出现「复用 LLM 缓存」，且 LLM 无调用延迟（秒回）；产出 HTML 正常。
4. **--force**：加 `--force` 重跑 → 重新调用 LLM，缓存被覆盖。
5. **user-note 失效**：改不同 `--user-note` 重跑 → 缓存不命中，重新调用 LLM。
6. **瘦身效果**：新 prompt 字符数较基准 -30% 以上（对比 log 中的 prompt 字符数）。
7. **latest**：`--deep-analyze latest` 正确解析到 2026-09-12 那次跑步。
8. **日常模式回归**：`python3 main.py --load-parquet` 正常产出主报告，brief_summary 正常出现在深析链路（若日常模式也触发 deep analyze）。
9. 所有验证命令用项目 venv：`cd ~/Projects/skills/PowerFun && source venv/bin/activate`。

## 约束

- 最小改动：只碰 `main.py`、`src/deep_analyzer.py`、`src/analysis_report.py`（仅必要时）、`SKILL.md`。
- 禁止 `or` 做数值 fallback（AGENTS.md Python 规则）。
- LLM 失败降级行为与现状一致（不中断报告）。
- 不改图表、不改 HTML 模板样式。
