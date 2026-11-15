"""比赛参照、技术解释与教练点评语义修复测试（5.0.2 PRD 第 11.1 节八类合成边界）

覆盖：
1. 同距离比赛成绩参照池纯净性（不混全马/10K/其他赛事；温度/功率/配速不同不排除）
2. 同距离历史 1/2/3 场整体比较行为（成绩比较允许、纯能力结论禁止）
3. 比赛分圈 3 样本中位线 vs 普通课型 3 样本无中位线；任何课型 <10 无 P20-P80
4. 比赛技术池不混全马/半马；步幅增加不得返回 improved；基线不足不得写「稳定」
5. 比赛 Pa:Hr≤-5%、负荷超近 4 次均值、max_hr 超配置 → 问题清单无旧三类；max_hr 进 data_notes
6. 非比赛相同信号保持既有探测行为（回归）
7. 无比赛计划禁止计划偏离；有计划、修改计划后 analysis_hash 必须变化
8. 赛段配速/心率/功率按 PRD 9.3 加权口径（非逐公里简单平均）

真实回放（PRD 11.2/11.3）由 .runtime/acceptance/race-coaching/replay_662381792.py 承担。
"""

import numpy as np
import pandas as pd
import pytest

from main import _analysis_hash
from src.deep_analyzer import (
    DeepRunAnalyzer,
    LLMReportGenerator,
    RACE_CATEGORIES,
    RACE_LAP_MEDIAN_MIN_SAMPLES,
)
from src.lap_history_stats import compute_per_km_history_stats
from src.race_plans import RacePlanError, compute_plan_evidence, load_race_plan

TARGET_DATE = '2026-11-15'
MILD = (22.0, 26.0)


# ------------------------------------------------------------------
# 构造工具
# ------------------------------------------------------------------
def _hist_lap(idx, pace=300.0, hr=150.0, dist=1000):
    return {'lap_index': idx, 'distance_m': dist,
            'pace_sec_per_km': pace, 'avg_hr': hr}


def _race_row(aid, date, category='half_marathon', hr=150.0, pace=300.0,
              temp=MILD, distance=21.1, duration_min=100.0, power=250.0,
              vr=7.0, gct=240.0, cadence=180.0, stride=95.0, max_hr=180.0,
              load=100.0, title=None):
    d = {'activity_id': aid, 'date': date, 'category': category,
         'avg_hr': hr, 'avg_pace_sec': pace, 'distance': distance,
         'duration_min': duration_min, 'avg_power': power,
         'vertical_ratio': vr, 'ground_contact_time': gct,
         'cadence': cadence, 'stride_length': stride,
         'max_hr': max_hr, 'training_load': load,
         'min_temperature': temp[0], 'max_temperature': temp[1],
         'elevation_gain': 50.0}
    if title:
        d['title'] = title
    return d


def _df(rows):
    df = pd.DataFrame(rows)
    df['date'] = pd.to_datetime(df['date'])
    df['_category_norm'] = df['category'].apply(
        lambda c: 'race' if c in ('full_marathon', 'half_marathon', 'race_event') else c)
    return df


def _target(**kw):
    kw.setdefault('hr', 160.0)
    kw.setdefault('pace', 310.0)
    return pd.Series(_race_row(999, TARGET_DATE, **kw))


def _analyzer(df, target=None, race_plan=None):
    t = target if target is not None else _target()
    return DeepRunAnalyzer(df, target_date=pd.Timestamp(TARGET_DATE),
                           max_hr=188, resting_hr=60, race_plan=race_plan), t


def _old_race_rows(n, category='half_marathon', days_back=200, **kw):
    base = pd.Timestamp(TARGET_DATE) - pd.Timedelta(days=days_back)
    return [_race_row(i + 1, base + pd.Timedelta(days=i), category=category, **kw)
            for i in range(n)]


