"""Pa:Hr 统一选段、负向漂移边界与 analysis_hash 缓存测试（5.0 第一批 PRD 10.2/10.3）"""

import json

import pandas as pd
import pytest

import main
from main import LLM_PROMPT_VERSION
from src.deep_analyzer import DeepRunAnalyzer, select_pa_hr_scope


def _laps(n=10, dist=1000, dur=300, hr=150):
    return [{'lap_index': i, 'distance_m': dist, 'duration_sec': dur, 'avg_hr': hr}
            for i in range(1, n + 1)]


def _row(category, lap_start=None, lap_end=None):
    return pd.Series({'category': category,
                      'pa_hr_lap_start': lap_start, 'pa_hr_lap_end': lap_end})


def _analyzer(category, laps, lap_start=None, lap_end=None):
    az = DeepRunAnalyzer(pd.DataFrame(), raw_laps=laps)
    return az, _row(category, lap_start, lap_end)


# ------------------------------------------------------------------
# 统一选段规则
# ------------------------------------------------------------------
def test_normal_category_uses_full_activity():
    laps = _laps()
    sel = select_pa_hr_scope('easy_run', laps)
    assert sel['scope'] == 'full_activity'
    assert sel['segment_laps'] is None and sel['reason'] is None
    assert sel['laps'] is laps  # 原样整场输入，保持现状


def test_tempo_missing_segment_not_calculated():
    sel = select_pa_hr_scope('tempo_run', _laps())
    assert sel['scope'] == 'not_applicable'
    assert sel['reason'] == 'missing_manual_segment'


def test_tempo_uses_manual_segment_only():
    laps = _laps()
    sel = select_pa_hr_scope('tempo_run', laps, 4, 9)
    assert sel['scope'] == 'manual_segment'
    assert sel['segment_laps'] == [4, 9]
    assert [l['lap_index'] for l in sel['laps']] == [4, 5, 6, 7, 8, 9]


def test_tempo_segment_without_matching_laps():
    sel = select_pa_hr_scope('tempo_run', _laps(3), 4, 9)
    assert sel['scope'] == 'not_applicable'
    assert sel['reason'] == 'insufficient_lap_data'


def test_intensity_default_not_applicable():
    sel = select_pa_hr_scope('intensity_run', _laps())
    assert sel['scope'] == 'not_applicable'
    assert sel['reason'] == 'interval_not_applicable'


def test_intensity_explicit_segment_only_that_segment():
    laps = _laps()
    sel = select_pa_hr_scope('intensity_run', laps, 2, 5)
    assert sel['scope'] == 'manual_segment'
    assert [l['lap_index'] for l in sel['laps']] == [2, 3, 4, 5]


def test_manual_segment_failure_never_falls_back_to_full():
    """节奏跑人工段有效距离不足 3km：不计算且不回退整场"""
    laps = _laps(10, dist=1000)[:2]  # 仅 2 km
    az, row = _analyzer('tempo_run', laps, 1, 2)
    pa, ctx = az._calc_pa_hr_scoped(row)
    assert pa is None
    assert ctx == {'scope': 'not_applicable', 'segment_laps': [1, 2], 'reason': 'insufficient_lap_data'}


def test_intensity_not_applicable_zero_not_used():
    az, row = _analyzer('intensity_run', _laps())
    pa, ctx = az._calc_pa_hr_scoped(row)
    assert pa is None
    assert ctx['reason'] == 'interval_not_applicable'


def test_normal_category_pa_hr_unchanged():
    """普通课型整场 Pa:Hr 与直接 _calc_pa_hr 结果一致（输入与公式不变）"""
    laps = _laps(10, dur=310, hr=150)
    az, row = _analyzer('aerobic_run', laps)
    pa, ctx = az._calc_pa_hr_scoped(row)
    direct = az._calc_pa_hr(laps)
    assert pa['pa_hr_pct'] == direct['pa_hr_pct']
    assert pa['scope'] == 'full_activity'
    assert ctx['reason'] is None


