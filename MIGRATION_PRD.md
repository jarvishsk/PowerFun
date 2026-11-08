# PowerFun 迁移至 KimiWork 实施 PRD（执行版）

- 日期：2026-11-08
- 状态：已确认方案，可交由执行会话实施
- 执行工作区：`/Users/jarvis/Projects/KimiWork/PowerFun`
- 原项目（只读）：`/Users/jarvis/Projects/skills/PowerFun`
- 代码基线：`main` 分支 commit `c025822`
- 核心原则：**保留经过验证的确定性分析内核，替换平台接入、模型编排和报告交付方式**

---

## 1. 已确认的决策

1. 保留数据清洗、跑步分类、历史对比、长短期趋势、分圈分析、Pa:Hr、确定性问题探测等 Python 分析内核，不让模型重新计算指标。
2. 保留原 Prompt、六小节教练点评结构、`<<<BRIEF>>>` 简报协议和 `LLM_PROMPT_VERSION = 12`。
3. 取消 Python 调用外部模型 API，改由 KimiWork 当前模型生成教练点评；不需要模型 API Key。
4. 沿用 Plotly、Jinja2 和现有 HTML 报告，不重写为 React、Web 应用或 Canvas。
5. Plotly、jQuery、DataTables 等报告资源改为本地引用，取消 CDN 依赖。
6. **不迁移、不写入、不清理任何 iCloud 文件或目录。** 原 iCloud 内容由老板自行处理。
7. **取消 PDF 全流程。** 不迁移 PDF 功能，不保留 `--pdf-only`，不安装 Playwright/Chromium，不生成 PDF。
8. Garmin 优先改用官方 Personal API；使用中国区账号和中国区 Key，不跨区回退。
9. 所有正式数据、缓存和报告统一留在当前工作区，组织清晰，不依赖原 OpenClaw 目录。
10. 原项目只读保留，不删除、不格式化、不修改远端；目标端默认不 push。
11. 不创建定时任务。连续两次手动分析验收通过后，才将 KimiWork 作为主要入口。

---

## 2. 已核实的现状与研究资产

### 2.1 原项目基线

- 原项目 HEAD 为 `c025822`，工作区干净。
- Git 标签：v1.0、v2.0、v2.1、v3.0、v4.1。
- 原项目无自动化测试，必须先把历史验收场景固化为测试，再做适配。
- Python 3.14 环境下，原依赖已实际安装成功，`main.py` 可导入。
- 隔离离线回归已成功：读取 150 × 62 主表，生成 10 个综合图表及最新深析报告，并命中现有 LLM 缓存。
- 最新深析 HTML 除生成时间外与原报告一致，证明保留内核的路线可行。

### 2.2 数据资产

| 资产 | 已核实数量 | 说明 |
|---|---:|---|
| 原始活动缓存 | 153 次 | 保留全部原始记录 |
| 分析主表 | 150 次、62 列 | 150 个唯一 activity_id |
| 分圈数据 | 2,740 行 | 覆盖全部 150 次分析活动 |
| 历史深析 HTML | 95 份 | 原样迁移，不批量重建 |
| LLM 缓存 | 22 份 | 保留历史模型文字及 prompt_version |
| 外部 PowerFun PRD | 16 份 | 包含大小写不同的文件名 |

主表比原始缓存少 3 次，均为既定过滤规则：

- 1 次 138.85 km 超长记录；
- 2 次标题含“间歇跑”的记录。

这不是迁移丢数，不得为追求数量相等而取消过滤。

### 2.3 工作区内已有研究副本

执行会话可复用以下只读研究资产，避免重复复制：

```text
.migration-research/source/          # 原项目研究副本，含 .git 和非敏感缓存
.migration-research/assets/data/     # running_data.parquet、running_data_cleaned.csv
.migration-research/assets/reports/  # 综合报告、95 份深析报告、22 份 LLM 缓存
.migration-research/assets/prd/      # 外部 16 份 PowerFun PRD
.migration-research/venv/            # 研究依赖环境，不直接作为正式环境
.migration-research/offline-output/  # 研究回归输出，不作为正式报告
```

`.migration-research/assets/icloud/` 仅是前期研究复制内容，**不得用于正式迁移**。正式迁移完成后可随整个研究临时目录一并清理；此清理只针对工作区研究副本，绝不触碰真实 iCloud 目录。

---

## 3. 目标与非目标

### 3.1 目标

迁移完成后，老板可在 KimiWork 中直接提出：

- “跑步分析，体感：……”
- “跑分 2026-11-06”
- “更新跑步数据并生成报告”