# ------------------------------------------------------------------
# 11.1-1 同距离比赛成绩参照池纯净性
# ------------------------------------------------------------------
def test_race_pool_exact_category_no_contamination():
    """半马池只含历史半马：全马、10K（race_event）、其他距离半马记录不得混入；
    温度/功率/配速不同的半马必须留在池内（PRD 5.1/5.2）"""
    rows = _old_race_rows(3)
    rows.append(_race_row(101, pd.Timestamp(TARGET_DATE) - pd.Timedelta(days=20),
                          category='full_marathon', hr=165, pace=330))
    rows.append(_race_row(102, pd.Timestamp(TARGET_DATE) - pd.Timedelta(days=15),
                          category='race_event', hr=170, pace=280, distance=10.0))
    # 条件差异极大的半马：高温、高功率、慢配速——不得被排除
    rows.append(_race_row(103, pd.Timestamp(TARGET_DATE) - pd.Timedelta(days=5),
                          category='half_marathon', hr=175, pace=360, power=320,
                          temp=(30.0, 34.0)))
    df = _df(rows)
    az, t = _analyzer(df)
    comp = az._compare_with_history(t)
    assert comp['comparison_kind'] == 'same_distance_race_history'
    assert comp['sample_size'] == 4  # 3 + 1 条件差异半马；全马/race_event 不混入
    pool_ids = {a['date'] for a in comp['pool_activities']}
    assert len(pool_ids) == 4
    assert comp['result_comparison_allowed'] is True
    assert comp['ability_verdict_allowed'] is False


def test_full_marathon_pool_excludes_half():
    """全马池只含历史全马（PRD 5.1 双向不混池）"""
    rows = _old_race_rows(2, category='full_marathon', distance=42.2)
    rows += _old_race_rows(3, category='half_marathon')
    df = _df(rows)
    az, t = _analyzer(df, target=_target(category='full_marathon', distance=42.2))
    comp = az._compare_with_history(t)
    assert comp['sample_size'] == 2
    assert all(a['distance_km'] == 42.2 for a in comp['pool_activities'])


# ------------------------------------------------------------------
# 11.1-2 同距离历史 1/2/3 场整体比较行为
# ------------------------------------------------------------------
def test_race_pool_single_history_per_race_compare():
    """1 场历史比赛：保留逐场比较，不包装成统计中位数（PRD 5.4）"""
    df = _df(_old_race_rows(1, hr=155.0, pace=305.0))
    az, t = _analyzer(df)
    comp = az._compare_with_history(t)
    assert comp['sample_size'] == 1
    t_pace = comp['ability']['pace_trend']
    assert t_pace['diff'] == pytest.approx(310.0 - 305.0, abs=1e-6)
    assert t_pace['verdict_scope'] == 'result'
    gen = LLMReportGenerator(pd.DataFrame())
    text = gen._format_comparison(comp)
    assert '仅 1 场，逐场比较' in text


def test_race_pool_two_histories_median_and_range():
    """≥2 场：展示中位数和范围并始终标注实际场次数（PRD 5.4）"""
    rows = _old_race_rows(2, hr=150.0, pace=300.0)
    rows[1]['avg_pace_sec'] = 320.0
    df = _df(rows)
    az, t = _analyzer(df)
    comp = az._compare_with_history(t)
    assert comp['sample_size'] == 2
    t_pace = comp['ability']['pace_trend']
    assert t_pace['history_median'] == 310.0
    assert t_pace['history_min'] == 300.0 and t_pace['history_max'] == 320.0
    assert t_pace['sample_size'] == 2
    gen = LLMReportGenerator(pd.DataFrame())
    text = gen._format_comparison(comp)
    assert '2 场历史中位' in text


def test_race_pool_no_ability_verdict():
    """成绩差值允许展示，但禁止纯能力方向结论（PRD 5.3）"""
    df = _df(_old_race_rows(3))
    az, t = _analyzer(df)
    comp = az._compare_with_history(t)
    assert comp['ability_verdict_allowed'] is False
    for group in ('ability', 'economy'):
        for metric in comp[group].values():
            assert metric.get('verdict_scope') == 'result'
    gen = LLMReportGenerator(pd.DataFrame())
    text = gen._format_comparison(comp)
    assert '禁止仅凭该池输出「纯能力上升/下降」结论' in text


# ------------------------------------------------------------------
# 11.1-3 比赛分圈 3 样本中位线 / 普通课型 3 样本仍无中位线
# ------------------------------------------------------------------
def test_race_lap_median_3_samples_with_band_still_10():
    """比赛分圈每公里 3 样本有中位线、无 P20-P80；<3 不显示（PRD 6.1）"""
    runs = [[_hist_lap(i, pace=300 + i, hr=150 + i) for i in range(1, 6)]
            for _ in range(3)]
    stats = compute_per_km_history_stats(
        runs, max_km=5, median_min_samples=RACE_LAP_MEDIAN_MIN_SAMPLES)
    for km in range(1, 6):
        e = stats['by_km'][km]
        assert e['median_pace'] is not None and e['median_hr'] is not None
        assert e['p20_pace'] is None and e['p80_pace'] is None  # 区间带门槛 10 不降低
    # 2 样本：比赛中位线也不显示
    stats2 = compute_per_km_history_stats(
        runs[:2], max_km=5, median_min_samples=RACE_LAP_MEDIAN_MIN_SAMPLES)
    assert all(stats2['by_km'][km]['median_pace'] is None for km in range(1, 6))


