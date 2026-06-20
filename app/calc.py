import math
from datetime import datetime, timedelta
from typing import List, Optional, Dict

from app.models import FARM_IRRIGATION_NEEDS


def calc_gate_flow(water_level: float, canal_width: float, gate_opening: int) -> float:
    if gate_opening <= 0 or water_level <= 0 or canal_width <= 0:
        return 0.0
    effective_width = canal_width * (gate_opening / 100.0)
    flow = 0.61 * effective_width * math.sqrt(2 * 9.81) * (water_level ** 1.5)
    return flow


def _capacities(branch_canals: List[dict]) -> List[float]:
    caps = []
    for bc in branch_canals:
        caps.append(calc_gate_flow(
            bc.get("water_level", 0),
            bc["width"],
            bc.get("gate_opening", 100),
        ))
    return caps


def distribute_equal(total_flow: float, branch_canals: List[dict]) -> List[dict]:
    if not branch_canals or total_flow <= 0:
        return []
    caps = _capacities(branch_canals)
    allocated = [0.0] * len(branch_canals)
    remaining = total_flow
    active = [i for i in range(len(branch_canals)) if caps[i] > 0]
    while active and remaining > 0:
        share = remaining / len(active)
        new_active = []
        used = 0.0
        for i in active:
            room = caps[i] - allocated[i]
            if room <= 1e-9:
                continue
            take = min(share, room)
            allocated[i] += take
            used += take
            if room - take > 1e-9:
                new_active.append(i)
        remaining -= used
        if used <= 1e-9:
            break
        active = new_active
    results = []
    for i, bc in enumerate(branch_canals):
        results.append({
            "branch_canal_id": bc["id"],
            "name": bc["name"],
            "position": bc["position"],
            "flow": round(allocated[i], 4),
            "capacity": round(caps[i], 4),
        })
    return results


def distribute_downstream_first(total_flow: float, branch_canals: List[dict]) -> List[dict]:
    if not branch_canals or total_flow <= 0:
        return []
    caps = _capacities(branch_canals)
    sorted_pairs = sorted(enumerate(branch_canals), key=lambda x: x[1]["position"], reverse=True)
    allocated = [0.0] * len(branch_canals)
    remaining = total_flow
    for i, _ in sorted_pairs:
        if remaining <= 0:
            break
        take = min(caps[i], remaining)
        allocated[i] = take
        remaining -= take
    results = []
    for i, bc in enumerate(branch_canals):
        results.append({
            "branch_canal_id": bc["id"],
            "name": bc["name"],
            "position": bc["position"],
            "flow": round(allocated[i], 4),
            "capacity": round(caps[i], 4),
        })
    return results


def distribute_acreage_ratio(total_flow: float, branch_canals: List[dict]) -> List[dict]:
    if not branch_canals or total_flow <= 0:
        return []
    total_acreage = sum(bc.get("acreage", 0) for bc in branch_canals)
    caps = _capacities(branch_canals)
    if total_acreage <= 0:
        base = distribute_equal(total_flow, branch_canals)
        for i, item in enumerate(base):
            item["acreage"] = branch_canals[i].get("acreage", 0)
            item["ratio"] = 0.0
        return base
    ratios = [bc.get("acreage", 0) / total_acreage for bc in branch_canals]
    allocated = [0.0] * len(branch_canals)
    remaining = total_flow
    active = [i for i in range(len(branch_canals)) if caps[i] > 0]
    while active and remaining > 0:
        active_ratio_sum = sum(ratios[i] for i in active)
        if active_ratio_sum <= 0:
            share = remaining / len(active)
            for i in active:
                room = caps[i] - allocated[i]
                take = min(share, room)
                allocated[i] += take
                remaining -= take
            break
        used = 0.0
        new_active = []
        for i in active:
            room = caps[i] - allocated[i]
            if room <= 1e-9:
                continue
            target = remaining * (ratios[i] / active_ratio_sum)
            take = min(target, room)
            allocated[i] += take
            used += take
            if room - take > 1e-9:
                new_active.append(i)
        remaining -= used
        if used <= 1e-9:
            break
        active = new_active
    results = []
    for i, bc in enumerate(branch_canals):
        results.append({
            "branch_canal_id": bc["id"],
            "name": bc["name"],
            "position": bc["position"],
            "flow": round(allocated[i], 4),
            "capacity": round(caps[i], 4),
            "acreage": bc.get("acreage", 0),
            "ratio": round(ratios[i], 4),
        })
    return results


