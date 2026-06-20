import math
import random
import json
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta

DEFAULT_PARAM_RANGES = {
    "screw_diameter": {"min": 100, "max": 500, "step": 10},
    "screw_pitch": {"min": 50, "max": 300, "step": 5},
    "screw_lead": {"min": 50, "max": 300, "step": 5},
    "cone_angle": {"min": 5, "max": 30, "step": 1},
    "gap_size": {"min": 0.1, "max": 5.0, "step": 0.1},
    "compression_ratio": {"min": 1.5, "max": 8.0, "step": 0.1},
    "rotation_speed": {"min": 10, "max": 200, "step": 5},
    "feed_rate": {"min": 100, "max": 2000, "step": 50},
}

METRIC_OBJECTIVES = {
    "juice_yield": "maximize",
    "peak_pressure": "minimize",
    "residue_moisture": "minimize",
    "steady_juice_time": "minimize",
    "energy_consumption": "minimize",
    "throughput": "maximize",
}

METRIC_LABELS = {
    "juice_yield": "出汁率",
    "peak_pressure": "峰值压力",
    "residue_moisture": "残渣含水率",
    "steady_juice_time": "稳定出汁时间",
    "energy_consumption": "能耗",
    "throughput": "处理量",
}

METRIC_UNITS = {
    "juice_yield": "%",
    "peak_pressure": "MPa",
    "residue_moisture": "%",
    "steady_juice_time": "s",
    "energy_consumption": "kWh/t",
    "throughput": "kg/h",
}


def simulate_press(structure_params: Dict) -> Dict:
    """
    基于物理模型的压榨过程模拟
    输入：结构参数
    输出：四个核心指标 + 辅助指标
    """
    screw_diameter = structure_params.get("screw_diameter", 200)
    screw_pitch = structure_params.get("screw_pitch", 100)
    screw_lead = structure_params.get("screw_lead", 100)
    cone_angle = structure_params.get("cone_angle", 15)
    gap_size = structure_params.get("gap_size", 1.0)
    compression_ratio = structure_params.get("compression_ratio", 3.0)
    rotation_speed = structure_params.get("rotation_speed", 60)
    feed_rate = structure_params.get("feed_rate", 500)
    moisture_content = structure_params.get("moisture_content", 70)
    structure_type = structure_params.get("structure_type", "screw")

    type_factor = {
        "screw": 1.0,
        "roller": 0.9,
        "hydraulic": 1.1,
        "pneumatic": 0.85,
        "basket": 0.95,
    }.get(structure_type, 1.0)

    diameter_m = screw_diameter / 1000.0
    pitch_m = screw_pitch / 1000.0
    lead_m = screw_lead / 1000.0
    gap_m = gap_size / 1000.0
    cone_rad = math.radians(cone_angle)

    cross_section_area = math.pi * (diameter_m / 2) ** 2
    volume_per_rev = cross_section_area * lead_m
    throughput = volume_per_rev * rotation_speed * 60 * 800 * type_factor
    throughput = max(10, throughput)

    max_pressure = (compression_ratio * rotation_speed * diameter_m) / (gap_m * 10 + 0.1)
    peak_pressure = max_pressure * math.sin(cone_rad) * type_factor * 1.5
    peak_pressure = max(0.1, min(peak_pressure, 20))

    theoretical_yield = (
        0.5 * math.log(compression_ratio + 1)
        + 0.3 * (moisture_content / 100)
        + 0.2 * (1 - gap_size / 5)
    ) * 100 * type_factor
    speed_penalty = max(0, (rotation_speed - 100) / 100 * 15)
    juice_yield = min(95, max(30, theoretical_yield - speed_penalty))

    pressure_penetration = peak_pressure / (compression_ratio * math.sqrt(gap_size + 0.1))
    residue_moisture = moisture_content * (0.4 + 0.6 / (1 + pressure_penetration))
    residue_moisture = max(5, min(70, residue_moisture))

    filling_time = (feed_rate / throughput) * 30
    compression_time = (compression_ratio / rotation_speed) * 60
    steady_juice_time = filling_time + compression_time + (gap_size * 10)
    steady_juice_time = max(5, min(300, steady_juice_time))

    energy_per_ton = (
        peak_pressure * 10
        + rotation_speed * 0.5
        + feed_rate * 0.01
    ) * type_factor
    energy_consumption = max(1, energy_per_ton)

    return {
        "juice_yield": round(juice_yield, 2),
        "peak_pressure": round(peak_pressure, 2),
        "residue_moisture": round(residue_moisture, 2),
        "steady_juice_time": round(steady_juice_time, 2),
        "energy_consumption": round(energy_consumption, 2),
        "throughput": round(throughput, 2),
    }