def test_normal_lap_3_samples_still_no_median():
    """普通课型 3 样本仍无中位线（默认门槛 5 不变，PRD 6.1）"""
    runs = [[_hist_lap(i, pace=300 + i, hr=150 + i) for i in range(1, 6)]
            for _ in range(3)]
    stats = compute_per_km_history_stats(runs, max_km=5)
    assert stats['median_min_samples'] == 5
    assert all(stats['by_km'][km]['median_pace'] is None for km in range(1, 6))


def test_race_lap_prompt_label_and_chart_label():
    """比赛分圈 Prompt/图表注明实际场次数与执行参照限制（PRD 6.1/6.2）"""
    from src.chart_generator import ChartGenerator
    import json
    runs = [[_hist_lap(i, pace=300 + i, hr=150 + i) for i in range(1, 6)]
            for _ in range(3)]
    az, _ = _analyzer(_df(_old_race_rows(1, category='easy_run')))
    laps = az._analyze_laps([_hist_lap(i, pace=310 + i, hr=155 + i) for i in range(1, 6)],
                            runs,
                            median_min_samples=RACE_LAP_MEDIAN_MIN_SAMPLES,
                            race_history_label='3 场历史半程马拉松参考中位')
    assert laps['race_ref']['label'] == '3 场历史半程马拉松参考中位'
    gen = LLMReportGenerator(pd.DataFrame())
    text = gen._format_lap_data(laps)
    assert '3 场历史半程马拉松参考中位' in text
    assert '仅作执行参照' in text
    assert '历史中位配速 |' in text  # 3 样本比赛有中位列
    fig = json.loads(ChartGenerator().generate_lap_pace_chart_v2(
        [_hist_lap(i, pace=310 + i, hr=155 + i) for i in range(1, 6)],
        laps['history_stats'], median_label='3 场历史半程马拉松参考中位'))
    names = [t.get('name') for t in fig.get('data', [])]
    assert '3 场历史半程马拉松参考中位' in names


# ------------------------------------------------------------------
# 11.1-4 比赛技术池不混全马/半马；步幅增加不得 improved；基线不足不写「稳定」
# ------------------------------------------------------------------
def test_race_tech_pool_exact_category_change_not_improved():
    """比赛技术参照只含同距离历史比赛；VR/GCT 只称 change；步幅/步频只作强度背景（PRD 7.1/7.2）"""
    rows = _old_race_rows(3, stride=90.0, vr=7.5, gct=245.0, cadence=178.0)
    rows.append(_race_row(101, pd.Timestamp(TARGET_DATE) - pd.Timedelta(days=10),
                          category='full_marathon', stride=90.0, vr=7.5, gct=245.0,
                          cadence=178.0))
    df = _df(rows)
    # 本场：步幅 +8cm（机械结果）、VR -0.8、GCT -20ms
    az, t = _analyzer(df, target=_target(stride=98.0, vr=6.7, gct=225.0, cadence=180.0))
    comp = az._compare_with_history(t)
    tech = comp['tech_changes']
    assert tech['kind'] == 'race'
    assert tech['sample_size'] == 3          # 全马不混入半马技术池
    assert tech['status'] == 'comparable'
    changes = {c['field']: c for c in tech['changes']}
    assert changes['vertical_ratio']['direction'] == 'change'
    assert changes['ground_contact_time']['direction'] == 'change'
    assert not any(c['direction'] == 'improved' for c in tech['changes'])
    # 步幅/步频只作强度背景，不进变化清单
    assert 'stride_length' not in changes and 'cadence' not in changes
    assert tech['background']['步幅']['current'] == 98.0
    gen = LLMReportGenerator(pd.DataFrame())
    prompt = gen._build_prompt(_minimal_data(t, comp), user_note=None)
    # 5.0.2 验收修正（验收单 §2）：有技术变化但无「技术指标异常」→ 不展示【变化项】/【强度背景】，
    # 技术段只说明「本场未发现需要单独修正的技术问题」并强制固定一句收尾
    assert '【变化项】' not in prompt
    assert '【强度背景】' not in prompt
    assert '强度背景' not in prompt
    assert '本场未发现需要单独修正的技术问题' in prompt
    assert '技术效率分析：本段只输出一句「本场未发现需要单独修正的技术问题。」' in prompt
    # VR/GCT/步幅/步频数值不得逐项出现（技术数据段不展示技术四项）
    tech_section = prompt.split('## 技术分析')[1].split('## 历史对比')[0]
    assert 'vertical_ratio' not in tech_section and 'ground_contact' not in tech_section