RULE_FUNCTIONS = {
    "equal": distribute_equal,
    "downstream_first": distribute_downstream_first,
    "acreage_ratio": distribute_acreage_ratio,
}


def compute_distribution(total_flow: float, branch_canals: List[dict], rule: str) -> List[dict]:
    fn = RULE_FUNCTIONS.get(rule, distribute_equal)
    return fn(total_flow, branch_canals)


def apply_seasonal_priority(
    branch_canals: List[dict],
    priority_farm_type: str = "",
    priority_ratio: float = 1.0,
) -> List[dict]:
    if not priority_farm_type or priority_ratio <= 1.0:
        return branch_canals
    adjusted = []
    for bc in branch_canals:
        new_bc = dict(bc)
        farm_type = bc.get("farm_type", "general")
        if farm_type == priority_farm_type:
            base = new_bc.get("acreage", 0)
            new_bc["acreage"] = round(base * priority_ratio, 4)
        adjusted.append(new_bc)
    return adjusted


def check_over_allocation(total_flow: float, results: List[dict]) -> bool:
    total_allocated = sum(r["flow"] for r in results)
    return total_allocated > total_flow + 1e-6


def compute_main_canal_flow(water_level: float, main_canal_width: float) -> float:
    if water_level <= 0 or main_canal_width <= 0:
        return 0.0
    flow = main_canal_width * math.sqrt(2 * 9.81) * (water_level ** 1.5)
    return round(flow, 4)


def filter_continuous_dates(dates: List[str]) -> List[str]:
    if not dates:
        return []
    sorted_dates = sorted(set(dates))
    if len(sorted_dates) == 1:
        return sorted_dates
    segments = []
    current_segment = [sorted_dates[0]]
    try:
        current_dt = datetime.strptime(sorted_dates[0], "%Y-%m-%d")
    except (ValueError, TypeError):
        return sorted_dates
    for i in range(1, len(sorted_dates)):
        try:
            dt = datetime.strptime(sorted_dates[i], "%Y-%m-%d")
        except (ValueError, TypeError):
            segments.append(current_segment)
            current_segment = [sorted_dates[i]]
            continue
        expected = current_dt + timedelta(days=1)
        if dt == expected:
            current_segment.append(sorted_dates[i])
            current_dt = dt
        else:
            segments.append(current_segment)
            current_segment = [sorted_dates[i]]
            current_dt = dt
    segments.append(current_segment)
    if not segments:
        return sorted_dates
    longest = max(segments, key=len)
    return longest


def get_month_from_date(date_str: str) -> int:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.month
    except (ValueError, TypeError):
        return 0


def get_year_from_date(date_str: str) -> int:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.year
    except (ValueError, TypeError):
        return 0


def match_seasonal_rule(date_str: str, seasonal_rules: List[dict], water_level: float = 0) -> Optional[dict]:
    month = get_month_from_date(date_str)
    if month == 0:
        return None
    for rule in seasonal_rules:
        sm = rule.get("start_month", 1)
        em = rule.get("end_month", 12)
        threshold = rule.get("water_level_threshold", 0)
        if sm <= em:
            month_match = sm <= month <= em
        else:
            month_match = month >= sm or month <= em
        level_match = water_level >= threshold if threshold > 0 else True
        if month_match and level_match:
            return rule
    return None


def compute_coverage(flow: float, acreage: float, farm_type: str = "general", water_level: float = 0) -> float:
    if acreage <= 0 or flow <= 0:
        return 0.0
    need_coeff = FARM_IRRIGATION_NEEDS.get(farm_type, 1.0)
    needed = acreage * need_coeff * 0.01
    if needed <= 0:
        return 0.0
    coverage = min(1.0, flow / needed)
    return round(coverage, 4)