系统应完成 Garmin 增量更新或本地数据读取、确定性分析、KimiWork 教练点评、缓存复用和 HTML 报告生成，并保持既有分析口径。

### 3.2 非目标

- 不重新设计训练算法和指标口径。
- 不让模型替代 Python 做数值计算。
- 不重写图表体系或报告视觉体系。
- 不生成 PDF，不同步 iCloud。
- 不迁移 OpenClaw 的模型 Key、Garmin SSO token 或其他凭据。
- 不全量重拉 Garmin 历史数据。
- 不创建 cron 或其他自动任务。
- 不上传原始数据、报告、个人资料或凭据到公开仓库。

---

## 4. 目标目录约定

```text
PowerFun/
├── MIGRATION_PRD.md
├── main.py
├── src/                         # 保留的分析内核及薄适配
├── tests/                       # 新增确定性回归测试
├── requirements.txt             # 精简后的直接依赖
├── requirements.lock            # 验收环境锁定版本
├── data/
│   ├── running_data.parquet     # 分析主表，唯一报告数据源
│   ├── running_data_cleaned.csv
│   ├── activities_cache.json    # 原始活动缓存
│   ├── lap_data.parquet
│   └── last_fetch.json
├── reports/
│   ├── PowerFun.html
│   ├── assets/                  # 本地 Plotly 等共享资源
│   └── PowerFun_Reports/
│       └── run_analysis_*.html
├── cache/
│   └── llm/
│       └── llm_<activity_id>.md
├── docs/
│   ├── lessons.md
│   ├── runner-profile.md
│   ├── training/
│   └── prd/
│       └── external/            # 外部 16 份 PRD
├── static/                      # 原项目已有静态资源
├── .runtime/                    # 临时请求、在线验证和备份；Git 排除
├── .secrets/                    # Garmin Key/token；权限隔离、Git 排除
├── .venv/                       # 正式环境；Git 排除
└── SKILL.md                     # KimiWork 个人技能入口说明
```

既有 `docs/` 文档保持原路径；只将外部 16 份 PRD 放入 `docs/prd/external/`，避免无意义的大规模文档改路径。

正式 `data/`、`reports/`、`cache/` 是本地持久资产，但默认不入 Git，不上传公开仓库。

---

## 5. 实施要求

### Step 0：保护边界与基线检查

1. 不修改原项目和真实 iCloud 目录。
2. 确认目标根目录只有本 PRD、研究临时目录及执行会话明确产生的文件；发现其他文件先报告，不覆盖。
3. 目标目录位于 `/Users/jarvis/Projects/.git` 之下。目标项目应建立独立 Git 仓库，不提交到父仓库。
4. 在任何 `git add` 前，将以下路径加入目标 `.gitignore`：

```gitignore
.migration-research/
.runtime/
.secrets/
.venv/
data/
reports/
cache/
```

5. 扫描目标文件和 Git 当前版本，确认不存在 OpenClaw `.env`、模型 Key、Garmin SSO token 或 Personal API Key。
6. 记录源数据文件数量、大小和 SHA-256，供迁移后核对。

### Step 1：导入代码与正式资产

1. 从原项目本地 Git 仓库导入 `c025822`，保留 main 可达历史和全部既有标签；目标分支使用 `migration/kimiwork`。
2. 不修改原项目远端配置，目标端不 push。
3. 按第 4 节目录复制正式资产：
   - 主表、CSV：来自 `.migration-research/assets/data/`；
   - 原始活动、分圈、拉取状态：来自 `.migration-research/source/.data/`；
   - 综合及深析 HTML：来自 `.migration-research/assets/reports/`；
   - LLM 缓存迁移到 `cache/llm/`，不再放在报告目录；
   - 外部 16 份 PRD 复制到 `docs/prd/external/`。
4. 历史 HTML 原样保留，不批量重新生成。
5. 不复制 `.migration-research/assets/icloud/` 中任何内容。
6. 使用 `/opt/homebrew/bin/python3.14` 创建目标 `.venv`，不要使用默认的 Python 3.12。

### Step 2：配置与路径收拢

1. 默认项目根目录、数据目录、报告目录、LLM 缓存目录均由代码位置计算，不依赖用户 home 下的旧项目路径。
2. 默认路径对应第 4 节；保留 `--output` 作为隔离验收输出覆盖项。
3. 删除对 `~/.openclaw/.env`、OpenClaw workspace、`KIMI_API_KEY` 的读取。
4. 删除 `Path.home()/Documents/Run` 和 iCloud 路径配置。
5. 任何离线命令都不得访问 Garmin、外部模型或工作区外文件。

