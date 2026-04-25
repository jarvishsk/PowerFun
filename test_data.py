#!/usr/bin/env python3
"""PowerFun 测试脚本

测试数据获取模块和数据处理器，使用本地测试数据验证。
"""

import json
import sys
import os
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.data_processor import DataProcessor
from src.config import FIELD_MAPPING, PACE_LEVELS


def load_test_data(path: str) -> list[dict]:
    """加载测试数据"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_pace_conversion():
    """测试配速转换"""
    print("=" * 50)
    print("测试配速转换")
    print("=" * 50)

    processor = DataProcessor()

    test_cases = [
        (5.78, "05:47"),    # 示例: 5.78 min/km -> 05:47
        (4.50, "04:30"),
        (6.00, "06:00"),
        (3.25, "03:15"),
        (None, "--:--"),
        (0, "--:--"),
        (-1, "--:--"),
        (99.99, "99:59"),
    ]

    all_passed = True
    for pace, expected in test_cases:
        result = processor._pace_to_mmss(pace)
        status = "✅" if result == expected else "❌"
        if result != expected:
            all_passed = False
        print(f"  {status} pace_to_mmss({pace}) = '{result}' (期望 '{expected}')")

    return all_passed


def test_speed_to_pace():
    """测试速度转配速"""
    print("\n" + "=" * 50)
    print("测试速度转配速")
    print("=" * 50)

    processor = DataProcessor()

    test_cases = [
        (10.5, "05:43"),    # 60/10.5 = 5.71 -> 05:43
        (12.0, "05:00"),    # 60/12 = 5.0 -> 05:00
        (8.0, "07:30"),     # 60/8 = 7.5 -> 07:30
        (None, "--:--"),
        (0, "--:--"),
    ]

    all_passed = True
    for speed, expected in test_cases:
        result = processor._speed_to_pace_mmss(speed)
        status = "✅" if result == expected else "❌"
        if result != expected:
            all_passed = False
        print(f"  {status} speed_to_pace({speed}) = '{result}' (期望 '{expected}')")

    return all_passed


def test_duration_conversion():
    """测试时长转换"""
    print("\n" + "=" * 50)
    print("测试时长转换 (分钟 -> hh:mm:ss)")
    print("=" * 50)

    processor = DataProcessor()

    test_cases = [
        (99.73, "01:39:44"),   # 99.73 * 60 = 5983.8s
        (60.0, "01:00:00"),
        (30.5, "00:30:30"),
        (5.0, "00:05:00"),
        (None, "--:--:--"),
    ]

    all_passed = True
    for minutes, expected in test_cases:
        result = processor._minutes_to_hhmmss(minutes)
        status = "✅" if result == expected else "❌"
        if result != expected:
            all_passed = False
        print(f"  {status} minutes_to_hhmmss({minutes}) = '{result}' (期望 '{expected}')")

    return all_passed


def test_garmer_format_processing():
    """测试 garmer 格式数据处理"""
    print("\n" + "=" * 50)
    print("测试 garmer 格式数据处理")
    print("=" * 50)

    test_file = Path("/Users/jarvis/Documents/Run/all_running_activities.json")
    if not test_file.exists():
        print(f"  ❌ 测试数据文件不存在: {test_file}")
        return False

    raw_data = load_test_data(str(test_file))
    print(f"  加载 {len(raw_data)} 条原始数据")

    # 检查数据格式
    first = raw_data[0]
    has_raw_data = "raw_data" in first
    has_summary = "summaryDTO" in first.get("raw_data", {}) if has_raw_data else False
    print(f"  格式: garmer (raw_data={has_raw_data}, summaryDTO={has_summary})")

    # 处理数据
    processor = DataProcessor()
    df = processor.process(raw_data)

    if df.empty:
        print("  ❌ 处理结果为空")
        return False

    print(f"  ✅ 处理后: {len(df)} 条记录")
    print(f"  字段: {list(df.columns)}")

    # 显示前 3 条
    print("\n  前 3 条记录:")
    display_cols = ["date", "distance", "avg_pace", "duration", "avg_hr", "max_hr", "calories"]
    available = [c for c in display_cols if c in df.columns]
    print(df[available].head(3).to_string(index=False))

    # 验证配速格式
    if "avg_pace" in df.columns:
        sample = df["avg_pace"].dropna().iloc[0] if not df["avg_pace"].dropna().empty else None
        if sample:
            print(f"\n  配速示例: {sample}")
            # 验证格式 mm:ss
            parts = str(sample).split(":")
            if len(parts) == 2 and len(parts[0]) == 2 and len(parts[1]) == 2:
                print("  ✅ 配速格式正确 (mm:ss)")
            else:
                print(f"  ⚠️ 配速格式可能有问题: {sample}")

    # 验证时长格式
    if "duration" in df.columns:
        sample = df["duration"].dropna().iloc[0] if not df["duration"].dropna().empty else None
        if sample:
            print(f"  时长示例: {sample}")
            parts = str(sample).split(":")
            if len(parts) == 3:
                print("  ✅ 时长格式正确 (hh:mm:ss)")
            else:
                print(f"  ⚠️ 时长格式可能有问题: {sample}")

    # 数据校验
    issues = processor.validate(df)
    if issues:
        print(f"\n  数据质量: {issues}")
    else:
        print("\n  ✅ 数据质量检查通过")

    return True


def test_garth_format_processing():
    """测试 garth API 格式数据处理"""
    print("\n" + "=" * 50)
    print("测试 garth API 格式数据处理 (模拟)")
    print("=" * 50)

    # 模拟 garth connectapi 返回格式 (distance=meters, duration=seconds, speed=m/s)
    mock_activities = [
        {
            "activityId": 12345,
            "activityName": "晨跑",
            "activityType": {"typeKey": "running"},
            "activityTypeKey": "running",
            "startTimeLocal": "2026-04-20T07:30:00.0",
            "startTimeGMT": "2026-04-19T23:30:00.0",
            "distance": 10500.0,       # meters (10.5 km)
            "duration": 3780.0,        # seconds (63 min)
            "averageHR": 150,
            "maxHR": 175,
            "calories": 650,
            "averageSpeed": 2.78,      # m/s (~10 km/h)
            "maxSpeed": 4.03,          # m/s (~14.5 km/h)
            "averageRunningCadence": 175,
            "elevationGain": 45,
            "elevationLoss": 40,
        },
        {
            "activityId": 12346,
            "activityName": "夜跑",
            "activityType": {"typeKey": "running"},
            "activityTypeKey": "running",
            "startTimeLocal": "2026-04-21T19:00:00.0",
            "startTimeGMT": "2026-04-21T11:00:00.0",
            "distance": 5200.0,
            "duration": 1800.0,        # 30 min
            "averageHR": 145,
            "maxHR": 168,
            "calories": 320,
            "averageSpeed": 2.89,      # m/s (~10.4 km/h)
            "maxSpeed": 3.61,          # m/s (~13 km/h)
            "averageRunningCadence": 170,
            "elevationGain": 20,
            "elevationLoss": 18,
        },
    ]

    processor = DataProcessor()
    df = processor.process(mock_activities)

    if df.empty:
        print("  ❌ 处理结果为空")
        return False

    print(f"  ✅ 处理后: {len(df)} 条记录")
    print(f"  字段: {list(df.columns)}")

    display_cols = ["date", "distance", "avg_pace", "duration", "avg_hr", "max_hr"]
    available = [c for c in display_cols if c in df.columns]
    print(df[available].to_string(index=False))

    return True


def test_csv_export():
    """测试 CSV 导出"""
    print("\n" + "=" * 50)
    print("测试 CSV 导出")
    print("=" * 50)

    test_file = Path("/Users/jarvis/Documents/Run/all_running_activities.json")
    if not test_file.exists():
        print(f"  ⏭️ 跳过 (测试数据不存在)")
        return True

    raw_data = load_test_data(str(test_file))
    processor = DataProcessor()
    df = processor.process(raw_data)

    if df.empty:
        print("  ❌ 无数据可导出")
        return False

    output_path = "/tmp/powerfun_test_output.csv"
    processor.to_csv(df, output_path)

    if Path(output_path).exists():
        size = Path(output_path).stat().st_size
        print(f"  ✅ CSV 已导出: {output_path} ({size} bytes)")
        # 显示前 5 行
        with open(output_path, "r", encoding="utf-8-sig") as f:
            lines = f.readlines()
        print(f"  列名: {lines[0].strip()}")
        print(f"  前 3 行:")
        for line in lines[1:4]:
            print(f"    {line.strip()}")
        return True
    else:
        print(f"  ❌ CSV 导出失败")
        return False


def main():
    """运行所有测试"""
    print("🏃 PowerFun 数据模块测试\n")

    results = {}

    results["pace_conversion"] = test_pace_conversion()
    results["speed_to_pace"] = test_speed_to_pace()
    results["duration_conversion"] = test_duration_conversion()
    results["garmer_format"] = test_garmer_format_processing()
    results["garth_format"] = test_garth_format_processing()
    results["csv_export"] = test_csv_export()

    # 汇总
    print("\n" + "=" * 50)
    print("测试汇总")
    print("=" * 50)

    all_passed = True
    for name, passed in results.items():
        status = "✅ 通过" if passed else "❌ 失败"
        if not passed:
            all_passed = False
        print(f"  {status} - {name}")

    print()
    if all_passed:
        print("🎉 所有测试通过!")
    else:
        print("⚠️  部分测试未通过")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