def compute_time_series(
    water_levels: List[dict],
    main_canal_width: float,
    branch_canals: List[dict],
    rule: str,
    seasonal_rules: Optional[List[dict]] = None,
) -> List[dict]:
    results = []
    for wl_record in water_levels:
        water_level = wl_record["level"]
        date = wl_record["date"]
        total_flow = compute_main_canal_flow(water_level, main_canal_width)
        active_rule = rule
        active_priority_farm = ""
        active_priority_ratio = 1.0
        matched_seasonal = None
        if seasonal_rules:
            matched_seasonal = match_seasonal_rule(date, seasonal_rules, water_level)
            if matched_seasonal:
                active_rule = matched_seasonal.get("rule", rule)
                active_priority_farm = matched_seasonal.get("priority_farm_type", "")
                active_priority_ratio = matched_seasonal.get("priority_ratio", 1.0)
        branch_data = []
        for bc in branch_canals:
            branch_data.append({
                "id": bc["id"],
                "name": bc["name"],
                "position": bc["position"],
                "width": bc["width"],
                "acreage": bc.get("acreage", 0),
                "farm_type": bc.get("farm_type", "general"),
                "gate_opening": bc.get("gate_opening", 100),
                "water_level": water_level,
            })
        adjusted_branches = apply_seasonal_priority(branch_data, active_priority_farm, active_priority_ratio)
        distribution = compute_distribution(total_flow, adjusted_branches, active_rule)
        for br in distribution:
            bc_original = next((b for b in branch_data if b["id"] == br["branch_canal_id"]), None)
            if bc_original:
                br["coverage"] = compute_coverage(
                    br["flow"],
                    bc_original.get("acreage", 0),
                    bc_original.get("farm_type", "general"),
                    water_level,
                )
                br["farm_type"] = bc_original.get("farm_type", "general")
                br["acreage"] = bc_original.get("acreage", 0)
            else:
                br["coverage"] = 0.0
                br["farm_type"] = "general"
                br["acreage"] = 0
        results.append({
            "date": date,
            "water_level": water_level,
            "total_flow": round(total_flow, 4),
            "branches": distribution,
            "over_allocated": check_over_allocation(total_flow, distribution),
            "seasonal_rule_id": matched_seasonal["id"] if matched_seasonal else None,
            "seasonal_rule_name": matched_seasonal.get("name") if matched_seasonal else None,
            "applied_rule": active_rule,
        })
    return results


def detect_missing_dates(date_strs: List[str]) -> List[str]:
    if len(date_strs) < 2:
        return []
    sorted_dates = sorted(date_strs)
    missing = []
    try:
        current = datetime.strptime(sorted_dates[0], "%Y-%m-%d")
        end = datetime.strptime(sorted_dates[-1], "%Y-%m-%d")
        date_set = set(sorted_dates)
        while current <= end:
            d = current.strftime("%Y-%m-%d")
            if d not in date_set:
                missing.append(d)
            current += timedelta(days=1)
    except (ValueError, TypeError):
        return []
    return missing


def suggest_filled_levels(missing_dates: List[str], existing_levels: List[dict]) -> List[dict]:
    if not missing_dates or not existing_levels:
        return []
    sorted_levels = sorted(existing_levels, key=lambda x: x["date"])
    date_to_level = {wl["date"]: wl["level"] for wl in sorted_levels}
    existing_dates = sorted(date_to_level.keys())
    suggestions = []
    for md in missing_dates:
        before = None
        after = None
        for d in existing_dates:
            if d < md:
                before = d
            if d > md and after is None:
                after = d
                break
        if before and after:
            try:
                dt_before = datetime.strptime(before, "%Y-%m-%d")
                dt_after = datetime.strptime(after, "%Y-%m-%d")
                dt_md = datetime.strptime(md, "%Y-%m-%d")
                total_days = (dt_after - dt_before).days
                if total_days > 0:
                    offset = (dt_md - dt_before).days
                    lb = date_to_level[before]
                    la = date_to_level[after]
                    interpolated = lb + (la - lb) * (offset / total_days)
                    suggestions.append({"date": md, "level": round(interpolated, 4), "method": "interpolate", "confidence": "high"})
                else:
                    suggestions.append({"date": md, "level": round(date_to_level[before], 4), "method": "previous", "confidence": "medium"})
            except (ValueError, TypeError):
                if before:
                    suggestions.append({"date": md, "level": round(date_to_level[before], 4), "method": "previous", "confidence": "low"})
        elif before:
            suggestions.append({"date": md, "level": round(date_to_level[before], 4), "method": "previous", "confidence": "low"})
        elif after:
            suggestions.append({"date": md, "level": round(date_to_level[after], 4), "method": "next", "confidence": "low"})
    return suggestions


