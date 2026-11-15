# PowerFun 5.0 总体优化方案与执行索引

- 日期：2026-11-13
- 当前版本：5.0.2
- 目标版本：5.0
- 执行方式：一次只下发一个 PRD；执行会话落实；主会话验收合格后再下发下一 PRD
- 总审查报告：[PowerFun 5.0 项目审查报告](../audits/2026-11-13-powerfun-5.0-review.md)

## 1．目标

本次 5.0 不以增加功能数量为目标，而是修正影响训练判断的基础口径：

- 让节奏跑和间歇跑进入正确课型与参照池；
- 让 Pa:Hr 只在其适用范围内计算，并修复漂移漏报；
- 让缓存在分析事实变化后可靠失效；
- 让跨温、小样本和同比结果不再被过度解释为能力变化；
- 合并重复深析入口，降低后续维护成本。

## 2．已确认边界

### 要做

- 人工覆盖节奏跑、间歇跑，保留自动分类与来源；
- 普通课型 Pa:Hr 保持现状，节奏跑使用人工连续工作段，间歇跑默认不适用；
- 缓存增加分析数据哈希；
- 正常最新深析复用统一函数；
- 跨温数据保留用于描述，但限制能力 verdict；
- 按指标设置样本门槛和趋势稳定性检查；
- 全部批次验收后将 `VERSION` 从 4.1 改为 5.0。

### 不做

- 不重写 Garmin 数据管道，不回写历史 parquet 的自动分类；
- 不让模型从自由文本静默猜测课型或工作段；
- 不自动识别节奏稳态段，不自动识别间歇组；
- 不给间歇跑计算整场 Pa:Hr；
- 不建立个人化温度修正系数；
- 不通过 IQR 或单次状态异常删除整次活动；
- 不在 5.0 首批中重做负荷模型、强度结构、间歇组分析或 FIT 补拉机制；
- 不调用外部模型 API，不生成 PDF，不上传数据，不创建定时任务。

## 3．批次计划

| 批次 | 内容 | 执行文档 | 状态 |
|---|---|---|---|
| 第一批 | 人工课型、Pa:Hr 双轨、漂移符号、缓存哈希、深析入口合并 | [第一批 PRD](powerfun-5.0-phase-1-manual-category-pahr-cache.md) | 已验收通过（84 项测试） |
| 第二批 | 短期中位数、长期跨温 verdict、逐月敏感性、同比、多月份门槛、历史百分位 | [第二批 PRD](powerfun-5.0-phase-2-statistical-evidence-gates.md) | 已验收通过（125 项测试；边界修正后复验通过） |
| 发布 | 全量回归、文档同步、产品版本 4.1→5.0 | [5.0 发布验收清单](powerfun-5.0-release-acceptance.md) | 已验收通过（PowerFun 5.0 发布完成） |
| 5.0.1 修复 | 稀疏赛事分圈证据统一、跨全年描述性兜底、空状态与 Prompt 缓存修复 | [5.0.1 PRD](powerfun-5.0.1-sparse-race-evidence-fix.md) | 已验收通过（142 项测试；PowerFun 5.0.1 发布完成） |
| 5.0.2 修复 | 同距离比赛参照、技术变化解释、比赛问题分类、结构化计划与点评语义验收 | [5.0.2 PRD](powerfun-5.0.2-race-coaching-evidence.md)；[最终验收](../audits/2026-11-15-powerfun-5.0.2-final-acceptance.md) | 已验收通过（170 项测试、98 项回放；PowerFun 5.0.2 发布完成） |

第二批不得提前由第一批执行会话顺带实现，以便分别判断“课型修正造成的变化”和“统计门槛造成的变化”。

## 4．历史回放基准

第一批必须至少核对以下活动：

| 活动 | 人工课型／段落 | 关键预期 |
|---|---|---|
| 2026-11-06，`659451010` | 节奏跑，第 4—9 圈 | Pa:Hr `-6.14%`；配速 295→295 秒/km；心率 168→179 bpm；触发负向漂移 |
| 2026-11-09，`660460268` | 节奏跑，第 5—11 圈 | Pa:Hr `-4.12%`；配速 290→291 秒/km；心率 169.1→175.7 bpm；不触发 5% 漂移 |
| 2026-10-29，`656543045` | 间歇跑，无 Pa:Hr 段 | Pa:Hr 不适用；原轻松跑 P100 消失；不再污染轻松跑基线 |
| 2026-11-12，`661585068` | 轻松跑，无覆盖 | Pa:Hr 保持 `+0.92%`；短期参照 14→13，长期参照 57→56 |