def test_race_tech_insufficient_baseline_no_stable_claim():
    """同距离比赛 <3 场：不作技术评价，Prompt 不得写「长期稳定」（PRD 7.3）"""
    df = _df(_old_race_rows(2))
    az, t = _analyzer(df)
    comp = az._compare_with_history(t)
    assert comp['tech_changes']['status'] == 'insufficient_baseline'
    gen = LLMReportGenerator(pd.DataFrame())
    prompt = gen._build_prompt(_minimal_data(t, comp), user_note=None)
    assert '缺少可比技术基线' in prompt
    assert '不作技术评价' in prompt
    # 不得出现「长期稳定」的无状态收尾（PRD 7.3）
    assert '技术指标与长期基线持平，无显著变化' not in prompt


def test_normal_tech_insufficient_baseline_no_stable_claim():
    """普通课型无合格基线同样不得写「长期稳定」（PRD 7.2 状态表达修复）"""
    rows = [_race_row(i + 1, pd.Timestamp(TARGET_DATE) - pd.Timedelta(days=10 + i),
                      category='easy_run', distance=10.0, stride=90.0, vr=7.5,
                      gct=245.0, cadence=178.0)
            for i in range(2)]  # <90 天前样本不足 3 次
    df = _df(rows)
    az, t = _analyzer(df, target=_target(category='easy_run', distance=10.0))
    comp = az._compare_with_history(t)
    assert comp.get('tech_status') == 'insufficient_baseline'
    gen = LLMReportGenerator(pd.DataFrame())
    prompt = gen._build_prompt(_minimal_data(t, comp), user_note=None)
    assert '缺少可比技术基线' in prompt
    assert '不作技术评价' in prompt
    assert '技术指标与长期基线持平' not in prompt


def _minimal_data(target, comp):
    """构造 _build_prompt 需要的最小 analysis_data"""
    raw = {'date': str(target.get('date'))[:10], 'category': target.get('category', ''),
           'category_name': '半程马拉松', 'distance_km': target.get('distance', 21.1),
           'duration_min': target.get('duration_min', 100), 'avg_pace': '5:10',
           'avg_hr': target.get('avg_hr', 160), 'max_hr': target.get('max_hr', 180),
           'cadence': target.get('cadence', 180), 'stride_length_cm': target.get('stride_length', 95),
           'vertical_ratio_pct': target.get('vertical_ratio', 7),
           'ground_contact_ms': target.get('ground_contact_time', 240)}
    return {'raw_data': raw, 'summary': {'zone_pct': {}}, 'intensity': {},
            'efficiency': {}, 'comparison': comp, 'findings': [], 'laps': {},
            'pa_hr': None, 'issues': [], 'data_notes': []}


# ------------------------------------------------------------------
# 11.1-5 比赛三类信号不进问题清单；max_hr 进 data_notes
# ------------------------------------------------------------------
def _issue_scene(category):
    df_rows = [_race_row(i + 1, pd.Timestamp(TARGET_DATE) - pd.Timedelta(days=3 - i),
                         category=category, distance=10.0, load=80.0)
               for i in range(3)]
    df = _df(df_rows)
    target = _target(category=category, distance=10.0, max_hr=195.0, load=400.0)
    az, t = _analyzer(df, target=target)
    analysis_data = {
        'pa_hr': {'pa_hr_pct': -6.1, 'verdict': '明显漂移'},
        'comparison': {},
    }
    return az, t, analysis_data