def detect_anomalies(water_levels: List[dict]) -> List[dict]:
    if len(water_levels) < 3:
        return []
    sorted_levels = sorted(water_levels, key=lambda x: x["date"])
    levels = [wl["level"] for wl in sorted_levels]
    n = len(levels)
    mean = sum(levels) / n
    variance = sum((x - mean) ** 2 for x in levels) / n
    std = math.sqrt(variance) if variance > 0 else 0
    anomalies = []
    if std > 0:
        for i, wl in enumerate(sorted_levels):
            z = (wl["level"] - mean) / std
            if abs(z) > 2.5:
                anomalies.append({
                    "date": wl["date"],
                    "level": wl["level"],
                    "anomaly_type": "outlier",
                    "detail": f"水位 {wl['level']:.4f} 偏离均值 {mean:.4f} 达 {abs(z):.2f} 个标准差",
                    "suggestion": f"建议核实该日期数据，合理范围约为 {max(0, mean-2*std):.4f} ~ {mean+2*std:.4f}",
                })
    for i in range(1, n):
        diff = abs(levels[i] - levels[i-1])
        if mean > 0 and diff > mean * 0.6:
            anomalies.append({
                "date": sorted_levels[i]["date"],
                "level": levels[i],
                "anomaly_type": "sudden_change",
                "detail": f"较前一日骤变 {diff:.4f}，前值 {levels[i-1]:.4f}",
                "suggestion": "建议检查是否存在录入错误或特殊水情事件",
            })
    for wl in sorted_levels:
        if wl["level"] < 0:
            anomalies.append({
                "date": wl["date"],
                "level": wl["level"],
                "anomaly_type": "negative",
                "detail": f"水位为负：{wl['level']}",
                "suggestion": "水位不能为负，请修正",
            })
    return anomalies


def run_consistency_checks(
    scheme_id: int,
    weir_id: int,
    main_canal_id: int,
    results: List[dict],
    water_levels: List[dict],
    branch_canals: List[dict],
) -> List[dict]:
    checks = []
    checks.append({
        "check_type": "has_results",
        "passed": len(results) > 0,
        "detail": f"共有 {len(results)} 天的计算结果" if len(results) > 0 else "方案没有任何计算结果",
    })
    over_alloc_count = sum(1 for r in results if r.get("over_allocated"))
    checks.append({
        "check_type": "no_over_allocation",
        "passed": over_alloc_count == 0,
        "detail": "无超配情况" if over_alloc_count == 0 else f"存在 {over_alloc_count} 天超配水量，需调整闸口或渠宽",
    })
    wl_set = {wl["date"] for wl in water_levels}
    res_set = {r["date"] for r in results}
    missing_in_result = wl_set - res_set
    checks.append({
        "check_type": "all_waterlevels_used",
        "passed": len(missing_in_result) == 0,
        "detail": "所有水位数据均已纳入计算" if len(missing_in_result) == 0 else f"有 {len(missing_in_result)} 条水位未参与计算（如 {sorted(missing_in_result)[:3]}）",
    })
    total_acreage = sum(bc.get("acreage", 0) for bc in branch_canals)
    avg_coverage = 0.0
    coverage_days = 0
    for r in results:
        for br in r.get("branches", []):
            avg_coverage += br.get("coverage", 0)
            coverage_days += 1
    avg_coverage = round(avg_coverage / coverage_days, 4) if coverage_days > 0 else 0
    checks.append({
        "check_type": "coverage_adequate",
        "passed": avg_coverage >= 0.7,
        "detail": f"平均灌溉覆盖率 {avg_coverage*100:.1f}%，满足要求" if avg_coverage >= 0.7 else f"平均灌溉覆盖率仅 {avg_coverage*100:.1f}%，建议提高来水量或优化分水规则",
    })
    bc_count = len(branch_canals)
    zero_flow_branches = 0
    for bc in branch_canals:
        total_bc_flow = 0.0
        for r in results:
            for br in r.get("branches", []):
                if br["branch_canal_id"] == bc["id"]:
                    total_bc_flow += br["flow"]
        if total_bc_flow <= 1e-9:
            zero_flow_branches += 1
    checks.append({
        "check_type": "all_branches_irrigated",
        "passed": bc_count == 0 or zero_flow_branches == 0,
        "detail": "所有支渠均获得水量" if zero_flow_branches == 0 else f"有 {zero_flow_branches} 条支渠始终未获得水量，建议检查闸口设置",
    })
    checks.append({
        "check_type": "has_branch_canals",
        "passed": bc_count > 0,
        "detail": f"共 {bc_count} 条支渠参与分水" if bc_count > 0 else "主渠下没有任何支渠",
    })
    return checks


