# 🏃 PowerFun - 跑步数据分析

> 整合 Garmin Connect (China) 数据获取 + 跑步数据分析 + 可视化报告生成

**版本**: v2.0 (2026-04-25)

## 🚀 版本 2.0 新特性

- **⚡ 功率数据分析**: 支持Garmin功率数据，生成功率分布图
- **👟 步频与垂直振幅**: 完整支持步频(spm)和垂直振幅比(%)分析
- **🛡️ 安全增强**: XSS防护、安全token存储、HTML转义
- **📁 智能文件管理**: 主报告`PowerFun.html` + 自动备份策略
- **🎯 精准心率区间**: 动态计算心率区间，支持自定义最大/静息心率
- **📱 移动端优化**: 响应式HTML报告，表格标题智能截断(25字符)

## 功能特性

- **🔐 自动登录**: Garmin Connect China 区域 SSO 登录
- **📊 智能拉取**: 首次全部拉取，后续增量更新，自动去重
- **🧹 数据清洗**: 完整的字段映射、类型转换、异常检测
- **❤️ 心率区间**: Z1-Z5 五区间分析（基于最大心率或心率储备）
- **⏱️ 配速趋势**: 移动平均、趋势判断（提升/持平/下降）
- **📈 可视化**: Plotly 交互式仪表盘（6 图布局）
- **📄 HTML 报告**: 完整跑步分析报告，移动端友好

## 快速开始

### 安装

```bash
cd /Users/jarvis/Projects/skills/PowerFun
pip install -r requirements.txt
```

### 运行

```bash
# 首次运行（需要账号密码）
python main.py --email your_email@example.com --password your_password

# 后续运行（使用已保存的token）
python main.py

# 拉取指定天数数据
python main.py --days 90

# 指定最大心率（用于心率区间计算）
python main.py --max-hr 180 --resting-hr 60

# 仅拉取数据，不生成报告
python main.py --dry-run
```

## 项目结构

```
PowerFun/
├── main.py                 # 主程序入口（7 步流程）
├── requirements.txt        # Python 依赖
├── SKILL.md               # OpenClaw 技能说明
├── README.md              # 项目文档
├── VERSION                # 版本文件
├── .gitignore
└── src/
    ├── __init__.py
    ├── config.py           # 字段映射 + 心率区间 + 默认配置
    ├── data_fetcher.py     # Garmin Connect API 数据获取
    ├── data_processor.py   # 数据清洗 + 字段映射 + 校验
    ├── classifier.py       # 心率区间 + 跑步类型分类
    ├── chart_generator.py   # Plotly 交互式图表（9个独立图表）
    └── report_generator.py # Jinja2 HTML 报告生成
```

## 数据流

```
Garmin API → DataFetcher → DataProcessor → Classifier → ChartGenerator → ReportGenerator
                ↓              ↓              ↓             ↓                ↓
           自动登录        字段映射        数据清洗      9个交互式图表    HTML 报告
           增量拉取        类型转换        异常检测      功率分析        移动端友好
           限流处理        完整性校验      智能分类      心率区间        自动备份
```

## 字段映射

完整字段映射见 `src/config.py` 中的 `FIELD_MAPPING` 字典。

| 跑分期望字段 | Garmin 源字段 | 转换方式 |
|-------------|--------------|---------|
| date | startTimeLocal | 解析 datetime |
| distance | distance_km | 直接映射 |
| avg_hr | avg_hr | 直接映射 |
| avg_pace | pace_min_per_km | min/km → mm:ss |
| best_pace | maxSpeed | km/h → mm:ss |
| duration | elapsed_min | 分钟 → hh:mm:ss |
| ... | ... | ... |

## 输出

- **主HTML报告**: `/Users/jarvis/Documents/Run/PowerFun.html`
- **自动备份**: `/Users/jarvis/Documents/Run/PowerFun_Reports/PowerFun_backup_*.html`
- **清洗后CSV**: `/Users/jarvis/Documents/Run/running_data_cleaned.csv`
- **原始活动数据**: `/Users/jarvis/Documents/Run/all_running_activities.json`
- **状态文件**: `~/.powerfun/last_fetch.json`

## 注意事项

- Garmin 账号密码通过命令行参数传入，不会持久化存储
- 限流时自动等待 1 小时后重试（指数退避）
- 数据目录 `~/.powerfun/` 已加入 `.gitignore`

## License

MIT
