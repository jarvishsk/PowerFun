# 🏃 PowerFun - 跑步数据分析

> 整合 Garmin Connect (China) 数据获取 + 跑步数据分析 + 可视化报告生成

**版本**: v3.0 (2026-05-02)

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

## 功能特性

- **🔐 自动登录**: Garmin Connect China 区域 SSO 登录
- **📊 智能拉取**: 首次全部拉取，后续增量更新，自动去重
- **🧹 数据清洗**: 完整的字段映射、类型转换、异常检测
- **❤️ 心率区间**: Garmin 官方 5 区间时长 + 本地平均心率分类（双数据源）
- **⏱️ 配速趋势**: 移动平均、趋势判断（提升/持平/下降）
- **📈 可视化**: Plotly 交互式仪表盘（9 个独立图表）
- **📄 HTML/PDF 报告**: 完整跑步分析报告，移动端友好
- **🔍 深度分析**: 支持指定跑步深度分析，AI 教练建议

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

# 指定最大心率和静息心率
python main.py --max-hr 180 --resting-hr 60

# 深度分析指定跑步
python main.py --deep-analyze 2026-04-25
python main.py --deep-analyze "富阳半程马拉松"
```

## 项目结构

```
PowerFun/
├── main.py                 # 主程序入口（10 步流程）
├── requirements.txt        # Python 依赖
├── README.md              # 项目文档
├── VERSION                # 版本文件
├── .gitignore
├── .data/                 # 运行时数据（token、缓存）
└── src/
    ├── __init__.py
    ├── config.py           # 字段映射 + 心率区间 + 默认配置
    ├── data_fetcher.py     # Garmin Connect API 数据获取
    ├── data_processor.py   # 数据清洗 + 字段映射 + 校验
    ├── classifier.py       # 心率区间 + 跑步类型分类
    ├── chart_generator.py   # Plotly 交互式图表（9 个独立图表）
    ├── report_generator.py # Jinja2 HTML 报告生成
    ├── pdf_generator.py    # Playwright PDF 生成
    ├── deep_analyzer.py    # 深度分析器 + LLM 报告生成
    └── analysis_report.py  # 深度分析 HTML 报告生成
```

## 数据流

```
Garmin API → DataFetcher → DataProcessor → Classifier → ChartGenerator → ReportGenerator
                ↓              ↓              ↓             ↓                ↓
           自动登录        字段映射        数据清洗      9 个图表         HTML 报告
           增量拉取        类型转换        异常检测      功率分析         移动端友好
           限流处理        完整性校验      智能分类      心率区间         自动备份
                                                        ↓
                                              DeepAnalyzer → AI 教练建议
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
- **PDF 报告**: `~/Documents/Run/PowerFun.pdf`
- **深析报告**: `~/Documents/Run/PowerFun_Reports/run_analysis_YYYYMMDD.html`
- **清洗后 CSV**: `~/Documents/Run/running_data_cleaned.csv`
- **状态文件**: `.data/last_fetch.json`

## 注意事项

- Garmin 账号密码通过命令行参数传入，不会持久化存储
- 限流时自动等待 1 小时后重试（指数退避）
- 数据目录 `.data/` 已加入 `.gitignore`
- 心率区间分布使用 Garmin 官方 `hrTimeInZone_1~5` 数据
- 配速数据为关键数据，缺失时会报错退出

## License

MIT