def detect_gap_segments(date_strs: List[str]) -> List[dict]:
    if len(date_strs) < 2:
        return []
    sorted_dates = sorted(set(date_strs))
    segments = []
    try:
        prev_dt = datetime.strptime(sorted_dates[0], "%Y-%m-%d")
        current_gap_start = None
        current_gap_days = 0
        for i in range(1, len(sorted_dates)):
            curr_dt = datetime.strptime(sorted_dates[i], "%Y-%m-%d")
            diff = (curr_dt - prev_dt).days
            if diff > 1:
                missing_dates = []
                gap_start_dt = prev_dt + timedelta(days=1)
                for j in range(1, diff):
                    missing_dates.append((prev_dt + timedelta(days=j)).strftime("%Y-%m-%d"))
                segments.append({
                    "start_date": sorted_dates[i - 1],
                    "end_date": sorted_dates[i],
                    "gap_start": gap_start_dt.strftime("%Y-%m-%d"),
                    "gap_end": (curr_dt - timedelta(days=1)).strftime("%Y-%m-%d"),
                    "days": diff - 1,
                    "missing_dates": missing_dates,
                    "before_level": None,
                    "after_level": None,
                })
            prev_dt = curr_dt
    except (ValueError, TypeError):
        return []
    return segments


def compute_monthly_averages(water_levels: List[dict]) -> Dict[str, float]:
    month_data: Dict[str, List[float]] = {}
    for wl in water_levels:
        try:
            dt = datetime.strptime(wl["date"], "%Y-%m-%d")
            key = f"{dt.month:02d}"
            if key not in month_data:
                month_data[key] = []
            month_data[key].append(wl["level"])
        except (ValueError, TypeError):
            continue
    return {k: round(sum(v) / len(v), 4) for k, v in month_data.items() if v}


def compute_weekly_averages(water_levels: List[dict]) -> Dict[str, float]:
    week_data: Dict[str, List[float]] = {}
    for wl in water_levels:
        try:
            dt = datetime.strptime(wl["date"], "%Y-%m-%d")
            key = f"{dt.isocalendar()[1]:02d}"
            if key not in week_data:
                week_data[key] = []
            week_data[key].append(wl["level"])
        except (ValueError, TypeError):
            continue
    return {k: round(sum(v) / len(v), 4) for k, v in week_data.items() if v}


def interpolate_linear(before_date: str, after_date: str, before_level: float, after_level: float, target_date: str) -> float:
    try:
        dt_before = datetime.strptime(before_date, "%Y-%m-%d")
        dt_after = datetime.strptime(after_date, "%Y-%m-%d")
        dt_target = datetime.strptime(target_date, "%Y-%m-%d")
        total_days = (dt_after - dt_before).days
        if total_days <= 0:
            return round(before_level, 4)
        offset = (dt_target - dt_before).days
        result = before_level + (after_level - before_level) * (offset / total_days)
        return round(max(0, result), 4)
    except (ValueError, TypeError):
        return round(before_level, 4)


def interpolate_spline(before_dates: List[str], before_levels: List[float], after_dates: List[str], after_levels: List[float], target_date: str) -> float:
    if len(before_dates) < 2 or len(after_dates) < 2:
        if before_levels:
            return round(before_levels[-1], 4)
        return 0.0
    try:
        dt_target = datetime.strptime(target_date, "%Y-%m-%d")
        dt_points = []
        lv_points = []
        for d, l in zip(before_dates[-3:], before_levels[-3:]):
            dt_points.append(datetime.strptime(d, "%Y-%m-%d"))
            lv_points.append(l)
        for d, l in zip(after_dates[:3], after_levels[:3]):
            dt_points.append(datetime.strptime(d, "%Y-%m-%d"))
            lv_points.append(l)
        if len(dt_points) < 3:
            return round((before_levels[-1] + after_levels[0]) / 2, 4)
        day_nums = [(d - dt_points[0]).days for d in dt_points]
        target_day = (dt_target - dt_points[0]).days
        n = len(day_nums)
        result = 0.0
        for i in range(n):
            term = lv_points[i]
            for j in range(n):
                if i != j:
                    if day_nums[i] != day_nums[j]:
                        term *= (target_day - day_nums[j]) / (day_nums[i] - day_nums[j])
                    else:
                        term = 0
                        break
            result += term
        return round(max(0, result), 4)
    except (ValueError, TypeError):
        if before_levels:
            return round(before_levels[-1], 4)
        return 0.0


