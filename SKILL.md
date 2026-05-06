# PowerFun 跑步数据分析技能

完全独立的跑步数据分析技能，整合 Garmin Connect (China) 数据获取 + 跑步数据分析 + 可视化报告生成。

## 触发词

- `跑步分析`
- `分析今天跑步数据`
- `分析跑步数据`
- `跑分`
- `PowerFun`

## 功能

- 🔐 **自动登录**: Garmin Connect (China 区域) SSO 登录
- 📊 **智能拉取**: 首次全部拉取，后续增量更新
- 🧹 **数据清洗**: 字段映射、类型转换、异常检测
- ❤️ **心率区间**: Karvonen HRR 法，Z1-Z5 五区间（百分比固定，不可更改）
- ⏱️ **配速趋势**: 移动平均、趋势判断
- 📈 **可视化**: 9个Plotly交互式图表（图例居中、心率分布等）
- 📄 **HTML/PDF 报告**: 综合分析报告 + 深度分析报告（含 AI 教练建议）

## 配置

用户首次使用时，修改 `src/config.py` 顶部的 `USER_CONFIG`：

```python
USER_CONFIG = {
    'max_hr': 188,        # 最大心率（实测值）
    'resting_hr': 60,     # 静息心率（实测值）
}
```

心率参数修改后，其他所有代码自动同步，无需额外指定。

## 使用

```bash
# 首次运行（输入账号密码，登录后 token 自动保存）
python main.py --email YOUR_EMAIL --password YOUR_PASSWORD

# 后续运行（自动加载 token，无需密码）
python main.py

# 从 parquet 生成报告（跳过 API 拉取）
python main.py --load-parquet

# 单独深析指定日期
python main.py --deep-analyze "2026-05-03"

# 仅拉取数据
python main.py --dry-run
```

## 输出

- **综合报告**: `~/Documents/Run/PowerFun.html` + `综合分析报告.pdf`
- **深析报告**: `~/Documents/Run/PowerFun_Reports/run_analysis_YYYYMMDD.html` + `深度分析报告_YYYYMMDD.pdf`
- **iCloud 同步**: PDF 自动同步到 iCloud
