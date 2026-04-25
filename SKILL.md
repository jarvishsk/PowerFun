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
- 📈 **可视化**: Plotly 交互式仪表盘
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
├── main.py                 # 主程序入口
├── requirements.txt        # 依赖
├── SKILL.md               # 技能说明
├── README.md              # 项目文档
├── .gitignore
└── src/
    ├── __init__.py
    ├── config.py           # 字段映射 + 配置
    ├── data_fetcher.py     # Garmin 数据获取
    ├── data_processor.py   # 数据清洗 + 字段映射
    ├── analyzer.py         # 心率区间分析
    ├── visualizer.py       # Plotly 图表生成
    └── report_generator.py # HTML 报告
```

## 状态管理

状态文件存储在 `~/.powerfun/last_fetch.json`，记录上次拉取时间和数据量。

## 输出

报告默认保存在 `~/.powerfun/reports/` 目录。

## 注意事项

- Garmin 账号密码通过命令行参数传入，不会持久化存储
- 限流时自动等待 1 小时后重试
- 支持指数退避重试机制