def test_race_signals_not_issues_and_max_hr_in_data_notes():
    """比赛：Pa:Hr≤-5%、负荷超近 4 次均值、max_hr 超配置均不进问题清单；
    max_hr 进入 data_notes 数据提示（PRD 8.1/8.2）"""
    az, t, ad = _issue_scene('half_marathon')
    issues = az._detect_issues(t, ad)
    titles = '；'.join(i['title'] for i in issues)
    assert '心率漂移' not in titles
    assert '负荷激增' not in titles
    assert '心率异常' not in titles
    notes = az._detect_data_notes(t)
    assert len(notes) == 1
    assert '超过配置上限 188' in notes[0]['title']
    assert '核验' in notes[0]['evidence']
    assert '而非执行问题' in notes[0]['evidence']


def test_race_tech_anomaly_uses_same_pool():
    """比赛技术异常探测器与参照池同口径：池 ≥3 才触发，且证据注明同距离比赛池（PRD 7.3）"""
    rows = _old_race_rows(3, vr=7.0, gct=240.0)
    df = _df(rows)
    az, t = _analyzer(df, target=_target(vr=9.5, gct=240.0))  # VR 明显劣于池 P80
    comp = az._compare_with_history(t)
    assert comp['tech_changes']['status'] == 'comparable'
    issues = az._detect_issues(t, {'pa_hr': None, 'comparison': comp})
    tech_issues = [i for i in issues if '技术指标异常' in i['title']]
    assert len(tech_issues) == 1
    assert '同距离历史比赛' in tech_issues[0]['evidence']


# ------------------------------------------------------------------
# 11.1-6 非比赛相同信号保持既有探测行为（回归）
# ------------------------------------------------------------------
def test_non_race_signals_still_detected():
    """非比赛：Pa:Hr≤-5%、负荷激增、max_hr 超配置三条探测器照常触发（PRD 8.1 非比赛保持现状）"""
    az, t, ad = _issue_scene('easy_run')
    issues = az._detect_issues(t, ad)
    titles = [i['title'] for i in issues]
    assert any('心率漂移' in x for x in titles)
    assert any('负荷激增' in x for x in titles)
    assert any('心率异常' in x for x in titles)
    assert az._detect_data_notes(t) == []


# ------------------------------------------------------------------
# 11.1-7 比赛计划与 analysis_hash
# ------------------------------------------------------------------
def _plan(segments=None, checkpoints=None, target='1:48'):
    segs = segments if segments is not None else [
        {'start_km': 1, 'end_km': 2, 'pace_min_sec': 310, 'pace_max_sec': 312, 'note': 'n'},
    ]
    cps = checkpoints if checkpoints is not None else [
        {'distance_km': 5, 'anchor_sec': 1535, 'upper_sec': 1570, 'action': 'a'},
    ]
    return {'date': TARGET_DATE, 'name': '测试半马', 'category': 'half_marathon',
            'target': target, 'strategy': 's', 'weather_rule': 'w',
            'heat_threshold_c': 18.0, 'heat_pace_penalty_min_sec': 3,
            'heat_pace_penalty_max_sec': 5, 'heat_adjusted_target': '1:49-1:50',
            'segments': segs, 'checkpoints': cps}


def _laps_2k():
    return [{'lap_index': 1, 'distance_m': 1000, 'duration_sec': 310,
             'avg_hr': 150, 'avg_power': 250, 'elevation_gain_m': 2},
            {'lap_index': 2, 'distance_m': 1000, 'duration_sec': 312,
             'avg_hr': 152, 'avg_power': 252, 'elevation_gain_m': 3}]


def test_no_plan_no_deviation_allowed_and_hash_stable():
    """无比赛计划：race_plan 为 None、analysis_hash 正常生成（PRD 9.2 禁止计划偏离判断）"""
    df = _df(_old_race_rows(1, category='easy_run'))
    az, t = _analyzer(df)
    result = az.analyze(t)
    assert result['race_plan'] is None
    h1 = _analysis_hash(result)
    assert isinstance(h1, str) and len(h1) == 64


def test_plan_changes_analysis_hash():
    """有计划、修改计划后 analysis_hash 必须变化（PRD 9.2/10.3）"""
    df = _df(_old_race_rows(1, category='easy_run'))
    az1, t1 = _analyzer(df, race_plan=_plan())
    az1.raw_laps = _laps_2k()
    r1 = az1.analyze(t1)
    assert r1['race_plan'] is not None
    h1 = _analysis_hash(r1)

    az2, t2 = _analyzer(df, race_plan=_plan(target='1:47'))  # 修改目标
    az2.raw_laps = _laps_2k()
    r2 = az2.analyze(t2)
    h2 = _analysis_hash(r2)
    assert h1 != h2

    az3, t3 = _analyzer(df)  # 无计划
    az3.raw_laps = _laps_2k()
    h3 = _analysis_hash(az3.analyze(t3))
    assert h3 != h1


