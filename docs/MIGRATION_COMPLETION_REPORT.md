# PowerFun 迁移完成报告

生成时间：2026-11-09（Asia/Shanghai）
对应指令：2026-11-09 12:53 收尾指令（七大项）
工作目录：`/Users/jarvis/Projects/KimiWork/PowerFun`

---

## 1. 仓库与版本状态

- 分支：`migration/kimiwork`
- 最新 commit：`aa3f7bd` fix(garmin-check): 不输出用户资料内容，只报告认证/活动ID/圈数/成败
- 迁移期关键提交：
  - `b28aaab` fix(fetch_new): 内容变化的已有活动重新清洗并 upsert 主表/分圈；CSV 从最终主表导出
  - `f37ca5d` fix(fetch_new): 无待处理活动时也从主表幂等刷新 CSV
  - `1dfda71` refactor: 移除 garth SSO 抓取实现与依赖（Personal API 已验收）
  - `aa3f7bd` fix(garmin-check): 去除个人资料输出
- 标签：`v1.0` / `v2.0` / `v2.1` / `v3.0` / `v4.1` 均未修改
- 工作区：干净（`git status` 无未提交改动，本报告提交后即为最新 HEAD）
- 历史导入完整：`git fsck --no-dangling` 返回码 0（证据 `.runtime/final-acceptance/git-fsck.txt`）
- **未 push**（按指令要求）

---

## 2. 最终数据量与增量原因

口径：**固定迁移基线 + 经过验证的增量**（测试 `test_data_integrity.py` 中的 `MIGRATION_BASELINE` + `VERIFIED_INCREMENTS`）。

| 数据 | 基线 | 已验证增量 | 最终 | 说明 |
|---|---|---|---|---|
| 原始活动缓存（activities_cache.json） | 153 | +1（活动 660164388，2026-11-08） | 154 | 迁移后一次真实跑步 |
| 主表（running_data.parquet） | 150 行 / 150 唯一 activity_id | +1 | **151 行 / 151 唯一 id / 62 列** | 150→151 不是丢数 |
| 分圈（laps） | 2,740 行 | +17（660164388 共 17 圈） | **2,757 行** | |
| 深析 HTML | 94 份 | +1 | **95 份** | |
| LLM 缓存 | 22 份 | +1 | **23 份** | |
| CSV（running_data_cleaned.csv） | 150 行 / 截止 2026-11-06 | 修复后刷新 | **151 行 / 截止 2026-11-08** | 见 §3 缺陷修复 |

150 → 151 差异的定性结论（与此前一致）：**不是迁移丢数**。迁移期核对确认 153 条原始缓存中 3 条在清洗过滤规则下本就不入主表（历史口径如此，过滤规则本身有回归测试覆盖）；真正缺陷是 CSV 未随主表刷新，已在 §3.1 修复。

如实说明：验收过程中旧版失败测试曾级联删除 `cache/llm/659451010.md`，已从迁移前备份 `.runtime/backups/20261108_pre_kimiwork_cache/` 原样恢复（user_note_hash 与报告附录体感文本匹配校验通过），恢复后 LLM 缓存为 23 份，正式缓存无损失。

---

## 3. 产品代码修复

### 3.1 CSV 同步缺陷（必修）

**根因**：`src/personal_api.py` 的正式增量写出流程只写 `running_data.parquet`，从不调用 CSV 导出，导致新活动 660164388 已在主表中、CSV 却停在 150 行 / 2026-11-06。

**修复**：主表合并、去重、排序完成后，使用现有 `_export_csv()`（经 `DataProcessor().to_csv()`）从**最终合并后的主表**同步刷新 `running_data_cleaned.csv`，保持既有 12 列导出口径，不另造格式。无待处理活动时也执行一次幂等刷新（commit `f37ca5d`），保证任何一次正式拉取后 CSV 与主表必然一致。

### 3.2 已有活动更新不回流主表（必修）

**根因**：`fetch_new()` 只重新清洗 `truly_new` 活动；标题或字段更新的已有活动只写回 `activities_cache.json`，主表/分圈不更新。

**修复**（commit `b28aaab`）：

- 处理对象从"仅新增"改为"新增 + 内容发生变化的已有活动"（对比缓存与远端字段）；
- 变化的活动重新清洗、分类并 **upsert** 主表；对应分圈按 `activity_id + lap_index` 去重后同步更新；
- 未变化的已有活动不重复处理；
- 标题保护收窄为"仅保留缓存中的自定义标题"，不再阻断其他字段更新；
- CSV 一律从最终合并后的主表导出。

