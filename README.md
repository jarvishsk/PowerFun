# 🏃 PowerFun - 跑步数据分析

> 整合 Garmin Connect (China) 数据获取 + 跑步数据分析 + 可视化报告生成

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
# 基本用法（拉取最近 30 天）
python main.py --email your_email@example.com --password your_password

# 拉取 90 天数据
python main.py --email your_email@example.com --password your_password --days 90

# 指定最大心率（用于心率区间计算）
python main.py --email your_email@example.com --password your_password --max-hr 180

# 仅拉取数据，不生成报告
python main.py --email your_email@example.com --password your_password --dry-run
```

## 项目结构

```
PowerFun/
├── main.py                 # 主程序入口（5 步流程）
├── requirements.txt        # Python 依赖
├── SKILL.md               # OpenClaw 技能说明
├── README.md              # 项目文档
├── .gitignore
└── src/
    ├── __init__.py
    ├── config.py           # 字段映射 + 心率区间 + 默认配置
    ├── data_fetcher.py     # Garmin Connect API 数据获取
    ├── data_processor.py   # 数据清洗 + 字段映射 + 校验
    ├── analyzer.py         # 心率区间 + 配速趋势 + 月度统计
    ├── visualizer.py       # Plotly 交互式图表
    └── report_generator.py # Jinja2 HTML 报告
```

## 数据流

```
Garmin API → DataFetcher → DataProcessor → Analyzer → Visualizer → ReportGenerator
                ↓              ↓              ↓            ↓              ↓
           自动登录        字段映射        统计分析      Plotly 图     HTML 报告
           增量拉取        数据清洗        趋势判断      仪表盘        移动端友好
           限流处理        异常检测        区间分布
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

- **HTML 报告**: `~/.powerfun/reports/powerfun_report_YYYYMMDD_HHMMSS.html`
- **状态文件**: `~/.powerfun/last_fetch.json`
- **JSON 数据**: 可选 `--json-out` 参数导出

## 注意事项

- Garmin 账号密码通过命令行参数传入，不会持久化存储
- 限流时自动等待 1 小时后重试（指数退避）
- 数据目录 `~/.powerfun/` 已加入 `.gitignore`

## License

MIT