def normalize_metrics(experiments: List[Dict], weights: Optional[Dict] = None) -> List[Dict]:
    """标准化指标值到0-1范围"""
    if not experiments:
        return []

    default_weights = {
        "juice_yield": 0.3,
        "peak_pressure": 0.25,
        "residue_moisture": 0.25,
        "steady_juice_time": 0.2,
    }
    if weights is None:
        weights = default_weights

    metrics = ["juice_yield", "peak_pressure", "residue_moisture", "steady_juice_time"]

    min_max = {}
    for m in metrics:
        values = [e.get(m, 0) for e in experiments if e.get(m) is not None]
        if values:
            min_max[m] = {"min": min(values), "max": max(values)}
        else:
            min_max[m] = {"min": 0, "max": 1}

    normalized = []
    for exp in experiments:
        norm_exp = dict(exp)
        norm_values = {}
        for m in metrics:
            val = exp.get(m, 0)
            mn = min_max[m]["min"]
            mx = min_max[m]["max"]
            if mx - mn > 1e-9:
                if METRIC_OBJECTIVES.get(m) == "maximize":
                    norm_values[m] = (val - mn) / (mx - mn)
                else:
                    norm_values[m] = (mx - val) / (mx - mn)
            else:
                norm_values[m] = 1.0
            norm_exp[f"{m}_norm"] = round(norm_values[m], 4)
        norm_exp["_normalized"] = norm_values
        normalized.append(norm_exp)

    return normalized


def topsis_ranking(
    experiments: List[Dict],
    weights: Optional[Dict] = None
) -> List[Dict]:
    """
    TOPSIS (Technique for Order of Preference by Similarity to Ideal Solution)
    多目标排序算法
    """
    default_weights = {
        "juice_yield": 0.3,
        "peak_pressure": 0.25,
        "residue_moisture": 0.25,
        "steady_juice_time": 0.2,
    }
    if weights is None:
        weights = default_weights

    metrics = ["juice_yield", "peak_pressure", "residue_moisture", "steady_juice_time"]
    normalized = normalize_metrics(experiments, weights)

    weighted_normalized = []
    for exp in normalized:
        wn = {}
        for m in metrics:
            w = weights.get(m, 0.25)
            wn[m] = exp.get(f"{m}_norm", 0) * w
        exp["_weighted"] = wn
        weighted_normalized.append(exp)

    ideal_best = {}
    ideal_worst = {}
    for m in metrics:
        values = [exp["_weighted"][m] for exp in weighted_normalized]
        ideal_best[m] = max(values)
        ideal_worst[m] = min(values)

    ranked = []
    for i, exp in enumerate(weighted_normalized):
        d_plus = math.sqrt(sum(
            (exp["_weighted"][m] - ideal_best[m]) ** 2 for m in metrics
        ))
        d_minus = math.sqrt(sum(
            (exp["_weighted"][m] - ideal_worst[m]) ** 2 for m in metrics
        ))
        if d_plus + d_minus > 1e-9:
            score = d_minus / (d_plus + d_minus)
        else:
            score = 0.5

        exp["topsis_score"] = round(score, 4)
        exp["distance_to_best"] = round(d_plus, 4)
        exp["distance_to_worst"] = round(d_minus, 4)
        ranked.append(exp)

    ranked.sort(key=lambda x: x["topsis_score"], reverse=True)
    for i, exp in enumerate(ranked):
        exp["rank"] = i + 1

    return ranked