**回归测试**（`tests/test_fetch_new.py`，全部基于 mock/fixture，fixture 为真实 FIT 文件 `tests/fixtures/659451010.fit`）：新增活动、已有活动字段更新、自定义标题保护、完全重复记录四场景 + CSV 与主表行数/集合/末日期一致性断言 + **FIT 基准逐圈零差异回归**（基准活动 16 圈、8 个数值字段与历史缓存 max diff = 0）。

### 3.3 测试体系修复

- **数据完整性测试**：删除硬编码 153/150/2740/94 与 2026-11-06，改为 `MIGRATION_BASELINE`（153/150/2740/94/22，max_date 2026-11-06）+ `VERIFIED_INCREMENTS`（660164388，17 圈，2026-11-08）结构；唯一性、过滤规则、字段数（62）、分圈覆盖检查全部保留。
- **报告测试**：历史场景显式使用 2026-11-06 / 活动 659451010；latest 场景按当前数据动态确定活动与上下文，不再假定 latest 是旧活动。
- **正式缓存隔离**：`config.py` 新增 `POWERFUN_CACHE_DIR` / `POWERFUN_LLM_RUNTIME_DIR` 环境变量覆盖；llm_cycle、reject 等测试经 env 使用临时目录，测试失败也不会污染正式缓存或后续测试。
- **级联 FileNotFoundError 修复**：`test_reject_wrong_activity_response` 等测试改为自建立、自清理前置状态，相互独立。
- 未使用 skip / xfail / 降低字段对照等任何手段制造通过。

---

## 4. 依赖清理

- **移除 garth 0.8.0**：Personal API 已验收通过，`data_fetcher.py` 重写为纯本地分圈缓存访问器（保留 `GarminDataFetcher` 类名、签名与 `load_all_lap_data` 等接口）；`main.py` 删除路径 C SSO 流程及 `--force-login / --logout / --backfill-since / --email / --password / --days` 等参数。不是只删 requirements 留 import——全代码树已无 garth import。
  - 说明：`data_processor.py` 中"garth 格式"字样是对**历史已存数据格式**的解析注释，与抓取库无关，保留。
- **移除 httpx 0.28.1**：核查官方 Garmin Personal API 客户端只依赖 `requests`，httpx 非直接依赖亦非必要传递依赖，`pip uninstall` 后全量测试与验收命令均通过，据实删除。
- **新增 fitparse 1.2.0**：FIT 文件分圈解析（官方客户端链路之外的分析需要，基线 FIT 回归测试依赖）。
- `requirements.txt` 与 `requirements.lock` 均已同步更新；`pip check` 返回码 0（证据 `.runtime/final-acceptance/pip-check.txt`）。

**清理**：工作区（除 `.venv` / `.migration-research`）与 `.git` 中的 `.DS_Store` 已删除，`git ls-files` 无跟踪，`.gitignore` 规则有效。

---

## 5. 重新验收结果（证据均在 `.runtime/final-acceptance/`）

### 5.1 pytest

`.venv/bin/python -m pytest -q` → **32 passed，0 failed，0 error**（修复前为 6 failed / 14 passed / 7 errors）。证据：`pytest.txt`。确定性场景 8 项与响应校验 4 项随全量一并通过。

### 5.2 深析综合报告（两份）

| 命令 | 输出目录 | 结果 |
|---|---|---|
| `main.py --load-parquet --deep-analyze 2026-11-06 --output .runtime/final-acceptance/reports-1106` | `reports-1106/` | 通过 |
| `main.py --load-parquet --deep-analyze latest --output .runtime/final-acceptance/reports-latest` | `reports-latest/` | 通过 |

校验（`report-verify.txt`，全部 ✅）：各 10 个 Plotly 图表；深析六小节完整；本地资源与历史链接有效；无 CDN、无 PDF、无 iCloud、无工作区外路径。latest 场景输出 `LLM_CACHE_HIT`，复用正式缓存。

### 5.3 Garmin 检查

`main.py --garmin-check`（证据 `garmin-check.txt`）：认证成功、活动列表与详情读取成功、最新活动 FIT 解析 17 圈，全部成功。**输出仅含认证状态、活动 ID、圈数与成功/失败，不含个人资料或凭据**（commit `aa3f7bd` 修复后复验）。

### 5.4 隔离 stage 拉取与正式数据哈希对照

