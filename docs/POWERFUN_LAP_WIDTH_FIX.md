# PowerFun 每KM图表修复需求 v3

> 创建时间: 2026-05-05 17:48
> 项目位置: `/Users/jarvis/Projects/skills/PowerFun`

---

## 问题描述

当前模板 `src/analysis_report.py` 中，**每KM心率图表及其之后的所有内容**，页面宽度异常（脱离 `.container` 约束）。

## 根因分析

经过排查，发现 **HTML 模板中多了一个 `</div>` 闭合标签**。

具体位置：配速图的 `<script>` 标签之后，有一个多余的 `</div>`，它提前闭合了最外层的 `<div class="container">`，导致心率图及之后所有内容都渲染为全宽。

**当前模板结构（问题代码）**：
```html
    </div>                                    ← 配速 section 闭合（正常）
    {% if lap_pace_chart_html %}
    <script>
    ...
    </script>
    {% endif %}
    </div>                                    ← ← ← 这是多余的！闭合了 container
                                              ← 心率图从此处开始脱离容器
    {% if lap_hr_chart_html %}
    <div class="section">
        <h2>📊 每KM心率</h2>
        ...
    </div>
    ...
```

**正确结构应该是**：
- 配速 section 的 `</div>` 在第 202 行（正常闭合 section）
- script 标签不应该被额外 div 包裹
- 心率 section 应该独立存在，不受影响

## 修复方案

**文件**: `src/analysis_report.py`

删除配速图 script 块之后、心率 section 之前那行多余的 `</div>`。

具体来说，找到这段代码：
```
    })();
    </script>
    {% endif %}
    </div>              ← 删除这行
```

改为：
```
    })();
    </script>
    {% endif %}
```

## 验收标准

1. 重新生成 5月3日深析报告：`python3 main.py --load-parquet --deep-analyze 2026-05-03`
2. 打开 HTML 文件，检查：
   - 每KM心率图在容器内（宽度正常，不是全宽）
   - 对比分析、AI 教练点评等后续所有 section 都在容器内
   - 页脚 footer 居中
3. 语法检查通过