# ------------------------------------------------------------------
# 历史趋势图与当前活动共用同一选段
# ------------------------------------------------------------------
def test_history_chart_shares_selection_and_excludes_not_applicable():
    class _StubFetcher:
        def __init__(self, laps_by_id):
            self._laps = laps_by_id

        def _load_lap_cache(self, activity_id):
            return self._laps.get(activity_id, [])

        def close(self):
            pass

    df = pd.DataFrame({
        'activity_id': [1, 2, 3, 4],
        'category': ['easy_run', 'intensity_run', 'tempo_run', 'easy_run'],
        'category_color': ['#808080', '#FFA500', '#32CD32', '#808080'],
        'category_icon': ['😌', '🔥', '⚡', '😌'],
        'distance': [5.0, 5.0, 6.0, 5.0],
        'min_temperature': [20.0, 20.0, 20.0, 20.0],
        'max_temperature': [22.0, 22.0, 22.0, 22.0],
        'pa_hr_lap_start': [None, None, 2, None],
        'pa_hr_lap_end': [None, None, 4, None],
        'date': pd.to_datetime(['2026-09-01', '2026-09-10', '2026-09-20', '2026-09-30']),
    })
    # 间歇跑（无人工段）必须被统一选段排除；节奏跑使用人工段（2—4 圈）仍可出点
    fetcher = _StubFetcher({1: _laps(5), 2: _laps(5), 3: _laps(6), 4: _laps(5)})
    fig = main._build_pa_hr_history_chart(df, 99, pd.Timestamp('2026-10-01'), 188, 60, fetcher)
    assert fig, '至少 3 个有效历史点应出图'
    fig_str = json.dumps(fig, ensure_ascii=False)
    assert 'intensity_run' not in fig_str, '间歇跑不得进入历史趋势点'
    assert fig_str.count('easy_run') >= 2
    assert 'tempo_run' in fig_str


# ------------------------------------------------------------------
# 负向漂移边界（-5.00 触发 / -4.99 不触发 / 正值不触发 / None 跳过）
# ------------------------------------------------------------------
def _issues_for_pa(pa_dict):
    az = DeepRunAnalyzer(pd.DataFrame())
    return az._detect_issues(pd.Series({'category': 'unknown_type'}), {'pa_hr': pa_dict})


def test_negative_drift_boundary_minus_500_triggers():
    issues = _issues_for_pa({'pa_hr_pct': -5.00, 'verdict': '有明显漂移'})
    drift = [i for i in issues if '心率漂移' in i['title']]
    assert len(drift) == 1
    assert '-5.0%' in drift[0]['title'] and '阈值 -5%' in drift[0]['title']
    assert '效率下降' in drift[0]['evidence'] and '+' not in drift[0]['title'].split('：')[1][:5]


def test_negative_drift_boundary_minus_499_not_triggered():
    assert _issues_for_pa({'pa_hr_pct': -4.99, 'verdict': '正常'}) == []


def test_positive_pa_hr_not_triggered():
    assert _issues_for_pa({'pa_hr_pct': 6.0, 'verdict': '有明显漂移'}) == []


def test_missing_pa_hr_skipped():
    assert _issues_for_pa(None) == []


# ------------------------------------------------------------------
# analysis_hash 缓存（临时 POWERFUN_CACHE_DIR / POWERFUN_LLM_RUNTIME_DIR）
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
1. **问题**：影响……；改进：……