第一批只验证分类、Pa:Hr、缓存及由其直接引起的参照池变化。跨温 verdict 和同比斜率的删除属于第二批验收，不应被提前宣称为第一批成果。

## 5．版本与缓存版本纪律

- 产品版本：所有 5.0 批次验收完成后才修改为 `5.0`，第一批和第二批执行过程中保持 `4.1`。
- Prompt 协议版本：5.0.1 使用 `LLM_PROMPT_VERSION = 13`；5.0.2 已验收发布并升级为 14。
- 分析缓存：新增 `analysis_hash` 后，旧格式缓存自然失效一次；不能靠全量提升 Prompt 版本替代分析哈希。
- 测试不得为了消除失败而删除历史场景或降低断言；确实改变口径时，应更新有证据支持的预期值并说明原因。

## 6．验收与交付纪律

- 主会话每次写完 PRD，必须在同次回复中直接附上可交给执行会话的实施 Prompt，不再等待老板单独提醒。

每一批执行会话需要交付：

1. 实际修改文件清单；
2. 新增／修改测试清单；
3. 全量测试命令与结果；
4. 指定历史活动回放结果；
5. 未解决问题和是否偏离 PRD 的说明；
6. 不得覆盖或回滚工作区已有未提交改动。

主会话验收重点：

- PRD 每一项是否真正实现，而非只在文档或 Prompt 中声明；
- 数值是否由 Python 确定性内核计算；
- 普通跑是否保持既定口径；
- 缓存是否在“应失效”和“应命中”两种情况下都正确；
- 测试是否覆盖正常、缺失、错误配置和历史回放；
- 是否出现范围外改动。

验收未通过时只返回修正意见，不下发下一批 PRD。

## 7．文档归档

本次新增：

- `docs/audits/2026-11-13-powerfun-5.0-review.md`：完整审查证据与取舍；
- `docs/prd/powerfun-5.0-master-plan.md`：本总体方案与批次索引；
- `docs/prd/powerfun-5.0-phase-1-manual-category-pahr-cache.md`：第一批执行 PRD；
- `docs/audits/2026-11-13-powerfun-5.0-phase-1-acceptance.md`：第一批初验与修正后复验记录；
- `docs/audits/2026-11-13-powerfun-5.0-phase-1-acceptance-fix.md`：第一批阻断项修正交付；
- `docs/prd/powerfun-5.0-phase-2-statistical-evidence-gates.md`：第二批统计证据门槛执行 PRD；
- `docs/audits/2026-11-13-powerfun-5.0-phase-2-delivery.md`：第二批初验交付记录；
- `docs/audits/2026-11-13-powerfun-5.0-phase-2-acceptance.md`：第二批初验问题与修正后最终验收记录；
- `docs/audits/2026-11-13-powerfun-5.0-phase-2-acceptance-fix.md`：第二批阻断项修正交付；
- `docs/prd/powerfun-5.0-release-acceptance.md`：5.0 发布执行与验收清单；
- `docs/audits/2026-11-13-powerfun-5.0-release-delivery.md`：发布批次执行交付；
- `docs/audits/2026-11-13-powerfun-5.0-release-acceptance.md`：5.0 发布最终验收记录；
- `docs/prd/powerfun-5.0.1-sparse-race-evidence-fix.md`：稀疏赛事证据一致性与空状态修复 PRD；
- `docs/audits/2026-11-15-powerfun-5.0.1-sparse-race-delivery.md`：5.0.1 执行交付与主会话复核修正；
- `docs/audits/2026-11-15-powerfun-5.0.1-sparse-race-acceptance.md`：5.0.1 最终验收记录；
- `docs/audits/2026-11-15-powerfun-race-analysis-review.md`：横店半马教练点评复核及老板补充决策；
- `docs/prd/powerfun-5.0.2-race-coaching-evidence.md`：同距离比赛参照、技术解释与点评语义修复执行 PRD。

历史项目文档已迁入：

- `docs/MIGRATION_PRD.md`
- `docs/MIGRATION_COMPLETION_REPORT.md`

根目录 `README.md` 与 `SKILL.md` 是项目／技能运行入口，继续保留在原位，不作为普通历史文档移动。