def test_plan_category_mismatch_skipped():
    """计划 category 与活动不一致：不计算赛段证据（PRD 9.2 校验）"""
    df = _df(_old_race_rows(1, category='easy_run'))
    az, t = _analyzer(df, target=_target(category='half_marathon'),
                      race_plan=_plan())  # plan 是 half_marathon，一致——再测不一致：
    az.raw_laps = _laps_2k()
    assert az.analyze(t)['race_plan'] is not None
    az2, t2 = _analyzer(df, target=_target(category='easy_run'),
                        race_plan=_plan())
    az2.raw_laps = _laps_2k()
    assert az2.analyze(t2)['race_plan'] is None


def test_race_plan_config_validation():
    """配置非法清晰报错：schema 错误/赛段重叠/配速上下限颠倒/检查点窗口非法（PRD 9.2）"""
    import tomllib
    import tempfile
    from pathlib import Path

    def _write(toml_text):
        f = tempfile.NamedTemporaryFile('w', suffix='.toml', delete=False)
        f.write(toml_text)
        f.close()
        return Path(f.name)

    bad_schema = _write('schema_version = 2\n')
    with pytest.raises(RacePlanError):
        load_race_plan(TARGET_DATE, path=bad_schema)

    overlap = _write("""schema_version = 1
[races."2026-11-15"]
name = "x" ; category = "half_marathon" ; target = "1:48" ; strategy = "s"
weather_rule = "w" ; heat_threshold_c = 18.0 ; heat_pace_penalty_min_sec = 3
heat_pace_penalty_max_sec = 5 ; heat_adjusted_target = "1:49"
[[races."2026-11-15".segments]]
start_km = 1 ; end_km = 5 ; pace_min_sec = 300 ; pace_max_sec = 310
[[races."2026-11-15".segments]]
start_km = 3 ; end_km = 7 ; pace_min_sec = 300 ; pace_max_sec = 310
[[races."2026-11-15".checkpoints]]
distance_km = 5 ; anchor_sec = 1500 ; upper_sec = 1600 ; action = "a"
""")
    with pytest.raises(RacePlanError):
        load_race_plan(TARGET_DATE, path=overlap)

    no_entry = _write('schema_version = 1\n')
    assert load_race_plan('2026-01-01', path=no_entry) is None


# ------------------------------------------------------------------
# 11.1-8 赛段加权口径（非逐公里简单平均）
# ------------------------------------------------------------------
def test_segment_weighted_pace_hr_power():
    """赛段配速=总时长/总距离；心率/功率按分圈时长加权——非逐公里简单平均（PRD 9.3）"""
    plan = _plan(segments=[{'start_km': 1, 'end_km': 2, 'pace_min_sec': 250,
                            'pace_max_sec': 400, 'note': ''}],
                 checkpoints=[{'distance_km': 2, 'anchor_sec': 1000,
                               'upper_sec': 2000, 'action': ''}])
    # 圈 1：500m/100s（配速 200）；圈 2：1500m/450s（配速 300）
    laps = [{'lap_index': 1, 'distance_m': 500, 'duration_sec': 100,
             'avg_hr': 140, 'avg_power': 200, 'elevation_gain_m': 1},
            {'lap_index': 2, 'distance_m': 1500, 'duration_sec': 450,
             'avg_hr': 160, 'avg_power': 260, 'elevation_gain_m': 3}]
    ev = compute_plan_evidence(plan, laps, temp_mid=10.0, humidity=None)
    seg = ev['segments'][0]
    # 加权配速 = 550s / 2000m × 1000 = 275（简单平均 (200+300)/2 = 250 ≠ 275）
    assert seg['actual_pace_sec'] == 275.0
    # 心率按时长加权：(100×140 + 450×160) / 550 = 156.4（简单平均 150 ≠ 156.4）
    assert seg['avg_hr_weighted'] == round((100 * 140 + 450 * 160) / 550, 1)
    # 功率按时长加权：(100×200 + 450×260) / 550 = 249.1
    assert seg['avg_power_weighted'] == round((100 * 200 + 450 * 260) / 550, 1)
    assert seg['elevation_gain_m'] == 4.0
    # 低温未触发天气调整
    assert ev['weather']['heat_triggered'] is False
    assert ev['weather']['humidity_participated'] is False