def rule_based_fill(target_date: str, water_levels: List[dict], monthly_avg: Dict[str, float], weekly_avg: Dict[str, float]) -> float:
    try:
        dt = datetime.strptime(target_date, "%Y-%m-%d")
        m_key = f"{dt.month:02d}"
        w_key = f"{dt.isocalendar()[1]:02d}"
        candidates = []
        if m_key in monthly_avg:
            candidates.append(monthly_avg[m_key])
        if w_key in weekly_avg:
            candidates.append(weekly_avg[w_key])
        if candidates:
            return round(sum(candidates) / len(candidates), 4)
        same_month_years = []
        for wl in water_levels:
            try:
                w_dt = datetime.strptime(wl["date"], "%Y-%m-%d")
                if w_dt.month == dt.month:
                    same_month_years.append(wl["level"])
            except (ValueError, TypeError):
                continue
        if same_month_years:
            return round(sum(same_month_years) / len(same_month_years), 4)
        if water_levels:
            lvls = [wl["level"] for wl in water_levels]
            return round(sum(lvls) / len(lvls), 4)
        return 0.0
    except (ValueError, TypeError):
        if water_levels:
            lvls = [wl["level"] for wl in water_levels]
            return round(sum(lvls) / len(lvls), 4)
        return 0.0


def assess_confidence(method: str, gap_days: int, before_exists: bool, after_exists: bool, surrounding_count: int = 0) -> tuple:
    if method == "linear_interpolate" and before_exists and after_exists:
        if gap_days <= 2:
            return "high", "前后日数据完整，缺口短，线性插值可靠性高"
        elif gap_days <= 7:
            return "medium", "缺口在一周内，前后数据可支撑线性趋势外推"
        else:
            return "low", "缺口超过一周，线性插值可能偏离实际水文过程"
    elif method == "spline_interpolate" and surrounding_count >= 4:
        if gap_days <= 5:
            return "high", "多日数据支撑样条插值，曲线拟合度较好"
        elif gap_days <= 14:
            return "medium", "样条插值覆盖较长缺口，可靠性中等"
        else:
            return "low", "缺口过长，样条插值可能产生不合理震荡"
    elif method == "monthly_average":
        return "medium", "基于同月历史均值，反映季节规律但忽略短期波动"
    elif method == "weekly_average":
        return "medium", "基于同周历史均值，时间分辨率高于月均但数据量较少"
    elif method == "previous_day":
        if before_exists:
            return "low", "直接沿用前一日数据，无法反映日内变化"
        else:
            return "low", "无前置数据，可靠性差"
    elif method == "next_day":
        if after_exists:
            return "low", "直接使用后一日数据，无法反映日内变化"
        else:
            return "low", "无后置数据，可靠性差"
    elif method == "rule_based":
        return "medium", "基于季节/周均规则补录，符合历史规律但缺失突发性"
    else:
        return "low", "修复方法未明确分类"


