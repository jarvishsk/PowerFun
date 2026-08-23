# PRD: PowerFun 遗留问题修复（fetcher 生命周期 / test-data 崩溃 / 孤儿脚本清理）

- **日期**：2026-08-23
- **项目**：`~/Projects/skills/PowerFun`
- **来源**：2026-08-22 技能全面审阅发现的 3 个代码疑点，老板已确认处理方案
- **规模**：小改动，3 项修复，预计 < 30 行变更

## 背景

2026-08-22 对 PowerFun 做全面审阅，Round1-4 修复已全部提交（最新 commit `cb0ecf6`）。剩余 3 个代码疑点经老板确认处理方案：修 5、修 4、删 6。

## 修复项

### Fix 1（最高优先）：`--test-data` 模式必崩

**现象**：test-data 路径下 `fetcher` 为 `None`，但 Step 7.5 分圈拉取无条件执行 `fetcher._load_lap_cache(act_id)` → `AttributeError: 'NoneType'`。

**根因**：test-data 是无 API 的离线模式，Step 7.5 分圈拉取本就不该在此模式执行。

**修法**（`main.py` `_main_inner` Step 7.5 处）：
- 在 Step 7.5 入口加守卫：`fetcher is None` 时跳过分圈拉取，日志说明「test-data 模式，跳过分圈拉取」。
- 不要为此在 test-data 模式新建 fetcher——离线模式不应触网。

### Fix 2（低优先）：fetcher 关闭失效

**现象**：`main()` 中 `fetcher = None` 按值传入 `_main_inner(args, fetcher)`，正常模式（路径 C）在 `_main_inner` 内部新建了局部 fetcher，`main()` 的 `finally: if fetcher is not None: fetcher.close()` 永远关不到它（外层始终是 None）。

**修法**：
- 把 `try/finally + fetcher.close()` 下沉到 `_main_inner` 内部——即 fetcher 真正创建的地方管理其生命周期。
- `main()` 简化为直接调用 `_main_inner(args)`，不再传递 fetcher 参数。
- 注意 `_run_reports` 的 `fetcher` 参数传递链保持不变（`_main_inner` → `_run_reports`），只是关闭责任归 `_main_inner`。
- 参考：`close()` 仅重置 garth 客户端，无资源泄漏风险，本次属于「把声称修过的生命周期修干净」。

### Fix 3：删除 `fetch_all_laps.py`

**原因**：一次性脚本（首次批量拉分圈），使命已完成（`.data/lap_data.parquet` 已有 118 条活动 / 2189 圈）。日常增量由 main.py Step 7.5 覆盖。脚本重复实现了 `GarminDataFetcher` 的分圈逻辑且硬编码了 DEFAULT_CONFIG 已有的参数，属于维护负债。

**操作**：`git rm fetch_all_laps.py`。

## 验收标准

1. `python3 -c "import ast; ast.parse(open('main.py').read())"` 语法通过
2. `python3 main.py --load-parquet --dry-run` 正常退出（exit 0）——验证 parquet 加载路径无回归
3. `python3 main.py --test-data <小样例.json> --dry-run` 正常退出（exit 0），不再 AttributeError——Coder 自造一个最小测试 JSON（1-2 条活动，含 Garmin API 原始字段结构，可参考 `.data/activities_cache.json` 的真实结构裁剪），测试 JSON 放 `tmp/` 或测试后删除，不进 git
4. `git status` 干净，变更已 commit

## 约束

- 最小改动，不重构无关代码，不动 config.py / 报告生成逻辑
- commit message 遵循仓库现有风格（`fix: ...` 中文摘要）
