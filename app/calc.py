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
    sorted_dates = sorted(dates)
    return sorted_dates


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
