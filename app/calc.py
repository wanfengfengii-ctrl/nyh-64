import math
from datetime import datetime, timedelta


def calc_gate_flow(water_level: float, canal_width: float, gate_opening: int) -> float:
    if gate_opening <= 0 or water_level <= 0 or canal_width <= 0:
        return 0.0
    effective_width = canal_width * (gate_opening / 100.0)
    flow = 0.61 * effective_width * math.sqrt(2 * 9.81) * (water_level ** 1.5)
    return flow


def _capacities(branch_canals: list[dict]) -> list[float]:
    caps = []
    for bc in branch_canals:
        caps.append(calc_gate_flow(
            bc.get("water_level", 0),
            bc["width"],
            bc.get("gate_opening", 100),
        ))
    return caps


def distribute_equal(total_flow: float, branch_canals: list[dict]) -> list[dict]:
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


def distribute_downstream_first(total_flow: float, branch_canals: list[dict]) -> list[dict]:
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


def distribute_acreage_ratio(total_flow: float, branch_canals: list[dict]) -> list[dict]:
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


def compute_distribution(total_flow: float, branch_canals: list[dict], rule: str) -> list[dict]:
    fn = RULE_FUNCTIONS.get(rule, distribute_equal)
    return fn(total_flow, branch_canals)


def check_over_allocation(total_flow: float, results: list[dict]) -> bool:
    total_allocated = sum(r["flow"] for r in results)
    return total_allocated > total_flow + 1e-6


def compute_main_canal_flow(water_level: float, main_canal_width: float) -> float:
    if water_level <= 0 or main_canal_width <= 0:
        return 0.0
    flow = main_canal_width * math.sqrt(2 * 9.81) * (water_level ** 1.5)
    return round(flow, 4)


def filter_continuous_dates(dates: list[str]) -> list[str]:
    if not dates:
        return []
    sorted_dates = sorted(dates)
    date_set = set(sorted_dates)
    try:
        current = datetime.strptime(sorted_dates[0], "%Y-%m-%d")
    except ValueError:
        return sorted_dates
    result = []
    for ds in sorted_dates:
        expected = current.strftime("%Y-%m-%d")
        if ds == expected:
            result.append(ds)
        else:
            break
        current += timedelta(days=1)
    return result


def compute_time_series(
    water_levels: list[dict],
    main_canal_width: float,
    branch_canals: list[dict],
    rule: str,
) -> list[dict]:
    results = []
    for wl_record in water_levels:
        water_level = wl_record["level"]
        date = wl_record["date"]
        total_flow = compute_main_canal_flow(water_level, main_canal_width)
        branch_data = []
        for bc in branch_canals:
            branch_data.append({
                "id": bc["id"],
                "name": bc["name"],
                "position": bc["position"],
                "width": bc["width"],
                "acreage": bc.get("acreage", 0),
                "gate_opening": bc.get("gate_opening", 100),
                "water_level": water_level,
            })
        distribution = compute_distribution(total_flow, branch_data, rule)
        results.append({
            "date": date,
            "water_level": water_level,
            "total_flow": round(total_flow, 4),
            "branches": distribution,
            "over_allocated": check_over_allocation(total_flow, distribution),
        })
    return results