def weighted_sum_ranking(
    experiments: List[Dict],
    weights: Optional[Dict] = None
) -> List[Dict]:
    """加权求和法排序"""
    default_weights = {
        "juice_yield": 0.3,
        "peak_pressure": 0.25,
        "residue_moisture": 0.25,
        "steady_juice_time": 0.2,
    }
    if weights is None:
        weights = default_weights

    normalized = normalize_metrics(experiments, weights)
    metrics = ["juice_yield", "peak_pressure", "residue_moisture", "steady_juice_time"]

    for exp in normalized:
        score = sum(
            exp.get(f"{m}_norm", 0) * weights.get(m, 0.25)
            for m in metrics
        )
        exp["weighted_score"] = round(score, 4)

    normalized.sort(key=lambda x: x["weighted_score"], reverse=True)
    for i, exp in enumerate(normalized):
        exp["rank"] = i + 1

    return normalized


def vikor_ranking(
    experiments: List[Dict],
    weights: Optional[Dict] = None,
    v: float = 0.5
) -> List[Dict]:
    """
    VIKOR (VlseKriterijumska Optimizacija I Kompromisno Resenje)
    妥协排序法，v=0.5表示在群体最大效用和个体最小遗憾之间取折中
    """
    default_weights = {
        "juice_yield": 0.3,
        "peak_pressure": 0.25,
        "residue_moisture": 0.25,
        "steady_juice_time": 0.2,
    }
    if weights is None:
        weights = default_weights

    metrics = ["juice_yield", "peak_pressure", "residue_moisture", "steady_juice_time"]
    normalized = normalize_metrics(experiments, weights)

    for exp in normalized:
        S = 0
        R = 0
        for m in metrics:
            w = weights.get(m, 0.25)
            f_best = 1.0
            f_actual = exp.get(f"{m}_norm", 0)
            if METRIC_OBJECTIVES.get(m) == "maximize":
                regret = w * (f_best - f_actual)
            else:
                regret = w * (f_best - f_actual)
            S += regret
            R = max(R, regret)
        exp["S"] = round(S, 4)
        exp["R"] = round(R, 4)

    S_min = min(exp["S"] for exp in normalized)
    S_max = max(exp["S"] for exp in normalized)
    R_min = min(exp["R"] for exp in normalized)
    R_max = max(exp["R"] for exp in normalized)

    for exp in normalized:
        if S_max - S_min > 1e-9:
            S_norm = (exp["S"] - S_min) / (S_max - S_min)
        else:
            S_norm = 0
        if R_max - R_min > 1e-9:
            R_norm = (exp["R"] - R_min) / (R_max - R_min)
        else:
            R_norm = 0
        Q = v * S_norm + (1 - v) * R_norm
        exp["vikor_score"] = round(Q, 4)

    normalized.sort(key=lambda x: x["vikor_score"])
    for i, exp in enumerate(normalized):
        exp["rank"] = i + 1

    return normalized


def rank_schemes(
    experiments: List[Dict],
    method: str = "topsis",
    weights: Optional[Dict] = None
) -> List[Dict]:
    """统一排序入口"""
    if method == "topsis":
        return topsis_ranking(experiments, weights)
    elif method == "weighted_sum":
        return weighted_sum_ranking(experiments, weights)
    elif method == "viikor":
        return vikor_ranking(experiments, weights)
    elif method == "ahp":
        return topsis_ranking(experiments, weights)
    elif method == "electre":
        return topsis_ranking(experiments, weights)
    else:
        return topsis_ranking(experiments, weights)


def random_params(param_ranges: Optional[Dict] = None) -> Dict:
    """随机生成参数组合"""
    if param_ranges is None:
        param_ranges = DEFAULT_PARAM_RANGES

    params = {}
    for pname, prange in param_ranges.items():
        min_val = prange.get("min", 0)
        max_val = prange.get("max", 100)
        step = prange.get("step", 1)
        if step >= 1:
            steps = int((max_val - min_val) / step)
            if steps > 0:
                params[pname] = min_val + random.randint(0, steps) * step
            else:
                params[pname] = min_val
        else:
            val = min_val + random.random() * (max_val - min_val)
            params[pname] = round(val / step) * step
    return params