def test_weather_trigger_uses_structured_seconds():
    """天气触发由内核按结构化秒数计算调整后区间；湿度缺失明确未参与（PRD 9.3）"""
    plan = _plan()
    ev = compute_plan_evidence(_plan(), _laps_2k(), temp_mid=23.5, humidity=None)
    assert ev['weather']['heat_triggered'] is True           # 23.5 > 18.0
    assert ev['weather']['adjusted_pace_penalty_sec'] == [3, 5]
    assert ev['weather']['adjusted_target'] == '1:49-1:50'
    assert ev['weather']['humidity_participated'] is False
    seg = ev['segments'][0]
    assert seg['adjusted_pace_min_sec'] == 313 and seg['adjusted_pace_max_sec'] == 317


# ------------------------------------------------------------------
# 5.0.2 验收修正测试（docs/audits/2026-11-15-powerfun-5.0.2-race-coaching-acceptance.md）
# ------------------------------------------------------------------
def test_race_tech_anomaly_prompt_shows_evidence():
    """确有技术异常：Prompt 直接复用 data['issues'] 中「技术指标异常」确定性证据，
    允许针对异常分析（异常/执行影响/修正），且不把普通 change 当异常（验收单 §2）"""
    rows = _old_race_rows(3, vr=7.0, gct=240.0)
    df = _df(rows)
    az, t = _analyzer(df, target=_target(vr=9.5, gct=240.0))  # VR 明显劣于池 P80
    comp = az._compare_with_history(t)
    issues = az._detect_issues(t, {'pa_hr': None, 'comparison': comp})
    data = _minimal_data(t, comp)
    data['issues'] = issues
    gen = LLMReportGenerator(pd.DataFrame())
    prompt = gen._build_prompt(data, user_note=None)
    assert '【技术异常】' in prompt
    assert '技术指标异常' in prompt
    assert '对本次比赛执行的影响' in prompt        # 允许针对异常分析
    assert '本场未发现需要单独修正的技术问题' not in prompt
    # 异常场景也不得把普通 change 包装成【变化项】逐项展示
    assert '【变化项】' not in prompt


def _race_ev(checkpoints):
    return {'plan': _plan(), 'weather': {'temp_mid_c': 20.0, 'heat_triggered': False},
            'segments': [{'start_km': 1, 'end_km': 2, 'actual_pace_sec': 311.0,
                          'deviation': 'in_range', 'adjusted_pace_min_sec': None,
                          'planned_pace_min_sec': 310, 'planned_pace_max_sec': 312,
                          'avg_hr_weighted': 150, 'avg_power_weighted': 250,
                          'elevation_gain_m': 2, 'note': 'n'}],
            'checkpoints': checkpoints}


def test_checkpoint_within_window_not_triggered():
    """窗口内：「超限预案：{action}（本场未触发）」，不得出现实际指令式「行动：」（验收单 §3）"""
    cp = {'distance_km': 15, 'actual_elapsed_sec': 4646.0, 'anchor_sec': 4600,
          'upper_sec': 4700, 'deviation': 'within_window', 'action': '降档：目标放宽'}
    text = LLMReportGenerator(pd.DataFrame())._format_race_plan(_race_ev([cp]))
    assert '窗口内；超限预案：降档：目标放宽（本场未触发）' in text
    assert '行动：' not in text
    assert '已触发' not in text


def test_checkpoint_beyond_upper_triggered():
    """超窗口上限：「已触发超限预案：{action}」（验收单 §3）"""
    cp = {'distance_km': 5, 'actual_elapsed_sec': 1600.0, 'anchor_sec': 1535,
          'upper_sec': 1570, 'deviation': 'beyond_upper', 'action': '只慢不快，不追'}
    text = LLMReportGenerator(pd.DataFrame())._format_race_plan(_race_ev([cp]))
    assert '超窗口上限；已触发超限预案：只慢不快，不追' in text


