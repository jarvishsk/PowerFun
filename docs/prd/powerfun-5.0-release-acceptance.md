# PowerFun 5.0 发布验收清单

- 日期：2026-11-13
- 状态：已验收通过（125 项测试；全部回放及正式目录哈希复验通过，PowerFun 5.0 发布完成）
- 前置条件：第一批验收通过（84 项测试）；第二批验收通过（125 项测试，边界修正后复验通过）
- 执行方式：只做发布回归、入口文档同步和产品版本发布；完成后由主会话独立验收
- 目标产品版本：5.0
- Prompt 协议版本：保持 `LLM_PROMPT_VERSION = 12`

关联文档：

- [总体优化方案与执行索引](powerfun-5.0-master-plan.md)
- [第一批验收记录](../audits/2026-11-13-powerfun-5.0-phase-1-acceptance.md)
- [第二批 PRD](powerfun-5.0-phase-2-statistical-evidence-gates.md)
- [第二批最终验收记录](../audits/2026-11-13-powerfun-5.0-phase-2-acceptance.md)
- [第二批修正交付记录](../audits/2026-11-13-powerfun-5.0-phase-2-acceptance-fix.md)

## 1．发布目标与边界

第一、第二批的功能和统计口径已经验收，本批不再设计或调整分析逻辑，只完成：

1. 全量测试与既定只读回放；
2. 两个第二批验收边界及第一批缓存安全边界复验；
3. `README.md`、`SKILL.md` 与最终实现同步；
4. 根目录 `VERSION` 从 `4.1` 改为 `5.0`；
5. 数据安全、缓存、版本和工作区纪律终检。

### 明确禁止

- 不得修改 `_calc_short_term()`、`_calc_long_term()`、同比、百分位或其他统计算法；
- 不得修改人工课型、Pa:Hr 选段、缓存哈希、深析入口及其既有行为；
- 不得修改六小节、`<<<BRIEF>>>...<<<END>>>` 协议或 `_format_comparison()` 的分析语义；
- 不得提升 `LLM_PROMPT_VERSION`，不得借发布版本号强制刷新 LLM 缓存；
- 不得为了让测试通过而删除场景、放宽断言或再次调整已验收口径；
- 不得调用 Garmin、外部模型 API，不得生成正式报告或写正式缓存；
- 不得修改正式 `data/`、`reports/`、`cache/` 内容，不得 commit／push／打标签；
- 不得覆盖、回滚或整理工作区既有未提交改动。

若回归暴露生产代码问题，停止发布并报告，不在本批顺带修复。

## 2．允许修改的文件

### 2.1 产品版本

根目录 `VERSION` 当前内容为一行：

```text
4.1
```

改为：

```text
5.0
```

`src/utils.py` 的 `load_version()` 已从该文件读取版本号，无需也不应新增版本常量或版本机制。`main.py` 中 `LLM_PROMPT_VERSION = 12` 保持不变。

### 2.2 `README.md` 统计证据门槛说明

更新“统计证据门槛”条目，使其与最终代码一致，至少补齐：

- 短期不仅要求总样本 `n≥5`，心率、配速、效率还分别要求自身有效样本 `n≥5` 且当前值有效，才给该项方向判断；
- 总样本达标但某指标有效样本不足时，仅该指标降级为“样本有限”并保留描述，其他达标指标不受影响；
- 长期同温池的方向判断必须得到逐月剔除敏感性支持；全量分类为“稳定”也不例外，全量稳定但 LOO 不稳时同样降级为“趋势待确认”；
- 跨温池、同比、百分位等既有说明不得被删弱。

只改说明文字，不借文档同步重写其他功能介绍。

### 2.3 `SKILL.md` 统计证据语义

更新“统计证据语义”条目，同步上述两项最终规则：

- 短期方向判断按各指标自身有效样本和当前值逐项放行；
- 全量稳定但逐月剔除方向不稳时，不得输出确定“稳定”，应为“趋势待确认”。

保留既有 `n=3—4`、`<3`、跨温池、同比月份门槛和百分位门槛说明。命令、触发语义、六小节和缓存协议不变。

### 2.4 总体索引与发布交付记录

- 将 `docs/prd/powerfun-5.0-master-plan.md` 的“当前版本”更新为 `5.0`；发布批次状态更新为“已实施，待主会话验收”，不得自行标成主会话已验收。
- 新建 `docs/audits/2026-11-13-powerfun-5.0-release-delivery.md`，记录实际改动、命令、关键输出、数据安全检查和未解决问题。
- 第一批、第二批 PRD 与审查报告中的“当前版本 4.1／本批不得修改”是历史执行约束，保留原文，不做全局替换。

除上述文件及 `.runtime/acceptance/release/` 下的临时验证产物外，不应出现其他改动。

