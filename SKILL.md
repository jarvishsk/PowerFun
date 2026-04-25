# PowerFun 跑步数据分析技能

完全独立的跑步数据分析技能，整合 Garmin Connect (China) 数据获取 + 跑步数据分析 + 可视化报告生成。

## 触发词

- `跑步分析`
- `跑步数据`
- `跑步报告`
- `跑分`
- `PowerFun`

## 功能

- 🔐 **自动登录**: Garmin Connect (China 区域) SSO 登录
- 📊 **智能拉取**: 首次全部拉取，后续增量更新
- 🧹 **数据清洗**: 字段映射、类型转换、异常检测
- ❤️ **心率区间**: Z1-Z5 五区间分析
- ⏱️ **配速趋势**: 移动平均、趋势判断
- 📈 **可视化**: 9个Plotly交互式图表（含功率分布、心率分布等）
- 📄 **HTML 报告**: 完整跑步分析报告

## 安装

```bash
cd /Users/jarvis/Projects/skills/PowerFun
pip install -r requirements.txt
```

## 使用

```bash
# 基本用法 (拉取最近 30 天)
python main.py --email YOUR_EMAIL --password YOUR_PASSWORD

# 指定天数
python main.py --email YOUR_EMAIL --password YOUR_PASSWORD --days 90

# 指定最大心率 (用于心率区间计算)
python main.py --email YOUR_EMAIL --password YOUR_PASSWORD --max-hr 180

# 仅拉取数据，不生成报告
python main.py --email YOUR_EMAIL --password YOUR_PASSWORD --dry-run

# 输出 JSON 数据
python main.py --email YOUR_EMAIL --password YOUR_PASSWORD --json-out data.json
```

## 项目结构

```
PowerFun/
├── main.py                 # 主程序入口（7步流程）
├── requirements.txt        # Python依赖
├── SKILL.md               # OpenClaw技能说明
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

## 状态管理

状态文件存储在 `~/.powerfun/last_fetch.json`，记录上次拉取时间和数据量。

## 输出

- **主HTML报告**: `/Users/jarvis/Documents/Run/PowerFun.html`
- **自动备份**: `/Users/jarvis/Documents/Run/PowerFun_Reports/`
- **清洗后CSV**: `/Users/jarvis/Documents/Run/running_data_cleaned.csv`

## 注意事项

- Garmin 账号密码通过命令行参数传入，不会持久化存储
- 限流时自动等待 1 小时后重试
- 支持指数退避重试机制