### Step 3：KimiWork 模型编排适配

#### 3.1 保留内容

- 保留 `DeepRunAnalyzer` 和确定性 `analysis_data`。
- 保留 `LLMReportGenerator._build_prompt()` 的 Prompt 内容和数据格式化口径。
- 保留 `_parse_brief()`、`user_note` 哈希和 Prompt 版本失效机制。
- `LLM_PROMPT_VERSION` 保持 12；仅更换执行平台，不因此升版。

#### 3.2 删除内容

- 删除模型 HTTP 请求、API Key 配置、模型重试和外部模型降级文案。
- 删除 `python-dotenv` 使用及 OpenClaw 环境读取。
- 不得自动改用其他外部模型或旧 OpenClaw Key。

#### 3.3 必须实现的接口

保留现有 `--deep-analyze`、`latest`、`--user-note`、`--force` 语义，新增：

```bash
# 第一阶段：计算分析数据并准备模型请求
python main.py --load-parquet --deep-analyze latest \
  --user-note "<体感>" --prepare-llm

# 第二阶段：使用 KimiWork 已生成的回复渲染报告
python main.py --load-parquet --deep-analyze latest \
  --user-note "<体感>" \
  --llm-response .runtime/llm/<activity_id>/response.md
```

第一阶段行为：

- 有效缓存命中：输出 `LLM_CACHE_HIT`，可直接进入报告生成，不创建模型请求。
- 缓存未命中或 `--force`：输出 `LLM_REQUEST_REQUIRED=<path>`，将原 Prompt 写入 `.runtime/llm/<activity_id>/request.md`，不得调用外部模型，不得用空点评生成正式报告。
- 请求目录同时记录 activity_id、user_note 哈希和 prompt_version，防止响应错配。

KimiWork 执行会话读取 request 后，以当前模型生成回复，写入对应 `response.md`。模型只解释已计算事实，不重新推导数值。

第二阶段行为：

- 校验 activity_id 和请求上下文一致。
- 校验六个标题完整且顺序正确：
  1. `## 🔥 本次跑步小结`
  2. `## 🏃 强度与负荷分析`
  3. `## ⚙️ 技术效率分析`
  4. `## 📈 能力变化趋势`
  5. `## 🔄 分圈表现分析`
  6. `## 🛠️ 问题与修正`
- 校验存在 `<<<BRIEF>>>...<<<END>>>`；正文与简报的解析沿用原逻辑。
- 校验失败：指出问题，由 KimiWork 修正 response，不写缓存、不生成正式报告。
- 校验成功：写入 `cache/llm/llm_<activity_id>.md`，渲染深析及综合 HTML。
- 新缓存 `model` 标记为 `KimiWork`；历史缓存原样保留，不伪造具体模型版本。
- 第二次相同活动、相同体感和 Prompt 版本运行必须命中缓存，不再请求模型。

### Step 4：报告与静态资源适配

1. 保留 `ChartGenerator`、综合报告和深析报告结构。
2. 综合报告仍应生成 10 个图表；深析保留分圈 P20–P80、Pa:Hr 等既有图表。
3. 将模板中的 Plotly、jQuery、DataTables CDN 改为 `reports/assets/` 本地共享资源。
4. 确保移动或复制整个 `reports/` 目录后，相对资源链接仍有效。
5. 删除自动复制 iCloud 的调用、配置和工具函数。
6. 删除 `--pdf-only` 参数及其执行分支，移除 `src/pdf_generator.py` 的当前版本代码；Git 历史自然保留旧实现。
7. 不安装 Playwright，不生成任何 PDF，不保留 PDF 触发说明。
8. `SKILL.md` 和 README 只描述 HTML 报告，不再出现 iCloud、PDF 或 OpenClaw 指令。

### Step 5：Garmin Personal API 接入

#### 5.1 凭据安全

- 使用中国区 Personal API Key，不使用国际区端点代替。
- Key 文件：`.secrets/garmin-personal-api-key`。
- Bearer token 缓存：`.secrets/garmin-personal-bearer-token.json`。
- `.secrets/` 权限为 `700`，两个文件权限为 `600`。
- Key 不得写入 PRD、代码、Git、日志、命令参数或完成报告。
- 老板已在聊天中提供过一次 Key，执行会话不得复述或再次打印。该 Key 应在验收后轮换；如老板已重新生成，以本机密钥文件中的新 Key 为准。
- 若密钥文件不存在，暂停在线步骤并请求老板在本机写入，不要求在聊天中发送。

