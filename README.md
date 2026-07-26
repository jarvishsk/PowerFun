# 🏃 PowerFun - 跑步数据分析

> 整合 Garmin Connect (China) 数据获取 + 跑步数据分析 + 可视化报告生成

## 功能特性

- **🔐 自动登录**: Garmin Connect China 区域 SSO 登录，首次输入账号密码后自动保存 token
- **📊 智能拉取**: 首次全部拉取，后续增量更新，自动去重和限流处理
- **🧹 数据清洗**: 完整的字段映射、类型转换、异常检测
- **❤️ 心率区间**: 基于 Karvonen HRR（心率储备法），支持 Z1-Z5 五区间分析，使用 Garmin 官方 `hrTimeInZone_1~5` 原生数据
- **⏱️ 配速趋势**: 移动平均、趋势判断（提升/持平/下降）
- **📈 可视化**: 9 个 Plotly 交互式图表（配速-心率趋势、心率分布、功率分布、训练效果等）
- **📄 综合分析报告**: HTML + PDF 格式，包含详细数据表、可视化图表、月度统计，移动端友好
- **🔍 深度分析报告**: 单次跑步深度分析（HTML + PDF + iCloud 同步），包含能力对比、分圈表现、AI 教练建议

## 数据流

### 正常模式 / --load-parquet

```
数据管线:  API → 清洗 → 过滤 → 心率分类 → 跑分类 → 保存 parquet
                                                        ↓
报告管线:  Step 7: 深析报告（最近一次跑步，HTML + PDF）
          Step 8: 9 个 Plotly 交互式图表
          Step 9: HTML 综合报告（含深析链接）
          Step 10: PDF 综合报告
```

### --deep-analyze 模式

```
数据管线:  读取 parquet
          Step 7: 指定跑步的深析报告（HTML + PDF）
          Step 8: 9 个 Plotly 交互式图表
          Step 9: HTML 综合报告（含深析链接）
         Step 10: 跳过综合报告 PDF
```

## 快速开始

### 安装

```bash
cd PowerFun
pip install -r requirements.txt
```

### 首次运行

```bash
python main.py --email your_email@example.com --password your_password
```

登录后 token 自动保存，后续运行无需输入密码。

### 日常使用

```bash
# 从 Garmin API 拉取最新数据并生成完整报告（深析 + 综合）
python main.py

# 跳过 API 拉取，直接从已有数据生成报告
python main.py --load-parquet

# 查看指定跑步的深度分析报告（同时更新综合报告链接）
python main.py --deep-analyze "2026-05-05"

# 对所有跑步批量生成深析报告
python main.py --deep-analyze-all

# 指定心率参数（可选，默认从配置文件读取）
python main.py --max-hr 180 --resting-hr 60
```

## 配置心率参数

打开 `src/config.py`，找到文件顶部的 `USER_CONFIG`：

```python
USER_CONFIG = {
    'max_hr': 188,        # 最大心率（实测值）
    'resting_hr': 60,     # 静息心率（实测值）
}
```

按你的实测值修改这两个参数即可，所有模块自动同步，无需在其他地方修改。

> 心率区间使用 **Karvonen HRR（心率储备法）** 计算，区间百分比为固定值，无需也不建议修改。

## 输出文件

| 文件 | 路径 |
|------|------|
| 综合分析报告 (HTML) | `~/Documents/Run/PowerFun.html` |
| 综合分析报告 (PDF) | `~/Documents/Run/综合分析报告.pdf` |
| 深度分析报告 (HTML) | `~/Documents/Run/PowerFun_Reports/run_analysis_YYYYMMDD.html` |
| 深度分析报告 (PDF) | `~/Documents/Run/PowerFun_Reports/深度分析报告_YYYYMMDD.pdf` |
| 清洗后数据 (CSV) | `~/Documents/Run/running_data_cleaned.csv` |

PDF 报告会自动同步到 iCloud。

## 项目结构

```
PowerFun/
├── main.py                 # 主程序入口
├── requirements.txt        # Python 依赖
├── README.md              # 项目文档
├── SKILL.md               # OpenClaw 技能说明
├── VERSION                # 版本文件
├── .gitignore
├── .data/                 # 运行时数据（token、缓存，已忽略）
└── src/
    ├── config.py           # 用户配置 + 字段映射 + 系统参数
    ├── data_fetcher.py     # Garmin Connect API 数据获取
    ├── data_processor.py   # 数据清洗 + 字段映射 + 校验
    ├── classifier.py       # 心率区间 + 跑步类型分类
    ├── chart_generator.py   # Plotly 交互式图表
    ├── report_generator.py # HTML 报告生成
    ├── pdf_generator.py    # PDF 报告生成
    ├── deep_analyzer.py    # 深度分析器 + LLM 报告生成
    └── analysis_report.py  # 深度分析 HTML 报告生成
```

## 注意事项

- Garmin 账号密码通过命令行参数传入，不会持久化存储
- 限流时自动等待 1 小时后重试（指数退避）
- 配速数据为关键数据，缺失时会报错退出

## License

MIT