<<<BRIEF>>>测试简报内容<<<END>>>
"""


def _sample_analysis(category='easy_run', segment=None, percentile=70):
    pa = None
    if segment:
        pa = {'pa_hr_pct': -6.1, 'scope': 'manual_segment', 'segment_laps': segment}
    return {
        'raw_data': {'activity_id': 123, 'category': category, 'category_name': 'x'},
        'summary': {'dominant_zone': 'Z2-有氧耐力', 'zone_pct': {}},
        'intensity': {},
        'efficiency': {},
        'comparison': {'percentile': {'value': percentile, 'sample_size': 30,
                                      'rank_label': f'P{percentile} 正常'}},
        'findings': [],
        'laps': {},
        'pa_hr': pa,
        'pa_hr_context': {'scope': 'full_activity', 'segment_laps': None, 'reason': None},
        'issues': [],
    }


@pytest.fixture
def iso_dirs(tmp_path, monkeypatch):
    cache = tmp_path / 'cache'
    runtime = tmp_path / 'runtime'
    cache.mkdir()
    runtime.mkdir()
    monkeypatch.setitem(main.DEFAULT_CONFIG, 'cache_dir', str(cache))
    monkeypatch.setitem(main.DEFAULT_CONFIG, 'llm_runtime_dir', str(runtime))
    return cache, runtime


def _write_cache(cache, data, note='备注', model='KimiWork'):
    h = main._analysis_hash(data)
    main._write_llm_cache(main._llm_cache_path(123), note, model, GOOD_RESPONSE, analysis_hash=h)
    return h


def test_cache_hit_same_analysis_data(iso_dirs):
    cache, _ = iso_dirs
    data = _sample_analysis(segment=[4, 9])
    _write_cache(cache, data)
    report, model = main._resolve_llm_report(
        pd.DataFrame(), data, 123, user_note='备注', on_miss='skip')
    assert '小结内容' in report and model == 'KimiWork'
    assert data['brief_summary'] == '测试简报内容'  # BRIEF 块解析后回填


@pytest.mark.parametrize('mutate', [
    lambda d: d['raw_data'].update(category='tempo_run'),               # 仅人工课型变化
    lambda d: d['pa_hr'].update(segment_laps=[5, 9]),                   # 仅 Pa:Hr 工作段变化
    lambda d: d['pa_hr'].update(pa_hr_pct=-6.2),                        # 仅 Pa:Hr 数值变化
    lambda d: d['comparison']['percentile'].update(value=71),           # 仅基线/比较结果变化
])
def test_cache_miss_on_analysis_fact_change(iso_dirs, mutate):
    """分析事实任一变化都必须未命中，且 Prompt 版本保持 13
    （旧值 12 → 新值 13：5.0.1 PRD 7.3 要求版本升级确保 5.0 旧 response 安全未命中）"""
    cache, runtime = iso_dirs
    data = _sample_analysis(segment=[4, 9])
    _write_cache(cache, data)
    changed = _sample_analysis(segment=[4, 9])
    mutate(changed)
    report, model = main._resolve_llm_report(
        pd.DataFrame(), changed, 123, user_note='备注', on_miss='skip')
    assert report is None and model is None
    assert LLM_PROMPT_VERSION == 14  # 5.0.2 PRD 10.3：13→14（断言更新记录：旧值 13 → 新值 14 → PRD 10.3）


def test_old_three_line_format_safely_misses(iso_dirs):
    """旧三行 frontmatter 无 analysis_hash：按未命中处理，不报错、不删除"""
    cache, _ = iso_dirs
    old = cache / 'llm' / 'llm_123.md'
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text('user_note_hash: \nmodel: KimiWork\nprompt_version: 12\n\n旧点评', encoding='utf-8')
    report, model = main._resolve_llm_report(
        pd.DataFrame(), _sample_analysis(), 123, user_note=None, on_miss='skip')
    assert report is None
    assert old.exists()  # 旧文件未被删除


def test_response_analysis_hash_mismatch_rejected(iso_dirs, caplog):
    """response 的 analysis_hash 不匹配：拒绝写缓存和正式报告"""
    import io
    cache, runtime = iso_dirs
    req_dir = runtime / '123'
    req_dir.mkdir(parents=True)
    (req_dir / 'response.md').write_text(GOOD_RESPONSE, encoding='utf-8')
    (req_dir / 'context.json').write_text(json.dumps({
        'activity_id': '123', 'user_note_hash': main._user_note_hash('备注'),
        'prompt_version': LLM_PROMPT_VERSION, 'analysis_hash': '0' * 64}), encoding='utf-8')
    with caplog.at_level('ERROR'), pytest.raises(SystemExit):
        main._resolve_llm_report(pd.DataFrame(), _sample_analysis(), 123,
                                 user_note='备注', response_path=str(req_dir / 'response.md'))
    assert 'analysis_hash' in caplog.text
    # 未写缓存、未生成正式报告
    assert not (cache / 'llm' / 'llm_123.md').exists()


def test_response_context_includes_analysis_hash(iso_dirs):
    """两阶段第一阶段：context.json 记录 analysis_hash，供第二阶段校验"""
    cache, runtime = iso_dirs
    data = _sample_analysis()
    with pytest.raises(SystemExit) as exc_info:  # on_miss='exit'：prepare 后退出
        main._resolve_llm_report(pd.DataFrame(), data, 123,
                                 user_note='备注', on_miss='exit')
    assert exc_info.value.code == 0
    ctx = json.loads((runtime / '123' / 'context.json').read_text(encoding='utf-8'))
    assert ctx['analysis_hash'] == main._analysis_hash(data)


def test_note_semantics_preserved(iso_dirs):
    """未显式传 note 时保持现有复用语义；传不同 note 必须未命中"""
    cache, _ = iso_dirs
    data = _sample_analysis()
    _write_cache(cache, data, note='备注A')
    # 不传 note：复用缓存（现有语义）
    report, _ = main._resolve_llm_report(
        pd.DataFrame(), data, 123, user_note=None, on_miss='skip')
    assert report is not None
    # 传不同 note：未命中
    report, _ = main._resolve_llm_report(
        pd.DataFrame(), data, 123, user_note='备注B', on_miss='skip')
    assert report is None


def test_analysis_hash_stable_and_computed_before_brief():
    """哈希稳定；brief_summary 属于后加字段，_resolve_llm_report 在写入前计算哈希"""
    data = _sample_analysis()
    h1 = main._analysis_hash(data)
    h2 = main._analysis_hash(_sample_analysis())
    assert h1 == h2 and len(h1) == 64
    data['brief_summary'] = '后写入的简报'
    assert main._analysis_hash(data) != h1  # 已含 brief 的 dict 哈希不同 → 必须先算后写
