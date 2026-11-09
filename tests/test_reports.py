"""报告与两阶段编排测试（PRD 6.3 + A 组 5/6）

原则：
- 历史缓存场景显式使用 2026-11-06（对应活动 659451010），不假定 latest 永远是旧活动；
- 两阶段编排测试通过 POWERFUN_CACHE_DIR / POWERFUN_LLM_RUNTIME_DIR 环境变量
  将 LLM 缓存与运行时请求目录隔离到临时目录，不删除、移动或改写正式 cache/llm；
- latest 场景的动态行为在验收脚本中覆盖（见 MIGRATION_COMPLETION_REPORT.md）。
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import main
from conftest import PROJECT_ROOT, REPORTS_DIR

PY = str(PROJECT_ROOT / '.venv' / 'bin' / 'python')
MAIN_PY = str(PROJECT_ROOT / 'main.py')

# 历史验收场景：2026-11-06 活动（659451010）+ 附录原体感
HISTORIC_DATE = '2026-11-06'
HISTORIC_ID = 659451010

USER_NOTE = ("连续出差+应酬，导致不仅训练进度滞后，还拉跨了运动状态。今天一起步就感觉心率不对，"
             "一直找不到状态。第4公里开始4:55节奏，原来想坚持下看看能不能跑8KM的节奏跑，"
             "但坚持了6KM节奏跑配速之后，感觉不太行了。剩余6KM恢复跑，一时也没找到节奏，"
             "一直到最后4KM开始，慢慢找回状态，但感觉仍然比上周状态差。目前计划明后天跑一次有氧慢跑，"
             "找找状态，如果状态找回，下周二三再试一次节奏跑。")


def _run(args, env_extra=None, timeout=600):
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [PY, MAIN_PY] + args,
        capture_output=True, text=True, timeout=timeout,
        cwd=str(PROJECT_ROOT), env=env,
    )


@pytest.fixture(scope='module')
def generated(tmp_path_factory):
    """在隔离目录生成综合报告 + 历史活动深析（正式缓存命中，不改正式输出）"""
    out = tmp_path_factory.mktemp('reports-out')
    proc = _run(['--load-parquet', '--deep-analyze', HISTORIC_DATE,
                 '--user-note', USER_NOTE, '--output', str(out)])
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert 'LLM_CACHE_HIT' in proc.stdout
    return Path(out)


def test_main_report_ten_charts(generated):
    """综合报告生成 10 个非空图表"""
    html = (generated / 'PowerFun.html').read_text(encoding='utf-8')
    assert html.count('Plotly.newPlot(') == 10


def test_deep_report_sections_and_brief(generated):
    """深析六小节及 BRIEF 完整"""
    deep = list((generated / 'PowerFun_Reports').glob(f'run_analysis_*_{HISTORIC_ID}.html'))
    assert len(deep) == 1
    html = deep[0].read_text(encoding='utf-8')
    for emoji_title in ['🔥 本次跑步小结', '🏃 强度与负荷分析', '⚙️ 技术效率分析',
                        '📈 能力变化趋势', '🔄 分圈表现分析', '🛠️ 问题与修正']:
        assert f'<h2>{emoji_title}</h2>' in html
    # BRIEF 简报解析自缓存并回填到总结区
    content, _ = main._read_llm_cache(
        PROJECT_ROOT / 'cache' / 'llm' / f'llm_{HISTORIC_ID}.md', USER_NOTE)
    from src.deep_analyzer import LLMReportGenerator
    _, brief = LLMReportGenerator._parse_brief(content)
    assert brief
    assert brief[:20] in html


def test_no_cdn_in_new_reports(generated):
    """HTML 无 Plotly、jQuery、DataTables CDN 地址"""
    for f in [generated / 'PowerFun.html'] + \
             list((generated / 'PowerFun_Reports').glob('*.html')):
        html = f.read_text(encoding='utf-8')
        assert 'cdn.plot.ly' not in html
        assert 'cdn.bootcdn.net' not in html
        assert 'code.jquery.com' not in html


def test_local_assets_exist(generated):
    """本地资源存在且相对链接有效（移动整个目录仍可用）"""
    assets = generated / 'assets'
    for name in ['plotly-2.27.0.min.js', 'jquery.min.js', 'jquery.dataTables.min.js',
                 'jquery.dataTables.min.css', 'datatables-zh.json']:
        assert (assets / name).exists(), f"缺资源: {name}"
    assert (assets / 'plotly-2.27.0.min.js').stat().st_size > 1_000_000


def test_historical_deep_links_valid():
    """正式 reports/ 中综合报告的历史深析链接有效"""
    html = (REPORTS_DIR / 'PowerFun.html').read_text(encoding='utf-8')
    links = re.findall(r'PowerFun_Reports/(run_analysis_[^"\']+\.html)', html)
    assert links, "综合报告中没有历史深析链接"
    for link in set(links):
        assert (REPORTS_DIR / 'PowerFun_Reports' / link).exists(), f"链接失效: {link}"


def test_no_pdf_output(generated):
    """全流程无 PDF 输出"""
    assert list(generated.rglob('*.pdf')) == []


def test_outputs_no_external_path_leak(generated):
    """输出 HTML 不泄漏工作区外路径（home/iCloud 等）"""
    for f in [generated / 'PowerFun.html'] + \
             list((generated / 'PowerFun_Reports').glob('*.html')):
        html = f.read_text(encoding='utf-8')
        assert '/Users/jarvis' not in html
        assert 'Mobile Documents' not in html
        assert 'iCloud' not in html


# ------------------------------------------------------------------
# response 校验（A 组 6）
# ------------------------------------------------------------------
GOOD_RESPONSE = """## 🔥 本次跑步小结
小结内容。