## 3．必跑验证

所有命令在项目根目录执行。不得生成正式报告；测试所需的缓存和运行时文件继续使用临时目录。

### 3.1 全量测试

```bash
.venv/bin/python -m pytest tests/ -q
```

通过标准：`125 passed`。既有 pandas／fitparse 弃用警告可记录，但不得出现失败、错误或新增未解释警告类别。

### 3.2 第一批缓存安全与口径回放

```bash
.venv/bin/python .runtime/acceptance/phase1/verify_remaining.py
.venv/bin/python .runtime/diagnostics/replay_phase1.py
```

通过标准：

- 合法 response 缺少同目录 `context.json` 时明确拒绝，退出码为 1，不写缓存、不生成正式报告；
- 2026-11-06、2026-11-09、2026-10-29、2026-11-12 的 Pa:Hr 依次为 `-6.14%`、`-4.12%`、不适用、`+0.92%`；
- 人工课型、工作段、问题清单及普通课型整场口径不变。

### 3.3 第二批边界、真实敏感场景与历史回放

```bash
.venv/bin/python .runtime/acceptance/phase2/verify_edges.py
.venv/bin/python .runtime/acceptance/phase2/verify_2026_09_24.py
.venv/bin/python .runtime/diagnostics/replay_phase2.py
```

通过标准：

1. 短期总样本 5、心率有效 1 时，`verdict_hr=None`，配速仍可独立给方向；理由列明各指标有效样本数。
2. 长期全量稳定但 LOO 方向改变时，返回“趋势待确认”、`verdict_allowed=False`，不得声称“逐月剔除方向分类一致”。
3. 2026-09-24 的配速全量斜率约 `-0.86 秒/月`，LOO 范围约 `-2.47～+4.05`，`loo_unstable_stable=['pace']`，最终为“趋势待确认”。
4. 2026-11-12 保持短期 13、长期 56、6 个有效月份、P73、Pa:Hr `+0.92%`；长期 `all_temp` 只作描述，同比旧 `-32.22/+86.18` 月斜率不得恢复。
5. 2026-11-12 同比心率、配速各有 3 个有效样本时，可保留心率 `138 bpm`、配速 `374 秒/km` 的描述性中位数；没有足够有效月份则不出月斜率。不得把交付文档中的“同比数据不足”笔误当成需要修改代码的新需求。
6. 2026-10-25 LSD 保持 `no_temp` 全池、4 个有效月份、只作描述；2026-10-22 保持 `all_temp`，不无条件输出“进步”。
7. 三个人工活动的课型、Pa:Hr 和问题清单与第一、第二批最终验收记录一致。

## 4．发布终检

### 4.1 版本解析

```bash
.venv/bin/python -c "from src.utils import load_version; assert load_version() == '5.0'; print('VERSION=' + load_version())"
.venv/bin/python -c "from main import LLM_PROMPT_VERSION; assert LLM_PROMPT_VERSION == 12; print('LLM_PROMPT_VERSION=12')"
```

同时检查 `VERSION` 文件只含 `5.0`，不要把 `VERSION=5.0` 写成文件内容。

### 4.2 数据与缓存安全

- 在任何验证命令执行前，将正式 `data/`、`reports/`、`cache/` 的文件路径、大小、mtime 和内容 SHA-256 清单保存到 `.runtime/acceptance/release/before.json`；
- 全部验证完成后，以同样方式生成 `after.json` 并比较，要求正式目录没有新增、删除或内容变化；
- 临时测试缓存、response、回放输出只能位于 `.runtime/` 或测试临时目录；不得用正式报告生成来“验证版本显示”。

### 4.3 工作区与范围检查

- 对比执行前后 `git status --short`，确认没有范围外文件被修改，既有未提交改动均保留；
- 交付文档逐项列出实际修改文件，不应出现 `src/deep_analyzer.py`、`src/analysis_report.py`、`main.py` 或测试文件改动；
- 不执行 commit、push、tag，不将 5.0 发布实施等同于主会话最终验收通过。

## 5．交付与主会话验收条件

执行会话交付：

1. 全量测试及五个只读验证／回放脚本的命令与真实结果；
2. `VERSION=5.0`、`LLM_PROMPT_VERSION=12` 的解析结果；
3. `README.md`、`SKILL.md` 修改前后关键文案；
4. 正式目录前后内容哈希一致的证明；
5. 实际修改文件清单、范围外改动说明及未解决问题；
6. `docs/audits/2026-11-13-powerfun-5.0-release-delivery.md`。

主会话复验全部通过后，才将发布批次标记为“已验收通过”，确认 PowerFun 5.0 发布完成。任何必跑项失败、正式数据变化或范围外生产代码改动，均阻断发布。