#### 5.2 技术路线

1. 优先使用 Garmin 官方 `garmin-connect-personal-api-python` 客户端。
2. 中国区 token 和 API 基础地址使用 `personal.connectapi.garmin.cn`；如官方客户端当前版本不支持区域配置，只在本项目实现薄的 token exchange 和 GET 封装，不修改第三方包，不回退国际区。
3. Personal Key 只用于换取 bearer token；token 最长 24 小时，过期后用 Key 重新获取。
4. 复用现有活动列表、活动详情和分圈字段映射，数据清洗层不因认证方式改变而重写。
5. 分圈优先验证现有 `/activity-service/activity/{id}/laps` 是否可用；不可用时再依次评估活动详情 splits、原始 FIT。未经字段对照不得直接替换分圈口径。
6. 不迁移原 `garmin_tokens/`，不读取 Garmin 账号密码。
7. 在线验收完成前保留原抓取实现作代码级回退；不得自动回退 SSO 并提示输入密码。Personal API 验证失败应停止在线切换并报告。

#### 5.3 必须实现的隔离接口

```bash
# 仅验证认证、资料和单次活动读取，不改正式数据
python main.py --garmin-check

# 拉取新增数据，但全部写入隔离目录，不改正式 data/
python main.py --fetch-new --stage .runtime/garmin-validation
```

`--garmin-check` 只能写凭据缓存和非敏感日志。

`--fetch-new --stage` 必须：

- 从迁移的 `last_fetch.json` 继续增量拉取，不执行全量回填；
- 按 activity_id 去重；
- 保留标题保护规则；
- 将原始响应、处理结果和分圈写入 stage；
- 输出新增、更新、重复、缺失字段和分圈数量统计；
- 不覆盖正式 `data/`。

只有在字段及分圈对照通过后，普通 `python main.py` 才可写正式数据。首次正式写入前，将现有数据文件备份到 `.runtime/backups/<timestamp>/`。

### Step 6：依赖精简

正式环境只保留实际使用的直接依赖，预计包括：

- pandas、numpy、pyarrow；
- plotly、jinja2、python-dateutil；
- Garmin Personal API 官方客户端及其必要依赖。

处理要求：

- 删除 Playwright、python-dotenv。
- Personal API 验收通过后删除活跃流程不再使用的 garth；失败时不得擅自更换认证方案。
- 不因研究使用 DuckDB 而将其加入正式依赖。
- 生成 `requirements.lock`，锁定实际验收版本。
- 至少执行 `compileall` 和真实导入检查，不能只检查语法。

### Step 7：KimiWork 个人技能

1. `SKILL.md` 只保留 name、description 两个 frontmatter 字段，正文聚焦执行流程。
2. 描述覆盖“跑步分析、跑分、Garmin 跑步数据更新、单次深析、体感自述”等触发语义。
3. 明确两阶段模型编排：prepare → 当前 KimiWork 模型 → response → render。
4. 明确不得读取 OpenClaw 环境、不得调用外部模型、不得生成 PDF、不得访问 iCloud。
5. 代码和数据仍留当前工作区，个人技能只保存简洁入口说明，不复制整个项目。
6. 最后注册并验证个人技能可被发现；未完成实际触发验证前，不得宣称迁移完成。

---

## 6. 回归测试要求

原项目没有测试目录，本次先补最小但有效的测试集。

### 6.1 数据完整性测试

- 原始活动缓存 153 次。
- 主表 150 行、150 个唯一 activity_id、62 列。
- 分圈 2,740 行、覆盖 150 个 activity_id。
- 三个过滤记录继续缺席主表，且缺席原因符合原规则。
- 历史深析 HTML 95 份、LLM 缓存 22 份、外部 PRD 16 份。
- 数据时间范围为 2025-10-24 至 2026-11-06，在线增量后只允许多出已验证的新活动。

### 6.2 确定性场景测试

至少覆盖：

1. `2026-11-06`：携带附录原体感，六小节完整，无“预期配速”旧字样，无机械“关键发现”区块。
2. `2026-09-24`：热天轻松跑，既有结论不回归。
3. `2026-10-22`：凉爽天轻松跑，长期趋势使用 180 天全量回归，不得错误显示“样本不足”。
4. `2026-10-25`：30.13 km LSD，显示“全部 LSD 同池对比”，长期回归月度护栏为 ≥1/月。
5. 历史对比不得使用目标活动之后的数据。
6. `max_hr=188`、`resting_hr=60` 及 Karvonen HRR 口径不得改变。