`main.py --fetch-new --stage .runtime/final-acceptance/garmin-validation`（证据 `stage-fetch.txt`、`sha256-before.txt`、`sha256-after.txt`）：

- stage 拉取前后对正式数据文件（主表 parquet、CSV、activities_cache.json、lap cache、LLM 缓存）计算 SHA-256；
- **前后哈希逐项完全一致**，stage 模式未修改正式数据，stage 内新增 0 条。

### 5.5 正式写入验证（CSV 修复验证）

先完成 stage 对照后，备份至 `.runtime/backups/20261109_131110/`，再执行一次正式 `fetch-new`（证据 `formal-fetch.txt`）：

- 新增活动仅入账一次（660164388）；
- 修复验证通过：**parquet 151 行 == CSV 151 行，活动集合一致，CSV 末日期 2026-11-08，无重复 activity_id**。

### 5.6 git fsck

`git fsck --no-dangling` 返回码 0（证据 `git-fsck.txt`）。

### 5.7 FIT 基准零差异回归

基线活动 FIT 解析 16 圈、8 个数值字段与历史分圈缓存逐圈比对 max diff = 0，已固化为回归测试（`tests/test_fetch_new.py`），每次 pytest 全量执行。

---

## 6. KimiWork C 组验收

1. **隔离全流程走通**（证据 `.runtime/final-acceptance/iso/` + `c-group-prepare.txt` / `c-group-render.txt` / `c-group-cachehit.txt`）：在 `POWERFUN_CACHE_DIR` / `POWERFUN_LLM_RUNTIME_DIR` 指向隔离目录的环境下：
   - `--prepare-llm` → 输出 `LLM_REQUEST_REQUIRED`，生成隔离 request；
   - 当前 KimiWork 会话模型生成 response（六小节 + BRIEF 完整）；
   - `--llm-response` 校验通过并成功 render；
   - 再次运行同活动 → 输出 `LLM_CACHE_HIT`，缓存命中隔离缓存（model 记录为 KimiWork）；
   - 全程未删除或移动正式 `cache/llm/`，正式 LLM 缓存哈希前后 diff 为空。
2. **两次手动端到端**：上述 prepare→生成→render 为第一次；第二次复跑命中缓存（见 `c-group-cachehit.txt`）。
3. **SKILL.md 一致性**：受管注册副本 `powerfun/SKILL.md` 与项目 `SKILL.md` 内容一致（diff 为空）。
4. **新会话触发验证：未验证。** 注册文件存在不等于新会话触发通过；当前会话无法自证新会话的发现与触发。老板需在新会话输入的测试语句，例如：
   > 跑步分析，体感：今天跑了 10 公里有点累
5. **定时任务**：经 AutomationControl 全量核查，当前所有常规任务均属于其他项目，**迁移期间未创建任何 PowerFun 相关定时任务**。

---

## 7. 备份位置

| 备份 | 内容 |
|---|---|
| `.runtime/backups/20261108_pre_kimiwork_cache/` | KimiWork 迁移前正式缓存快照（llm_659451010.md 恢复来源） |
| `.runtime/backups/20261109_000402/` | 测试体系修复前相关快照 |
| `.runtime/backups/20261109_131110/` | 正式 fetch-new 写入前的正式数据备份 |

---

## 8. 边界确认

- 未读取后修改、未清理、未写入原 OpenClaw 项目与真实 iCloud；
- 未生成 PDF；
- 未调用外部模型 API（深析 LLM 环节均为本地缓存复用或当前会话内生成）；
- 未创建定时任务、未 push、未修改历史标签；
- Garmin Key 经老板决定**保留不轮换**；Key 内容未输出、未复制、未记录、未写入代码/测试/日志/PRD/本报告，未提交 Git。

---

## 9. 尚未实际验证 / 遗留项（如实列示）

1. **技能在新会话的触发验证：未验证**（见 §6.4，给出测试语句）。
2. **vO2MaxValue 不在 Garmin 中国区 Personal API 返回字段中**，新增活动 VO2max 为空；报告渲染层已做 NaN 容错，历史数据不受影响。是否补数据源待老板决策。
3. **`.migration-research/` 保留未删**：因第 1 项（新会话触发）尚未验证，按指令"其余验收全部通过才可删除"的规则保留；该项验证通过后可删。
4. 本报告中的验收结论均基于 `.runtime/final-acceptance/` 内保存的当期证据；此后若再新增活动，数据量按"基线 + 已验证增量"口径递增，测试不受影响。
