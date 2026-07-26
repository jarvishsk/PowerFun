# PowerFun 跑步数据分析 — 经验教训

## 关键技术要点

1. **Garmin.cn 字段映射**：功率 `avgPower`、步频 `averageRunningCadenceInStepsPerMinute`、垂直振幅 `avgVerticalRatio`
2. **心率区间**：API 原生 `hrTimeInZone_1~5` 在 activity 顶层（非 summaryDTO），`averageHR`/`maxHR` 同理
3. **Karvonen HRR**：`HRR = max_hr - resting_hr`；Z1(0.01,0.74) Z2(0.74,0.84) Z3(0.84,0.88) Z4(0.88,0.94) Z5(0.94,1.00)；max_hr=188, resting_hr=60；**唯一方法，绝不用最大心率法**
4. **USER_CONFIG 独立**（v4.0）：`max_hr`/`resting_hr` 提取为独立配置，`HR_ZONE_PERCENTAGES` 写死，零硬编码
5. **报告流程**：综合报告 → 深析报告；`--deep-analyze` 独立不触发综合报告
6. **XSS 防护**：用户输入必须 HTML 转义

## 经验教训

- **官方数据优先**：API 有原生字段时不用本地计算
- **Coder Agent 按 High→Medium→Low 选择性修复**：避免过度工程化
- **数据准确性红线**：清洗只做单位/格式转换，不推导业务指标
- **对比分析基线**：严格按跑步类型隔离（轻松跑只跟轻松跑比），同类型内加温区分桶（三档），降级只放宽温区不放宽类型
- **统计用中位数+P25P75**：替代均值+min-max，抗异常值干扰
- **报告输出**：不再生成 PDF，HTML 为最终形态，自动复制到 iCloud 云盘
- **iCloud 复制防死锁**：`shutil.copy2` 覆盖写入会被 iCloud 同步锁阻塞（EDEADLK），必须先 `dst.unlink(missing_ok=True)` 再 copy
- **深度分析距离取整**：prompt 中距离用 `int()` 取整，避免 AI 生成不存在的分段（如 16.2KM 出现"第 17KM"）
- **图表横轴日期**：用 `type='date'` + `tickformat='%m-%d'`，让 Plotly 自动选刻度，不要手动按月分组
