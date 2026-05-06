# 🏃 PowerFun - 跑步数据分析

> 整合 Garmin Connect (China) 数据获取 + 跑步数据分析 + 可视化报告生成

**版本**: v4.0 (2026-05-06)

## 🚀 版本 4.0 更新

### 配置管理重构
- **📝 USER_CONFIG 独立**: `max_hr`（最大心率）和 `resting_hr`（静息心率）提取为独立用户配置区，首次使用时按实测数据修改即可，无需改其他代码
- **🔒 HR_ZONE_PERCENTAGES 固定**: Z1-Z5 区间百分比基于 Karvonen HRR 法写死，不可更改，确保所有用户计算逻辑一致
- **🗑️ 零硬编码**: 所有心率参数均从 `DEFAULT_CONFIG` 统一读取，清除历史遗留的 `default=190` / `default=60` fallback 代码
- **⚡ CLI 参数自动同步**: `--max-hr` / `--resting-hr` 默认值从配置自动读取，无需手动指定

### 报告流程修正
- **📋 顺序调整**: 完整流程改为「综合报告 → 深度分析报告」，符合用户直觉
- **🔗 深析链接机制**: 综合报告扫描已有深析报告文件生成链接，最新一次深析在下次跑综合报告时自动补链
- **🎯 --deep-analyze 独立**: 单独指定日期深析时仅生成深析报告，不触发综合报告重跑

### 心率区间修复
- **🫀 HRR 计算修正**: `_get_hr_zone_ranges` 使用用户配置的 `max_hr`（188）而非单次跑步的实际峰值心率计算区间边界
- **📊 区间边界正确**: Z1 边界从错误的 60-133 修正为 61-154 bpm（基于 max_hr=188, resting_hr=60）

### 图表优化
- **📐 图例居中**: 所有图表图例统一居中对齐（`xanchor='center'`）
- **🔄 堆叠柱状图**: 月度心率区间时长图例顺序修正为 Z1→Z5
- **🎨 公共样式**: 提取 `_common_layout_style` 消除重复代码
- **🐛 margin 冲突修复**: 解决 `update_layout` 中重复 `margin` 参数导致图表生成失败的问题

### 代码质量
- **🧹 清理 .bak 文件**: 移除 git 中的备份文件，`.gitignore` 添加 `*.bak` 规则
- **🛡️ 类型注解**: 函数签名参数类型完善（如 `max_hr: int` 而非 `None` + fallback）
- **📝 注释更新**: ZONES range 注释从旧版 190-60 更新为动态计算说明

## 🚀 版本 3.0 更新

### 核心功能
- **📊 深度分析报告**: 支持单次跑步深度分析（HTML + PDF + iCloud 同步），包含能力对比、技术分析、AI 教练建议
- **🔍 指定跑步分析**: `--deep-analyze` 支持按日期或关键词分析指定跑步，`--deep-analyze-all` 批量生成
- **📈 训练效果面积图**: 上线（有氧+无氧）、下线（有氧）、红色填充区域直观展示无氧训练占比
- **🌐 国内 CDN 优化**: jQuery + DataTables 切换为国内 CDN，解决图表加载失败问题
- **📱 平滑曲线图表**: 训练效果图采用 spline 平滑，配速格式统一补零对齐

### 数据与配置
- **🔐 安全配置**: 路径使用 `Path.home()` 替代硬编码，`.data/` 目录集中管理运行时数据
- **📏 心率区间统一**: 统一使用 Karvonen HRR 法，心率区间颜色定义统一到 `config.py`
- **🏃 赛事识别简化**: RACE_KEYWORDS 从 45+ 个具体赛事名简化为 8 个通用关键词
- **📊 功率数据阈值优化**: 功率分布图阈值从 5 降至 2，3-4 条有效数据也可显示

### 代码质量
- **🛡️ 安全增强**: XSS 防护（LLM 输出过滤）、API key 传递修复、HTTPS 连接泄漏修复
- **🧹 代码重构**: 拆分为子方法、消除重复逻辑、类型注解完善、统一 fetcher.close() 处理
- **⚡ 性能优化**: classify 方法单次调用、DataFrame copy 减少、缓存按日期排序
- **🔧 错误处理**: 配速数据缺失报错退出、429 限流后客户端重建、LLM API 重试机制

## 🚀 版本 2.1 更新

- **📊 Garmin 官方心率区间**: 饼图和堆叠柱状图改用 Garmin API 原生 `hrTimeInZone_1~5` 字段
- **🧹 代码质量优化**: 消除重复代码、安全列重命名映射、图表失败日志提示
- **📈 心率轴范围优化**: 配速-心率趋势图心率轴调整为 `[120, 180]`

## 🚀 版本 2.0 特性