def test_checkpoint_ahead_of_anchor_not_triggered():
    """快于锚点：「快于锚点；超限预案：{action}（本场未触发）」（验收单 §3）"""
    cp = {'distance_km': 10, 'actual_elapsed_sec': 3000.0, 'anchor_sec': 3100,
          'upper_sec': 3200, 'deviation': 'ahead_of_anchor', 'action': '保持'}
    text = LLMReportGenerator(pd.DataFrame())._format_race_plan(_race_ev([cp]))
    assert '快于锚点；超限预案：保持（本场未触发）' in text


def test_checkpoint_unknown_deviation_not_inferred():
    """偏差状态未知：不得推断预案已触发（验收单 §3）"""
    cp = {'distance_km': 20, 'actual_elapsed_sec': 6100.0, 'anchor_sec': 6000,
          'upper_sec': 6200, 'deviation': None, 'action': '保持'}
    text = LLMReportGenerator(pd.DataFrame())._format_race_plan(_race_ev([cp]))
    assert '偏差状态未知；不得推断预案已触发' in text
    assert '已触发超限预案' not in text


def _race_ev_5segs():
    segs = [{'start_km': s, 'end_km': e, 'actual_pace_sec': 300.0,
             'deviation': 'in_range', 'adjusted_pace_min_sec': None,
             'planned_pace_min_sec': 300, 'planned_pace_max_sec': 310,
             'avg_hr_weighted': 150, 'avg_power_weighted': 250,
             'elevation_gain_m': 2, 'note': ''}
            for s, e in ((1, 2), (3, 7), (8, 12), (13, 17), (18, 21))]
    ev = _race_ev([])
    ev['segments'] = segs
    return ev


def test_race_lap_instruction_follows_plan_segments():
    """有计划比赛：第 5 小节按 race_plan.segments 实际赛段逐一分析并覆盖检查点，
    不再要求前/中/后程（验收单 §4.1）"""
    df = _df(_old_race_rows(3))
    az, t = _analyzer(df)
    comp = az._compare_with_history(t)
    data = _minimal_data(t, comp)
    data['race_plan'] = _race_ev_5segs()
    prompt = LLMReportGenerator(pd.DataFrame())._build_prompt(data, user_note=None)
    assert '5. 分圈表现分析：严格按上方「比赛计划与赛段执行」的计划赛段' in prompt
    assert '1-2 km / 3-7 km / 8-12 km / 13-17 km / 18-21 km' in prompt
    assert '并结合检查点表现' in prompt
    assert '不得另建前/中/后程' in prompt
    assert '按前/中/后程拆解' not in prompt


def test_normal_and_planless_lap_instruction_unchanged():
    """普通课型与无计划比赛：第 5 小节保持原有前/中/后程指令（验收单 §4.1，不扩大修改）"""
    gen = LLMReportGenerator(pd.DataFrame())
    # 普通课型（非比赛）
    df = _df(_old_race_rows(1, category='easy_run'))
    az, t = _analyzer(df, target=_target(category='easy_run', distance=10.0))
    comp = az._compare_with_history(t)
    prompt = gen._build_prompt(_minimal_data(t, comp), user_note=None)
    assert '按前/中/后程拆解配速与心率变化，还原训练现场' in prompt
    assert '不得另建前/中/后程' not in prompt
    # 比赛但无结构化计划
    df2 = _df(_old_race_rows(3))
    az2, t2 = _analyzer(df2)
    comp2 = az2._compare_with_history(t2)
    prompt2 = gen._build_prompt(_minimal_data(t2, comp2), user_note=None)
    assert '按前/中/后程拆解配速与心率变化，还原训练现场' in prompt2
    assert '不得另建前/中/后程' not in prompt2


def test_race_comparison_pace_no_duplicate_unit():
    """比赛历史比较：_format_pace 已含 /KM，当前值/中位数/范围不得再出现 /KM/km（验收单 §4.2）"""
    rows = _old_race_rows(2, hr=150.0, pace=300.0)
    rows[1]['avg_pace_sec'] = 320.0
    df = _df(rows)
    az, t = _analyzer(df)
    comp = az._compare_with_history(t)
    text = LLMReportGenerator(pd.DataFrame())._format_comparison(comp)
    assert '/KM/km' not in text
    assert '/km' not in text                      # 额外拼接的单位已移除
    assert '5分10秒/KM' in text                   # 当前值 310s
    assert '5分10秒/KM vs 2 场历史中位 5分10秒/KM' in text
    assert '范围 5分00秒/KM-5分20秒/KM' in text