def generate_gap_fix_suggestions(water_levels: List[dict], gap_segments: List[dict]) -> List[dict]:
    if not water_levels or not gap_segments:
        return []
    sorted_levels = sorted(water_levels, key=lambda x: x["date"])
    date_to_level = {wl["date"]: wl["level"] for wl in sorted_levels}
    existing_dates = sorted(date_to_level.keys())
    monthly_avg = compute_monthly_averages(sorted_levels)
    weekly_avg = compute_weekly_averages(sorted_levels)
    suggestions = []
    for seg in gap_segments:
        seg_start = seg["start_date"]
        seg_end = seg["end_date"]
        before_level = date_to_level.get(seg_start, 0)
        after_level = date_to_level.get(seg_end, 0)
        before_idx = existing_dates.index(seg_start) if seg_start in existing_dates else -1
        after_idx = existing_dates.index(seg_end) if seg_end in existing_dates else -1
        before_dates_3 = existing_dates[max(0, before_idx - 2):before_idx + 1] if before_idx >= 0 else []
        before_levels_3 = [date_to_level[d] for d in before_dates_3]
        after_dates_3 = existing_dates[after_idx:after_idx + 3] if after_idx >= 0 else []
        after_levels_3 = [date_to_level[d] for d in after_dates_3]
        for md in seg["missing_dates"]:
            alternatives = []
            if before_level is not None and after_level is not None:
                lin_val = interpolate_linear(seg_start, seg_end, before_level, after_level, md)
                conf_lin, basis_lin = assess_confidence(
                    "linear_interpolate", seg["days"], True, True
                )
                alternatives.append({
                    "method": "linear_interpolate",
                    "method_label": "线性插值",
                    "suggested_level": lin_val,
                    "confidence": conf_lin,
                    "basis": basis_lin + f"（前日{before_level:.4f}m，后日{after_level:.4f}m，缺口{seg['days']}天）",
                })
            if len(before_dates_3) + len(after_dates_3) >= 4:
                spline_val = interpolate_spline(before_dates_3, before_levels_3, after_dates_3, after_levels_3, md)
                conf_sp, basis_sp = assess_confidence(
                    "spline_interpolate", seg["days"], True, True,
                    len(before_dates_3) + len(after_dates_3)
                )
                alternatives.append({
                    "method": "spline_interpolate",
                    "method_label": "样条插值",
                    "suggested_level": spline_val,
                    "confidence": conf_sp,
                    "basis": basis_sp + f"（使用周边{len(before_dates_3) + len(after_dates_3)}个已知点拟合）",
                })
            rule_val = rule_based_fill(md, sorted_levels, monthly_avg, weekly_avg)
            conf_rb, basis_rb = assess_confidence("rule_based", seg["days"], True, True)
            alternatives.append({
                "method": "rule_based",
                "method_label": "规则补录",
                "suggested_level": rule_val,
                "confidence": conf_rb,
                "basis": basis_rb,
            })
            alternatives.sort(key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x["confidence"], 3))
            best = alternatives[0]
            suggestions.append({
                "date": md,
                "gap_segment": f"{seg['gap_start']} ~ {seg['gap_end']}",
                "gap_days": seg["days"],
                "before_date": seg_start,
                "before_level": before_level,
                "after_date": seg_end,
                "after_level": after_level,
                "recommended_method": best["method"],
                "recommended_method_label": best["method_label"],
                "recommended_level": best["suggested_level"],
                "recommended_confidence": best["confidence"],
                "recommended_basis": best["basis"],
                "alternatives": alternatives,
            })
    return suggestions