- **⚡ 功率数据分析**: 支持 Garmin 功率数据
- **👟 步频与垂直振幅**: 完整支持步频和垂直振幅比分析
- **🛡️ 安全增强**: XSS 防护、安全 token 存储
- **📁 智能文件管理**: 主报告 + 自动备份策略
- **🎯 精准心率区间**: 动态计算，支持自定义最大/静息心率
- **📱 移动端优化**: 响应式 HTML 报告

## 配置说明

### 首次使用：修改心率参数

打开 `src/config.py`，找到顶部的 `USER_CONFIG` 区段：

```python
# 📝 用户可配置参数（首次使用时按实测数据修改）
USER_CONFIG = {
    'max_hr': 188,        # 最大心率（实测值）
    'resting_hr': 60,     # 静息心率（实测值）
}
```

按你的实测值修改 `max_hr` 和 `resting_hr`，其余代码自动同步。

> ⚠️ `HR_ZONE_PERCENTAGES` 是基于 Karvonen HRR 法的固定百分比，不可修改。

## 快速开始

### 安装

```bash
cd PowerFun
pip install -r requirements.txt
```

### 运行

```bash
# 首次运行（需要账号密码）
python main.py --email your_email@example.com --password your_password

# 后续运行（使用已保存的 token）
python main.py

# 指定最大心率和静息心率（可选，默认从 config.py 读取）
python main.py --max-hr 180 --resting-hr 60

# 深度分析指定跑步
python main.py --deep-analyze 2026-04-25
python main.py --deep-analyze "富阳半程马拉松"

# 跳过 API 拉取，直接从 parquet 生成报告
python main.py --load-parquet

# 仅拉取数据，不生成报告
python main.py --dry-run
```

## 项目结构

```
PowerFun/
├── main.py                 # 主程序入口
├── requirements.txt        # Python 依赖
├── README.md              # 项目文档
├── VERSION                # 版本文件
├── .gitignore
├── .data/                 # 运行时数据（token、缓存）
└── src/
    ├── __init__.py
    ├── config.py           # USER_CONFIG + HR_ZONE_PERCENTAGES + DEFAULT_CONFIG + 字段映射
    ├── data_fetcher.py     # Garmin Connect API 数据获取
    ├── data_processor.py   # 数据清洗 + 字段映射 + 校验
    ├── classifier.py       # 心率区间 + 跑步类型分类
    ├── chart_generator.py   # Plotly 交互式图表
    ├── report_generator.py # Jinja2 HTML 报告生成
    ├── pdf_generator.py    # Playwright PDF 生成
    ├── deep_analyzer.py    # 深度分析器 + LLM 报告生成
    └── analysis_report.py  # 深度分析 HTML 报告生成
```

## 数据流

```
正常流程:
  Garmin API → 清洗 → 过滤 → 分类 → 保存 parquet
                                             ↓ 读取
                              综合报告(HTML+PDF) + 最近一次深析报告

--load-parquet 模式:
  读取 parquet → 综合报告 + 最近一次深析报告

--deep-analyze 模式:
  仅生成指定日期的深度分析报告
```

## 字段映射

完整字段映射见 `src/config.py` 中的 `FIELD_MAPPING` 字典。

| 跑分期望字段 | Garmin 源字段 | 转换方式 |
|-------------|--------------|---------|
| date | startTimeLocal | 解析 datetime |
| distance | distance | 直接映射（米 → km） |
| avg_hr | averageHR / avgHeartRate | 直接映射 |
| max_hr | maxHR / maxHeartRate | 直接映射 |
| hr_zone_1~5_sec | hrTimeInZone_1~5 | 直接映射（秒） |
| avg_pace | pace_min_per_km | min/km → mm:ss |
| best_pace | maxSpeed | m/s → km/h → mm:ss |
| duration | elapsed_min | 分钟 → hh:mm:ss |
| ... | ... | ... |

## 输出

- **主 HTML 报告**: `~/Documents/Run/PowerFun.html`
- **PDF 报告**: `~/Documents/Run/综合分析报告.pdf`
- **深析报告**: `~/Documents/Run/PowerFun_Reports/run_analysis_YYYYMMDD.html` + `深度分析报告_YYYYMMDD.pdf`
- **清洗后 CSV**: `~/Documents/Run/running_data_cleaned.csv`
- **状态文件**: `.data/last_fetch.json`

## 注意事项

- Garmin 账号密码通过命令行参数传入，不会持久化存储
- 限流时自动等待 1 小时后重试（指数退避）
- 数据目录 `.data/` 已加入 `.gitignore`
- 心率区间分布使用 Garmin 官方 `hrTimeInZone_1~5` 数据
- 配速数据为关键数据，缺失时会报错退出
- 心率区间计算使用 **Karvonen HRR（心率储备法）**，固定百分比不可更改

## License

MIT