def mutate_params(params: Dict, param_ranges: Optional[Dict] = None, mutation_rate: float = 0.1) -> Dict:
    """参数变异"""
    if param_ranges is None:
        param_ranges = DEFAULT_PARAM_RANGES

    new_params = dict(params)
    for pname, prange in param_ranges.items():
        if random.random() < mutation_rate:
            min_val = prange.get("min", 0)
            max_val = prange.get("max", 100)
            step = prange.get("step", 1)
            if step >= 1:
                steps = int((max_val - min_val) / step)
                if steps > 0:
                    new_params[pname] = min_val + random.randint(0, steps) * step
            else:
                val = min_val + random.random() * (max_val - min_val)
                new_params[pname] = round(val / step) * step
    return new_params


def crossover_params(
    parent1: Dict,
    parent2: Dict,
    crossover_rate: float = 0.8
) -> Tuple[Dict, Dict]:
    """参数交叉"""
    if random.random() > crossover_rate:
        return dict(parent1), dict(parent2)

    child1 = {}
    child2 = {}
    keys = list(parent1.keys())
    cross_point = random.randint(0, len(keys) - 1)

    for i, key in enumerate(keys):
        if i < cross_point:
            child1[key] = parent1[key]
            child2[key] = parent2[key]
        else:
            child1[key] = parent2[key]
            child2[key] = parent1[key]

    return child1, child2


def compute_fitness(
    metrics: Dict,
    weights: Optional[Dict] = None
) -> float:
    """计算适应度分数"""
    default_weights = {
        "juice_yield": 0.3,
        "peak_pressure": 0.25,
        "residue_moisture": 0.25,
        "steady_juice_time": 0.2,
    }
    if weights is None:
        weights = default_weights

    ideal_values = {
        "juice_yield": 95,
        "peak_pressure": 0.1,
        "residue_moisture": 5,
        "steady_juice_time": 5,
    }
    worst_values = {
        "juice_yield": 30,
        "peak_pressure": 20,
        "residue_moisture": 70,
        "steady_juice_time": 300,
    }

    fitness = 0.0
    for m, w in weights.items():
        val = metrics.get(m, 0)
        ideal = ideal_values.get(m, 0)
        worst = worst_values.get(m, 0)

        if METRIC_OBJECTIVES.get(m) == "maximize":
            if worst - ideal > 1e-9:
                normalized = (val - worst) / (ideal - worst)
            else:
                normalized = 1.0
        else:
            if worst - ideal > 1e-9:
                normalized = (worst - val) / (worst - ideal)
            else:
                normalized = 1.0

        normalized = max(0, min(1, normalized))
        fitness += normalized * w

    return round(fitness, 4)