测试以结构化 `analysis_data`、指标和关键文案为主，不要求不同 Plotly 版本的 HTML 字节完全一致。

### 6.3 报告测试

- 综合报告生成 10 个非空图表。
- 深析六小节及 BRIEF 完整。
- 本地资源存在，HTML 无 Plotly、jQuery、DataTables CDN 地址。
- 历史深析链接有效。
- 全流程无 iCloud 写入、无 PDF 输出。
- 输出只位于工作区指定目录。

---

## 7. 总体验收

### A 组：离线验收

1. Python 3.14 正式环境安装、compileall、导入检查全部通过。
2. 数据完整性测试全部通过。
3. 四个确定性场景全部通过。
4. 使用历史有效缓存可生成最新深析和综合报告，10 个图表正常。
5. 删除隔离测试中的一份缓存后，第一阶段产生 `LLM_REQUEST_REQUIRED`；KimiWork 生成 response 后成功渲染，第二次运行输出 `LLM_CACHE_HIT`。
6. 非六小节、缺 BRIEF、错 activity_id 的 response 均被拒绝，且不写缓存。
7. 检查代码和运行日志，无 OpenClaw `.env`、外部模型 API、iCloud、PDF 或工作区外数据路径依赖。

### B 组：Garmin 在线验收

1. 中国区 Personal API 换取 token 和资料读取成功。
2. 活动列表关键字段与原缓存一致，至少覆盖心率区间、功率、步频、VR、GCT、温度、训练效果和负荷。
3. 单次活动详情与分圈完整，分圈条数及关键值与既有缓存一致。
4. 增量拉取无异常全量重拉、无重复 activity_id，标题保护不回归。
5. stage 与正式数据的对照经检查通过后，才允许首次正式写入。
6. 正式写入后可再次生成报告，新增活动只增加一次。

任一 Personal API 关键能力不满足：保留离线成果，停止在线切换，不自动回退账号密码方式。

### C 组：KimiWork 使用验收

1. “跑步分析，体感：……”能完成 prepare → 当前模型 → response → HTML。
2. “跑分 2026-11-06”能正确匹配唯一活动；同日多次活动时应要求更精确条件。
3. “更新跑步数据并生成报告”只走已验收的中国区 Personal API 增量流程。
4. 连续两次手动端到端分析通过，第二次验证缓存复用。
5. 个人技能在新会话中可发现并正确触发。
6. 未创建任何定时任务。

---

## 8. 回滚与清理

1. 任一关键验收失败，停止切换，原项目继续作为主要入口。
2. 不删除或修改原项目，不删除真实 iCloud 内容。
3. 正式数据首次在线写入前的备份位于 `.runtime/backups/`，异常时只恢复工作区数据，不触碰外部目录。
4. 新模型 response 校验失败时，保留历史缓存，不覆盖旧结果。
5. 全部验收通过后，可删除工作区 `.migration-research/` 临时目录及研究 venv、研究输出；不得误删正式 `data/`、`reports/`、`cache/`。
6. Garmin Key 在在线验收后由老板撤销并重新生成；新 Key 仍只写 `.secrets/`，不进入聊天或 Git。

---

## 9. 完成报告必须包含

- 目标分支、commit、Git 标签及历史导入结果；
- 正式目录和资产数量核对；
- 依赖增删及锁定版本，不含任何凭据；
- A/B/C 各组命令、关键日志、测试结果和报告路径；
- Garmin 中国区认证、字段对照、分圈对照和增量去重结果，只写成功/失败及非敏感统计；
- KimiWork 模型首次生成、格式校验和第二次缓存命中的证据；
- 未生成 PDF、未访问 iCloud、未创建定时任务的确认；
- 连续两次手动验收和技能触发结果；
- 回滚备份位置及遗留问题。

不得将未实际验证的项目写成“已完成”。

---

## 附录：2026-11-06 验收用体感自述

「连续出差+应酬，导致不仅训练进度滞后，还拉跨了运动状态。今天一起步就感觉心率不对，一直找不到状态。第4公里开始4:55节奏，原来想坚持下看看能不能跑8KM的节奏跑，但坚持了6KM节奏跑配速之后，感觉不太行了。剩余6KM恢复跑，一时也没找到节奏，一直到最后4KM开始，慢慢找回状态，但感觉仍然比上周状态差。目前计划明后天跑一次有氧慢跑，找找状态，如果状态找回，下周二三再试一次节奏跑。」