def compute_impact_analysis(
    weir_id: int,
    target_date: str,
    before_level: Optional[float],
    after_level: float,
    main_canal_width: float,
    branch_canals: List[dict],
    rule: str = "equal",
) -> dict:
    impact = {
        "flow_before": 0.0,
        "flow_after": 0.0,
        "flow_delta": 0.0,
        "coverage_before": 0.0,
        "coverage_after": 0.0,
        "coverage_delta": 0.0,
        "branch_details": [],
        "publishable_before": True,
        "publishable_after": True,
    }
    if before_level is not None and before_level > 0:
        total_flow_before = compute_main_canal_flow(before_level, main_canal_width)
        branch_data_before = []
        for bc in branch_canals:
            branch_data_before.append({
                "id": bc["id"],
                "name": bc["name"],
                "position": bc["position"],
                "width": bc["width"],
                "acreage": bc.get("acreage", 0),
                "farm_type": bc.get("farm_type", "general"),
                "gate_opening": bc.get("gate_opening", 100),
                "water_level": before_level,
            })
        dist_before = compute_distribution(total_flow_before, branch_data_before, rule)
        impact["flow_before"] = total_flow_before
        impact["publishable_before"] = not check_over_allocation(total_flow_before, dist_before)
        cov_sum_before = 0.0
        for br in dist_before:
            bc_orig = next((b for b in branch_data_before if b["id"] == br["branch_canal_id"]), None)
            cov = compute_coverage(
                br["flow"], bc_orig.get("acreage", 0) if bc_orig else 0,
                bc_orig.get("farm_type", "general") if bc_orig else "general", before_level,
            )
            cov_sum_before += cov
            impact["branch_details"].append({
                "branch_canal_id": br["branch_canal_id"],
                "name": br["name"],
                "flow_before": round(br["flow"], 4),
                "coverage_before": round(cov, 4),
                "flow_after": 0.0,
                "coverage_after": 0.0,
                "flow_delta": 0.0,
                "coverage_delta": 0.0,
            })
        impact["coverage_before"] = round(cov_sum_before / len(dist_before), 4) if dist_before else 0.0
    if after_level > 0:
        total_flow_after = compute_main_canal_flow(after_level, main_canal_width)
        branch_data_after = []
        for bc in branch_canals:
            branch_data_after.append({
                "id": bc["id"],
                "name": bc["name"],
                "position": bc["position"],
                "width": bc["width"],
                "acreage": bc.get("acreage", 0),
                "farm_type": bc.get("farm_type", "general"),
                "gate_opening": bc.get("gate_opening", 100),
                "water_level": after_level,
            })
        dist_after = compute_distribution(total_flow_after, branch_data_after, rule)
        impact["flow_after"] = total_flow_after
        impact["flow_delta"] = round(total_flow_after - impact["flow_before"], 4)
        impact["publishable_after"] = not check_over_allocation(total_flow_after, dist_after)
        cov_sum_after = 0.0
        for br in dist_after:
            bc_orig = next((b for b in branch_data_after if b["id"] == br["branch_canal_id"]), None)
            cov = compute_coverage(
                br["flow"], bc_orig.get("acreage", 0) if bc_orig else 0,
                bc_orig.get("farm_type", "general") if bc_orig else "general", after_level,
            )
            cov_sum_after += cov
            existing = next((bd for bd in impact["branch_details"] if bd["branch_canal_id"] == br["branch_canal_id"]), None)
            if existing:
                existing["flow_after"] = round(br["flow"], 4)
                existing["coverage_after"] = round(cov, 4)
                existing["flow_delta"] = round(br["flow"] - existing["flow_before"], 4)
                existing["coverage_delta"] = round(cov - existing["coverage_before"], 4)
            else:
                impact["branch_details"].append({
                    "branch_canal_id": br["branch_canal_id"],
                    "name": br["name"],
                    "flow_before": 0.0,
                    "coverage_before": 0.0,
                    "flow_after": round(br["flow"], 4),
                    "coverage_after": round(cov, 4),
                    "flow_delta": round(br["flow"], 4),
                    "coverage_delta": round(cov, 4),
                })
        impact["coverage_after"] = round(cov_sum_after / len(dist_after), 4) if dist_after else 0.0
        impact["coverage_delta"] = round(impact["coverage_after"] - impact["coverage_before"], 4)
    return impact


def scan_water_level_quality(water_levels: List[dict]) -> dict:
    total = len(water_levels)
    if total == 0:
        return {
            "total_records": 0,
            "simulated_count": 0,
            "historical_count": 0,
            "missing_count": 0,
            "gap_segments": [],
            "longest_gap_days": 0,
            "date_range": None,
            "completeness": 0.0,
        }
    sorted_levels = sorted(water_levels, key=lambda x: x["date"])
    dates = [wl["date"] for wl in sorted_levels]
    try:
        first_dt = datetime.strptime(dates[0], "%Y-%m-%d")
        last_dt = datetime.strptime(dates[-1], "%Y-%m-%d")
        total_expected = (last_dt - first_dt).days + 1
    except (ValueError, TypeError):
        first_dt = None
        last_dt = None
        total_expected = total
    simulated = sum(1 for wl in water_levels if wl.get("is_simulated"))
    historical = total - simulated
    gaps = detect_gap_segments(dates)
    missing_count = sum(g["days"] for g in gaps)
    longest_gap = max((g["days"] for g in gaps), default=0)
    completeness = round(total / max(1, total + missing_count), 4)
    return {
        "total_records": total,
        "simulated_count": simulated,
        "historical_count": historical,
        "missing_count": missing_count,
        "gap_segments": gaps,
        "longest_gap_days": longest_gap,
        "date_range": {
            "start": dates[0],
            "end": dates[-1],
            "total_expected_days": total_expected,
        },
        "completeness": completeness,
    }