## 🏃 强度与负荷分析
强度内容。

## ⚙️ 技术效率分析
技术内容。

## 📈 能力变化趋势
趋势内容。

## 🔄 分圈表现分析
分圈内容。

## 🛠️ 问题与修正
修正内容。

<<<BRIEF>>>测试简报内容<<<END>>>
"""


def test_validate_response_ok():
    assert main._validate_llm_response(GOOD_RESPONSE) == []


def test_validate_response_missing_section():
    bad = GOOD_RESPONSE.replace('## 🛠️ 问题与修正', '## 🛠️ 问题与修改')
    problems = main._validate_llm_response(bad)
    assert problems and any('问题与修正' in p for p in problems)


def test_validate_response_wrong_order():
    # 调换小节顺序
    bad = GOOD_RESPONSE.replace(
        '## 🏃 强度与负荷分析', '## 📈 能力变化趋势').replace(
        '## 📈 能力变化趋势\n趋势内容。', '## 🏃 强度与负荷分析\n强度内容。', 1)
    problems = main._validate_llm_response(bad)
    assert problems


def test_validate_response_missing_brief():
    bad = GOOD_RESPONSE.replace('<<<BRIEF>>>测试简报内容<<<END>>>', '')
    problems = main._validate_llm_response(bad)
    assert any('BRIEF' in p for p in problems)


# ------------------------------------------------------------------
# 两阶段编排（A 组 5）：缓存隔离在临时目录，完整走 REQUEST → render → HIT
# ------------------------------------------------------------------
@pytest.fixture(scope='module')
def llm_cycle(tmp_path_factory):
    """在临时缓存/运行时目录上跑完整两阶段循环，正式 cache/llm 只读不参与"""
    iso = tmp_path_factory.mktemp('llm-iso')
    iso_cache = iso / 'cache'
    iso_runtime = iso / 'runtime'
    iso_cache.mkdir()
    env = {
        'POWERFUN_CACHE_DIR': str(iso_cache),
        'POWERFUN_LLM_RUNTIME_DIR': str(iso_runtime),
    }
    out = iso / 'out'

    # 第一阶段：隔离缓存为空 → LLM_REQUEST_REQUIRED
    p1 = _run(['--load-parquet', '--deep-analyze', HISTORIC_DATE,
               '--user-note', USER_NOTE, '--output', str(out)], env_extra=env)
    assert p1.returncode == 0
    assert 'LLM_REQUEST_REQUIRED=' in p1.stdout
    req_line = [l for l in p1.stdout.splitlines() if l.startswith('LLM_REQUEST_REQUIRED=')][0]
    req_path = Path(req_line.split('=', 1)[1])
    assert str(req_path).startswith(str(iso_runtime))  # 请求写在隔离目录
    assert req_path.exists()
    ctx = main.json.loads((req_path.parent / 'context.json').read_text())
    assert str(ctx['activity_id']) == str(HISTORIC_ID)
    assert ctx['prompt_version'] == 12
    assert ctx['user_note_hash'] == main._user_note_hash(USER_NOTE)

    # 第二阶段：response → 渲染，缓存写入隔离目录
    resp_path = req_path.parent / 'response.md'
    resp_path.write_text(GOOD_RESPONSE, encoding='utf-8')
    p2 = _run(['--load-parquet', '--deep-analyze', HISTORIC_DATE,
               '--user-note', USER_NOTE, '--output', str(out),
               '--llm-response', str(resp_path)], env_extra=env)
    assert p2.returncode == 0, p2.stderr[-2000:]
    deep = list((out / 'PowerFun_Reports').glob(f'run_analysis_*_{HISTORIC_ID}.html'))
    assert len(deep) == 1
    assert '测试简报内容' in deep[0].read_text(encoding='utf-8')

    # 缓存写入隔离 cache（model=KimiWork）；正式缓存在整个循环前后保持逐字节不变
    iso_cache_file = iso_cache / 'llm' / f'llm_{HISTORIC_ID}.md'
    written = iso_cache_file.read_text(encoding='utf-8')
    assert written.split('\n')[1] == 'model: KimiWork'
    official_file = PROJECT_ROOT / 'cache' / 'llm' / f'llm_{HISTORIC_ID}.md'
    official_before = official_file.read_bytes()

    # 第三次运行：隔离缓存命中
    p3 = _run(['--load-parquet', '--deep-analyze', HISTORIC_DATE,
               '--user-note', USER_NOTE, '--output', str(out)], env_extra=env)
    assert p3.returncode == 0
    assert 'LLM_CACHE_HIT' in p3.stdout

    # 正式缓存未被读取改写之外的操作影响，逐字节不变
    assert official_file.read_bytes() == official_before

    yield out


def test_llm_cycle_cache_hit_after_render(llm_cycle):
    html = (llm_cycle / 'PowerFun_Reports' / f'run_analysis_20261106_{HISTORIC_ID}.html') \
        .read_text(encoding='utf-8')
    assert '<h2>🔥 本次跑步小结</h2>' in html


def test_reject_wrong_activity_response(tmp_path):
    """错 activity_id 的 response 被拒绝，不写缓存；测试自建前置状态，级联失败"""
    req_dir = tmp_path / '999'
    req_dir.mkdir()
    (req_dir / 'context.json').write_text(main.json.dumps({
        'activity_id': 999, 'user_note_hash': main._user_note_hash(USER_NOTE),
        'prompt_version': 12}))
    resp = req_dir / 'response.md'
    resp.write_text(GOOD_RESPONSE, encoding='utf-8')

    iso_cache = tmp_path / 'iso-cache'
    iso_cache.mkdir()
    env = {
        'POWERFUN_CACHE_DIR': str(iso_cache),
        'POWERFUN_LLM_RUNTIME_DIR': str(tmp_path / 'iso-runtime'),
    }
    proc = _run(['--load-parquet', '--deep-analyze', HISTORIC_DATE,
                 '--user-note', USER_NOTE,
                 '--llm-response', str(resp), '--output', str(tmp_path / 'out')],
                env_extra=env)
    assert proc.returncode != 0
    assert '不一致' in proc.stderr
    # 隔离缓存目录中未写入任何缓存
    assert list(iso_cache.rglob('llm_*.md')) == []