def genetic_optimize(
    param_ranges: Optional[Dict] = None,
    weights: Optional[Dict] = None,
    population_size: int = 50,
    max_iterations: int = 100,
    mutation_rate: float = 0.1,
    crossover_rate: float = 0.8,
    callback=None,
    base_structure: Optional[Dict] = None
) -> Dict:
    """
    遗传算法多目标参数寻优
    """
    if param_ranges is None:
        param_ranges = DEFAULT_PARAM_RANGES

    population = []
    for _ in range(population_size):
        if base_structure and random.random() < 0.3:
            params = mutate_params(base_structure, param_ranges, 0.3)
        else:
            params = random_params(param_ranges)
        metrics = simulate_press(params)
        fitness = compute_fitness(metrics, weights)
        population.append({
            "params": params,
            "metrics": metrics,
            "fitness": fitness,
        })

    best_history = []
    for iteration in range(max_iterations):
        population.sort(key=lambda x: x["fitness"], reverse=True)
        best = population[0]
        best_history.append({
            "iteration": iteration + 1,
            "fitness": best["fitness"],
            "metrics": best["metrics"],
            "params": best["params"],
        })

        if callback:
            try:
                callback(iteration + 1, max_iterations, best["fitness"])
            except Exception:
                pass

        if iteration >= max_iterations - 1:
            break

        elite_count = max(2, population_size // 10)
        elites = population[:elite_count]

        new_population = list(elites)

        while len(new_population) < population_size:
            tournament_size = 5
            candidates = random.sample(population, tournament_size)
            candidates.sort(key=lambda x: x["fitness"], reverse=True)
            parent1 = candidates[0]
            parent2 = candidates[1]

            child1_params, child2_params = crossover_params(
                parent1["params"], parent2["params"], crossover_rate
            )
            child1_params = mutate_params(child1_params, param_ranges, mutation_rate)
            child2_params = mutate_params(child2_params, param_ranges, mutation_rate)

            for child_params in [child1_params, child2_params]:
                if len(new_population) < population_size:
                    metrics = simulate_press(child_params)
                    fitness = compute_fitness(metrics, weights)
                    new_population.append({
                        "params": child_params,
                        "metrics": metrics,
                        "fitness": fitness,
                    })

        population = new_population

    population.sort(key=lambda x: x["fitness"], reverse=True)

    return {
        "best_solution": population[0],
        "population": population,
        "best_history": best_history,
        "pareto_front": [p for p in population if p["fitness"] >= population[0]["fitness"] * 0.9],
    }


def particle_swarm_optimize(
    param_ranges: Optional[Dict] = None,
    weights: Optional[Dict] = None,
    population_size: int = 50,
    max_iterations: int = 100,
    base_structure: Optional[Dict] = None,
    callback=None
) -> Dict:
    """粒子群优化算法"""
    if param_ranges is None:
        param_ranges = DEFAULT_PARAM_RANGES

    particles = []
    for i in range(population_size):
        if base_structure and i < population_size * 0.2:
            params = dict(base_structure)
        else:
            params = random_params(param_ranges)
        metrics = simulate_press(params)
        fitness = compute_fitness(metrics, weights)
        velocity = {p: 0 for p in param_ranges.keys()}
        particles.append({
            "params": params,
            "metrics": metrics,
            "fitness": fitness,
            "velocity": velocity,
            "best_params": dict(params),
            "best_fitness": fitness,
        })

    global_best = max(particles, key=lambda p: p["fitness"])
    best_history = []

    w = 0.7
    c1 = 1.49
    c2 = 1.49

    for iteration in range(max_iterations):
        if callback:
            try:
                callback(iteration + 1, max_iterations, global_best["fitness"])
            except Exception:
                pass

        best_history.append({
            "iteration": iteration + 1,
            "fitness": global_best["fitness"],
            "metrics": global_best["metrics"],
            "params": global_best["params"],
        })

        for p in particles:
            for pname, prange in param_ranges.items():
                r1 = random.random()
                r2 = random.random()

                cognitive = c1 * r1 * (p["best_params"][pname] - p["params"][pname])
                social = c2 * r2 * (global_best["params"][pname] - p["params"][pname])

                p["velocity"][pname] = w * p["velocity"][pname] + cognitive + social

                p["params"][pname] += p["velocity"][pname]
                p["params"][pname] = max(
                    prange["min"], min(prange["max"], p["params"][pname])
                )
                step = prange.get("step", 1)
                p["params"][pname] = round(p["params"][pname] / step) * step

            metrics = simulate_press(p["params"])
            fitness = compute_fitness(metrics, weights)
            p["metrics"] = metrics
            p["fitness"] = fitness

            if fitness > p["best_fitness"]:
                p["best_params"] = dict(p["params"])
                p["best_fitness"] = fitness

            if fitness > global_best["fitness"]:
                global_best = {
                    "params": dict(p["params"]),
                    "metrics": dict(metrics),
                    "fitness": fitness,
                }

    return {
        "best_solution": {
            "params": global_best["params"],
            "metrics": global_best["metrics"],
            "fitness": global_best["fitness"],
        },
        "population": particles,
        "best_history": best_history,
        "pareto_front": [p for p in particles if p["fitness"] >= global_best["fitness"] * 0.9],
    }


def grid_search_optimize(
    param_ranges: Optional[Dict] = None,
    weights: Optional[Dict] = None,
    max_combinations: int = 1000,
    callback=None
) -> Dict:
    """网格搜索（分层抽样）"""
    if param_ranges is None:
        param_ranges = DEFAULT_PARAM_RANGES

    param_values = {}
    total_combinations = 1
    for pname, prange in param_ranges.items():
        min_val = prange["min"]
        max_val = prange["max"]
        step = prange.get("step", 1)

        n_steps = int((max_val - min_val) / step) + 1
        max_steps_per_param = int(max_combinations ** (1 / len(param_ranges)))
        actual_steps = min(n_steps, max_steps_per_param)

        if actual_steps <= 1:
            values = [(min_val + max_val) / 2]
        else:
            actual_step = (max_val - min_val) / (actual_steps - 1)
            values = [min_val + i * actual_step for i in range(actual_steps)]
            values = [round(v / step) * step for v in values]

        param_values[pname] = values
        total_combinations *= len(values)

    all_results = []
    from itertools import product

    combinations = list(product(*param_values.values()))
    param_names = list(param_values.keys())

    for i, combo in enumerate(combinations):
        params = dict(zip(param_names, combo))
        metrics = simulate_press(params)
        fitness = compute_fitness(metrics, weights)

        if callback and i % 10 == 0:
            try:
                callback(i + 1, len(combinations), fitness)
            except Exception:
                pass

        all_results.append({
            "params": params,
            "metrics": metrics,
            "fitness": fitness,
        })

    all_results.sort(key=lambda x: x["fitness"], reverse=True)

    best_history = []
    best_fitness = 0
    for i, r in enumerate(all_results):
        if r["fitness"] > best_fitness:
            best_fitness = r["fitness"]
            best_history.append({
                "iteration": i + 1,
                "fitness": r["fitness"],
                "metrics": r["metrics"],
                "params": r["params"],
            })

    return {
        "best_solution": all_results[0],
        "population": all_results,
        "best_history": best_history,
        "pareto_front": [r for r in all_results if r["fitness"] >= all_results[0]["fitness"] * 0.9],
    }


def run_optimization(
    algorithm: str = "genetic",
    param_ranges: Optional[Dict] = None,
    weights: Optional[Dict] = None,
    population_size: int = 50,
    max_iterations: int = 100,
    mutation_rate: float = 0.1,
    crossover_rate: float = 0.8,
    base_structure: Optional[Dict] = None,
    callback=None
) -> Dict:
    """统一优化入口"""
    if algorithm == "genetic":
        return genetic_optimize(
            param_ranges, weights, population_size, max_iterations,
            mutation_rate, crossover_rate, callback, base_structure
        )
    elif algorithm == "particle_swarm":
        return particle_swarm_optimize(
            param_ranges, weights, population_size, max_iterations,
            base_structure, callback
        )
    elif algorithm == "grid_search":
        return grid_search_optimize(
            param_ranges, weights, population_size * max_iterations, callback
        )
    elif algorithm == "random_search":
        return genetic_optimize(
            param_ranges, weights, population_size, 1,
            1.0, 0.0, callback, base_structure
        )
    elif algorithm == "nsga2":
        result = genetic_optimize(
            param_ranges, weights, population_size, max_iterations,
            mutation_rate, crossover_rate, callback, base_structure
        )
        result["is_multi_objective"] = True
        return result
    else:
        return genetic_optimize(
            param_ranges, weights, population_size, max_iterations,
            mutation_rate, crossover_rate, callback, base_structure
        )


def calculate_change_effect(
    params_before: Dict,
    params_after: Dict
) -> Dict:
    """计算参数改动对指标的影响"""
    metrics_before = simulate_press(params_before)
    metrics_after = simulate_press(params_after)

    effect = {}
    for metric in METRIC_OBJECTIVES.keys():
        before = metrics_before.get(metric, 0)
        after = metrics_after.get(metric, 0)
        if before > 1e-9:
            change_pct = ((after - before) / before) * 100
        else:
            change_pct = 100 if after > 0 else 0

        is_improvement = False
        if METRIC_OBJECTIVES.get(metric) == "maximize":
            is_improvement = after > before
        else:
            is_improvement = after < before

        effect[metric] = {
            "before": round(before, 2),
            "after": round(after, 2),
            "delta": round(after - before, 2),
            "change_pct": round(change_pct, 2),
            "is_improvement": is_improvement,
        }

    overall_score_before = compute_fitness(metrics_before)
    overall_score_after = compute_fitness(metrics_after)

    changed_params = {}
    for pname in set(list(params_before.keys()) + list(params_after.keys())):
        if pname not in ["structure_type", "material_type", "description"]:
            vb = params_before.get(pname, 0)
            va = params_after.get(pname, 0)
            if abs(va - vb) > 1e-9:
                changed_params[pname] = {
                    "before": vb,
                    "after": va,
                    "delta": va - vb,
                }

    return {
        "metrics_effect": effect,
        "changed_params": changed_params,
        "overall_score_before": overall_score_before,
        "overall_score_after": overall_score_after,
        "overall_improvement": overall_score_after > overall_score_before,
        "overall_delta_pct": round(
            ((overall_score_after - overall_score_before) / max(overall_score_before, 1e-9)) * 100,
            2
        ),
    }


def compare_experiments(
    experiments: List[Dict],
    include_metrics: Optional[List[str]] = None
) -> Dict:
    """多实验对比分析"""
    if include_metrics is None:
        include_metrics = [
            "juice_yield", "peak_pressure", "residue_moisture",
            "steady_juice_time", "energy_consumption", "throughput"
        ]

    comparison = {
        "experiments": [],
        "best_values": {},
        "worst_values": {},
        "avg_values": {},
        "ranking_summary": {},
    }

    for exp in experiments:
        exp_data = {
            "id": exp.get("id"),
            "name": exp.get("name"),
            "structure_type": exp.get("structure_type"),
            "metrics": {},
        }
        for m in include_metrics:
            exp_data["metrics"][m] = exp.get(m, 0)
        comparison["experiments"].append(exp_data)

    for m in include_metrics:
        values = [e["metrics"][m] for e in comparison["experiments"]]
        if values:
            if METRIC_OBJECTIVES.get(m) == "maximize":
                best_idx = values.index(max(values))
                worst_idx = values.index(min(values))
            else:
                best_idx = values.index(min(values))
                worst_idx = values.index(max(values))

            comparison["best_values"][m] = {
                "value": values[best_idx],
                "experiment_id": comparison["experiments"][best_idx]["id"],
                "experiment_name": comparison["experiments"][best_idx]["name"],
            }
            comparison["worst_values"][m] = {
                "value": values[worst_idx],
                "experiment_id": comparison["experiments"][worst_idx]["id"],
                "experiment_name": comparison["experiments"][worst_idx]["name"],
            }
            comparison["avg_values"][m] = round(sum(values) / len(values), 2)

    weights = {
        "juice_yield": 0.3,
        "peak_pressure": 0.25,
        "residue_moisture": 0.25,
        "steady_juice_time": 0.2,
    }
    ranked = rank_schemes(experiments, "topsis", weights)

    comparison["ranking_summary"] = [
        {
            "rank": r["rank"],
            "experiment_id": r.get("id"),
            "experiment_name": r.get("name"),
            "topsis_score": r.get("topsis_score"),
            "weighted_score": r.get("weighted_score"),
        }
        for r in ranked
    ]

    return comparison


def analyze_experiment_review(
    experiments: List[Dict],
    review_type: str = "full"
) -> Dict:
    """实验过程复盘分析"""
    if not experiments:
        return {
            "success_summary": "无实验数据",
            "issue_summary": "请先创建实验",
            "lesson_learned": "",
            "improvement_suggestions": [],
            "key_findings": [],
            "metrics_trend": [],
            "overall_assessment": "incomplete",
        }

    sorted_experiments = sorted(experiments, key=lambda x: x.get("created_at", ""))

    weights = {
        "juice_yield": 0.3,
        "peak_pressure": 0.25,
        "residue_moisture": 0.25,
        "steady_juice_time": 0.2,
    }

    metrics_trend = []
    scores = []
    for i, exp in enumerate(sorted_experiments):
        fitness = compute_fitness(exp, weights)
        scores.append(fitness)
        metrics_trend.append({
            "sequence": i + 1,
            "experiment_id": exp.get("id"),
            "experiment_name": exp.get("name"),
            "fitness": fitness,
            "juice_yield": exp.get("juice_yield"),
            "peak_pressure": exp.get("peak_pressure"),
            "residue_moisture": exp.get("residue_moisture"),
            "steady_juice_time": exp.get("steady_juice_time"),
        })

    best_idx = scores.index(max(scores)) if scores else 0
    worst_idx = scores.index(min(scores)) if scores else 0

    best_exp = sorted_experiments[best_idx] if sorted_experiments else None
    worst_exp = sorted_experiments[worst_idx] if sorted_experiments else None

    successes = []
    issues = []
    lessons = []
    suggestions = []
    findings = []

    if best_exp:
        successes.append(f"最佳实验「{best_exp.get('name')}」综合评分达到 {scores[best_idx]:.2f}")
        if best_exp.get("juice_yield", 0) >= 70:
            successes.append(f"出汁率达到 {best_exp.get('juice_yield'):.1f}%，超过70%的优秀水平")
        if best_exp.get("residue_moisture", 100) <= 40:
            successes.append(f"残渣含水率控制在 {best_exp.get('residue_moisture'):.1f}%，低于40%的优秀水平")

    if worst_exp and len(scores) > 1:
        issues.append(f"效果最差的实验「{worst_exp.get('name')}」综合评分仅 {scores[worst_idx]:.2f}")
        score_gap = scores[best_idx] - scores[worst_idx]
        issues.append(f"最佳与最差实验评分差距达 {score_gap:.2f}，参数选择影响显著")

    if len(scores) >= 3:
        improved_count = sum(1 for i in range(1, len(scores)) if scores[i] > scores[i-1])
        if improved_count >= len(scores) * 0.6:
            lessons.append("实验过程中参数调整整体呈优化趋势，说明参数寻优方向正确")
            findings.append("持续优化参数可稳定提升压榨效果")
        else:
            lessons.append("实验过程中评分波动较大，建议采用更系统的参数调整策略")
            findings.append("随机调整参数难以获得稳定提升")

    avg_yield = sum(e.get("juice_yield", 0) for e in sorted_experiments) / len(sorted_experiments)
    if avg_yield < 60:
        suggestions.append({
            "priority": "high",
            "content": f"平均出汁率仅 {avg_yield:.1f}%，建议增大压缩比或减小间隙",
            "expected_improvement": "出汁率预计可提升10-15%",
        })

    avg_pressure = sum(e.get("peak_pressure", 0) for e in sorted_experiments) / len(sorted_experiments)
    if avg_pressure > 12:
        suggestions.append({
            "priority": "high",
            "content": f"平均峰值压力达 {avg_pressure:.1f} MPa，偏高，建议降低转速或增大间隙",
            "expected_improvement": "可降低设备磨损和能耗",
        })

    avg_moisture = sum(e.get("residue_moisture", 0) for e in sorted_experiments) / len(sorted_experiments)
    if avg_moisture > 50:
        suggestions.append({
            "priority": "medium",
            "content": f"平均残渣含水率达 {avg_moisture:.1f}%，建议优化锥角和压缩比",
            "expected_improvement": "含水率预计可降低5-10%",
        })

    suggestions.append({
        "priority": "medium",
        "content": "建议使用自动参数寻优功能进行系统搜索",
        "expected_improvement": "可快速找到更优参数组合",
    })

    if len(sorted_experiments) >= 2:
        first = sorted_experiments[0]
        last = sorted_experiments[-1]
        yield_improvement = last.get("juice_yield", 0) - first.get("juice_yield", 0)
        if yield_improvement > 5:
            findings.append(f"实验过程中出汁率提升了 {yield_improvement:.1f}%，参数优化效果明显")

    overall_assessment = "excellent" if max(scores) >= 0.8 else \
                        "good" if max(scores) >= 0.6 else \
                        "fair" if max(scores) >= 0.4 else "poor"

    return {
        "total_experiments": len(sorted_experiments),
        "best_experiment": best_exp,
        "worst_experiment": worst_exp,
        "best_score": max(scores) if scores else 0,
        "worst_score": min(scores) if scores else 0,
        "avg_score": sum(scores) / len(scores) if scores else 0,
        "score_trend": scores,
        "metrics_trend": metrics_trend,
        "success_summary": "；".join(successes) if successes else "暂无突出成果",
        "issue_summary": "；".join(issues) if issues else "未发现明显问题",
        "lesson_learned": "；".join(lessons) if lessons else "继续积累实验数据",
        "improvement_suggestions": suggestions,
        "key_findings": findings,
        "overall_assessment": overall_assessment,
    }
