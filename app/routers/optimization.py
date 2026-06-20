import json
import threading
from typing import Optional, List, Dict
from fastapi import APIRouter, Request, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from app.database import get_db
from app.calc_press import (
    run_optimization,
    rank_schemes,
    simulate_press,
    compute_fitness,
    DEFAULT_PARAM_RANGES,
    METRIC_LABELS,
    METRIC_UNITS,
    METRIC_OBJECTIVES,
)
from app.models import (
    OPTIMIZATION_ALGORITHM_LABELS,
    RANKING_METHOD_LABELS,
    STRUCTURE_TYPE_LABELS,
)

router = APIRouter()

_optimization_tasks_cache = {}


def _get_structure_dict(structure_row) -> Dict:
    return {
        "id": structure_row["id"],
        "name": structure_row["name"],
        "structure_type": structure_row["structure_type"],
        "screw_diameter": structure_row["screw_diameter"],
        "screw_pitch": structure_row["screw_pitch"],
        "screw_lead": structure_row["screw_lead"],
        "cone_angle": structure_row["cone_angle"],
        "gap_size": structure_row["gap_size"],
        "compression_ratio": structure_row["compression_ratio"],
        "rotation_speed": structure_row["rotation_speed"],
        "feed_rate": structure_row["feed_rate"],
        "material_type": structure_row["material_type"],
        "moisture_content": structure_row["moisture_content"],
        "description": structure_row["description"],
        "created_at": structure_row["created_at"],
    }


def _get_experiment_dict(exp_row) -> Dict:
    return {
        "id": exp_row["id"],
        "name": exp_row["name"],
        "structure_id": exp_row["structure_id"],
        "status": exp_row["status"],
        "juice_yield": exp_row["juice_yield"],
        "peak_pressure": exp_row["peak_pressure"],
        "residue_moisture": exp_row["residue_moisture"],
        "steady_juice_time": exp_row["steady_juice_time"],
        "energy_consumption": exp_row["energy_consumption"],
        "throughput": exp_row["throughput"],
        "experiment_date": exp_row["experiment_date"],
        "operator": exp_row["operator"],
        "notes": exp_row["notes"],
        "created_at": exp_row["created_at"],
    }


def _run_optimization_background(task_id: int, weir_id: int, params: Dict):
    db = get_db()
    try:
        db.execute(
            "UPDATE optimization_tasks SET status = 'running', started_at = CURRENT_TIMESTAMP WHERE id = ?",
            (task_id,),
        )
        db.commit()

        def progress_callback(iteration, max_iter, fitness):
            try:
                progress = int((iteration / max_iter) * 100)
                db.execute(
                    "UPDATE optimization_tasks SET progress = ? WHERE id = ?",
                    (progress, task_id),
                )
                db.commit()
                _optimization_tasks_cache[task_id] = {
                    "progress": progress,
                    "current_fitness": fitness,
                    "iteration": iteration,
                }
            except Exception:
                pass

        param_ranges = json.loads(params.get("param_ranges", "{}")) if params.get("param_ranges") else DEFAULT_PARAM_RANGES
        weights = {
            "juice_yield": params.get("target_juice_yield_weight", 0.3),
            "peak_pressure": params.get("target_peak_pressure_weight", 0.25),
            "residue_moisture": params.get("target_residue_moisture_weight", 0.25),
            "steady_juice_time": params.get("target_steady_time_weight", 0.2),
        }

        base_structure = None
        base_structure_id = params.get("base_structure_id")
        if base_structure_id:
            bs = db.execute(
                "SELECT * FROM press_structures WHERE id = ?", (base_structure_id,)
            ).fetchone()
            if bs:
                base_structure = _get_structure_dict(bs)

        result = run_optimization(
            algorithm=params.get("algorithm", "genetic"),
            param_ranges=param_ranges,
            weights=weights,
            population_size=params.get("population_size", 50),
            max_iterations=params.get("max_iterations", 100),
            mutation_rate=params.get("mutation_rate", 0.1),
            crossover_rate=params.get("crossover_rate", 0.8),
            base_structure=base_structure,
            callback=progress_callback,
        )

        best = result["best_solution"]
        best_params = best["params"]
        best_metrics = best["metrics"]

        cur = db.execute(
            """INSERT INTO press_structures
               (weir_id, name, structure_type, screw_diameter, screw_pitch, screw_lead,
                cone_angle, gap_size, compression_ratio, rotation_speed, feed_rate,
                material_type, moisture_content, description)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                weir_id,
                f"最优结构_{params.get('name', '寻优任务')}",
                best_params.get("structure_type", "screw"),
                best_params.get("screw_diameter", 0),
                best_params.get("screw_pitch", 0),
                best_params.get("screw_lead", 0),
                best_params.get("cone_angle", 0),
                best_params.get("gap_size", 0),
                best_params.get("compression_ratio", 0),
                best_params.get("rotation_speed", 0),
                best_params.get("feed_rate", 0),
                best_params.get("material_type", ""),
                best_params.get("moisture_content", 70),
                f"自动寻优生成，适应度分数: {best['fitness']:.4f}",
            ),
        )
        best_structure_id = cur.lastrowid

        for i, history in enumerate(result["best_history"]):
            params_json = json.dumps(history["params"])
            db.execute(
                """INSERT INTO optimization_results
                   (task_id, iteration, structure_params, juice_yield, peak_pressure,
                    residue_moisture, steady_juice_time, fitness_score, rank, is_pareto)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    history["iteration"],
                    params_json,
                    history["metrics"]["juice_yield"],
                    history["metrics"]["peak_pressure"],
                    history["metrics"]["residue_moisture"],
                    history["metrics"]["steady_juice_time"],
                    history["fitness"],
                    i + 1,
                    1 if history["fitness"] >= best["fitness"] * 0.9 else 0,
                ),
            )

        pareto_front = result.get("pareto_front", [])
        for i, sol in enumerate(pareto_front[:20]):
            params_json = json.dumps(sol["params"])
            db.execute(
                """INSERT INTO optimization_results
                   (task_id, iteration, structure_params, juice_yield, peak_pressure,
                    residue_moisture, steady_juice_time, fitness_score, rank, is_pareto)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    0,
                    params_json,
                    sol["metrics"]["juice_yield"],
                    sol["metrics"]["peak_pressure"],
                    sol["metrics"]["residue_moisture"],
                    sol["metrics"]["steady_juice_time"],
                    sol["fitness"],
                    i + 1,
                    1,
                ),
            )

        db.execute(
            """UPDATE optimization_tasks
               SET status = 'completed', progress = 100, completed_at = CURRENT_TIMESTAMP,
                   best_solution_id = ?
               WHERE id = ?""",
            (best_structure_id, task_id),
        )
        db.commit()

        if task_id in _optimization_tasks_cache:
            del _optimization_tasks_cache[task_id]

    except Exception as e:
        db.execute(
            "UPDATE optimization_tasks SET status = 'failed', error_message = ? WHERE id = ?",
            (str(e), task_id),
        )
        db.commit()
    finally:
        db.close()


@router.get("/weirs/{weir_id}/optimization", response_class=HTMLResponse)
def optimization_page(request: Request, weir_id: int):
    db = get_db()
    weir = db.execute("SELECT * FROM weirs WHERE id = ?", (weir_id,)).fetchone()
    if not weir:
        db.close()
        raise HTTPException(status_code=404, detail="堰坝不存在")

    structures = db.execute(
        "SELECT * FROM press_structures WHERE weir_id = ? ORDER BY id DESC",
        (weir_id,),
    ).fetchall()

    experiments = db.execute(
        "SELECT * FROM press_experiments WHERE weir_id = ? ORDER BY id DESC",
        (weir_id,),
    ).fetchall()

    tasks = db.execute(
        "SELECT * FROM optimization_tasks WHERE weir_id = ? ORDER BY id DESC",
        (weir_id,),
    ).fetchall()

    rankings = db.execute(
        "SELECT * FROM scheme_rankings WHERE weir_id = ? ORDER BY id DESC",
        (weir_id,),
    ).fetchall()

    db.close()

    return getattr(request.app.state, "templates", None).TemplateResponse(
        request,
        "optimization.html",
        {
            "weir": weir,
            "structures": [_get_structure_dict(s) for s in structures],
            "experiments": [_get_experiment_dict(e) for e in experiments],
            "tasks": [dict(t) for t in tasks],
            "rankings": [dict(r) for r in rankings],
            "algorithm_labels": OPTIMIZATION_ALGORITHM_LABELS,
            "ranking_method_labels": RANKING_METHOD_LABELS,
            "structure_type_labels": STRUCTURE_TYPE_LABELS,
            "metric_labels": METRIC_LABELS,
            "metric_units": METRIC_UNITS,
            "default_param_ranges": DEFAULT_PARAM_RANGES,
        },
    )


@router.post("/weirs/{weir_id}/optimization/tasks")
def create_optimization_task(
    weir_id: int,
    name: str = Form(...),
    algorithm: str = Form("genetic"),
    target_juice_yield_weight: float = Form(0.3),
    target_peak_pressure_weight: float = Form(0.25),
    target_residue_moisture_weight: float = Form(0.25),
    target_steady_time_weight: float = Form(0.2),
    population_size: int = Form(50),
    max_iterations: int = Form(100),
    mutation_rate: float = Form(0.1),
    crossover_rate: float = Form(0.8),
    base_structure_id: Optional[str] = Form(""),
):
    base_structure_id_val = int(base_structure_id) if base_structure_id else None
    if abs(target_juice_yield_weight + target_peak_pressure_weight +
           target_residue_moisture_weight + target_steady_time_weight - 1.0) > 0.01:
        raise HTTPException(status_code=400, detail="权重之和必须等于1.0")

    db = get_db()
    cur = db.execute(
        """INSERT INTO optimization_tasks
           (weir_id, name, algorithm, target_juice_yield_weight, target_peak_pressure_weight,
            target_residue_moisture_weight, target_steady_time_weight,
            population_size, max_iterations, mutation_rate, crossover_rate)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            weir_id, name, algorithm,
            target_juice_yield_weight, target_peak_pressure_weight,
            target_residue_moisture_weight, target_steady_time_weight,
            population_size, max_iterations, mutation_rate, crossover_rate,
        ),
    )
    task_id = cur.lastrowid
    db.commit()
    db.close()

    params = {
        "name": name,
        "algorithm": algorithm,
        "target_juice_yield_weight": target_juice_yield_weight,
        "target_peak_pressure_weight": target_peak_pressure_weight,
        "target_residue_moisture_weight": target_residue_moisture_weight,
        "target_steady_time_weight": target_steady_time_weight,
        "population_size": population_size,
        "max_iterations": max_iterations,
        "mutation_rate": mutation_rate,
        "crossover_rate": crossover_rate,
        "base_structure_id": base_structure_id_val,
    }

    thread = threading.Thread(
        target=_run_optimization_background,
        args=(task_id, weir_id, params),
        daemon=True,
    )
    thread.start()

    return RedirectResponse(url=f"/weirs/{weir_id}/optimization", status_code=303)


@router.get("/api/optimization/{task_id}/status")
def get_optimization_status(task_id: int):
    db = get_db()
    task = db.execute(
        "SELECT * FROM optimization_tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if not task:
        db.close()
        raise HTTPException(status_code=404, detail="任务不存在")

    cache_info = _optimization_tasks_cache.get(task_id, {})
    status = {
        "id": task["id"],
        "status": task["status"],
        "progress": task["progress"],
        "current_fitness": cache_info.get("current_fitness"),
        "iteration": cache_info.get("iteration"),
        "best_solution_id": task["best_solution_id"],
        "error_message": task["error_message"],
        "started_at": task["started_at"],
        "completed_at": task["completed_at"],
    }
    db.close()
    return status


@router.get("/api/optimization/{task_id}/results")
def get_optimization_results(task_id: int):
    db = get_db()
    task = db.execute(
        "SELECT * FROM optimization_tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if not task:
        db.close()
        raise HTTPException(status_code=404, detail="任务不存在")

    results = db.execute(
        """SELECT * FROM optimization_results
           WHERE task_id = ? ORDER BY iteration DESC, rank ASC""",
        (task_id,),
    ).fetchall()

    history = db.execute(
        """SELECT * FROM optimization_results
           WHERE task_id = ? AND iteration > 0
           ORDER BY iteration ASC""",
        (task_id,),
    ).fetchall()

    pareto = db.execute(
        """SELECT * FROM optimization_results
           WHERE task_id = ? AND is_pareto = 1
           ORDER BY fitness_score DESC""",
        (task_id,),
    ).fetchall()

    db.close()

    return {
        "task": dict(task),
        "best_solution": json.loads(results[0]["structure_params"]) if results else None,
        "best_metrics": {
            "juice_yield": results[0]["juice_yield"] if results else 0,
            "peak_pressure": results[0]["peak_pressure"] if results else 0,
            "residue_moisture": results[0]["residue_moisture"] if results else 0,
            "steady_juice_time": results[0]["steady_juice_time"] if results else 0,
            "fitness_score": results[0]["fitness_score"] if results else 0,
        } if results else None,
        "convergence_history": [
            {
                "iteration": h["iteration"],
                "fitness": h["fitness_score"],
                "juice_yield": h["juice_yield"],
                "peak_pressure": h["peak_pressure"],
                "residue_moisture": h["residue_moisture"],
                "steady_juice_time": h["steady_juice_time"],
            }
            for h in history
        ],
        "pareto_front": [
            {
                "params": json.loads(p["structure_params"]),
                "metrics": {
                    "juice_yield": p["juice_yield"],
                    "peak_pressure": p["peak_pressure"],
                    "residue_moisture": p["residue_moisture"],
                    "steady_juice_time": p["steady_juice_time"],
                    "fitness": p["fitness_score"],
                },
                "rank": p["rank"],
            }
            for p in pareto
        ],
    }


@router.post("/weirs/{weir_id}/rankings")
def create_ranking(
    weir_id: int,
    name: str = Form(...),
    ranking_method: str = Form("topsis"),
    juice_yield_weight: float = Form(0.3),
    peak_pressure_weight: float = Form(0.25),
    residue_moisture_weight: float = Form(0.25),
    steady_time_weight: float = Form(0.2),
    experiment_ids: str = Form(""),
):
    if abs(juice_yield_weight + peak_pressure_weight +
           residue_moisture_weight + steady_time_weight - 1.0) > 0.01:
        raise HTTPException(status_code=400, detail="权重之和必须等于1.0")

    exp_id_list = [int(x.strip()) for x in experiment_ids.split(",") if x.strip().isdigit()]
    if not exp_id_list:
        raise HTTPException(status_code=400, detail="请选择至少一个实验方案")

    db = get_db()
    placeholders = ",".join("?" * len(exp_id_list))
    experiments = db.execute(
        f"SELECT * FROM press_experiments WHERE id IN ({placeholders})",
        exp_id_list,
    ).fetchall()

    if not experiments:
        db.close()
        raise HTTPException(status_code=404, detail="未找到选中的实验")

    exp_dicts = [_get_experiment_dict(e) for e in experiments]

    weights = {
        "juice_yield": juice_yield_weight,
        "peak_pressure": peak_pressure_weight,
        "residue_moisture": residue_moisture_weight,
        "steady_juice_time": steady_time_weight,
    }

    ranked = rank_schemes(exp_dicts, ranking_method, weights)

    ranking_results = json.dumps([
        {
            "rank": r["rank"],
            "experiment_id": r.get("id"),
            "experiment_name": r.get("name"),
            "topsis_score": r.get("topsis_score"),
            "weighted_score": r.get("weighted_score"),
            "vikor_score": r.get("vikor_score"),
            "metrics": {
                "juice_yield": r.get("juice_yield"),
                "peak_pressure": r.get("peak_pressure"),
                "residue_moisture": r.get("residue_moisture"),
                "steady_juice_time": r.get("steady_juice_time"),
            },
        }
        for r in ranked
    ])

    cur = db.execute(
        """INSERT INTO scheme_rankings
           (weir_id, name, ranking_method, juice_yield_weight, peak_pressure_weight,
            residue_moisture_weight, steady_time_weight, scheme_ids, ranking_results)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            weir_id, name, ranking_method,
            juice_yield_weight, peak_pressure_weight,
            residue_moisture_weight, steady_time_weight,
            experiment_ids, ranking_results,
        ),
    )
    db.commit()
    db.close()

    return RedirectResponse(url=f"/weirs/{weir_id}/optimization#rankings", status_code=303)


@router.get("/api/rankings/{ranking_id}/results")
def get_ranking_results(ranking_id: int):
    db = get_db()
    ranking = db.execute(
        "SELECT * FROM scheme_rankings WHERE id = ?", (ranking_id,)
    ).fetchone()
    if not ranking:
        db.close()
        raise HTTPException(status_code=404, detail="排序不存在")

    results = json.loads(ranking["ranking_results"]) if ranking["ranking_results"] else []
    db.close()

    return {
        "ranking": dict(ranking),
        "results": results,
        "metric_labels": METRIC_LABELS,
        "metric_units": METRIC_UNITS,
    }


@router.post("/weirs/{weir_id}/structures")
def create_structure(
    weir_id: int,
    name: str = Form(...),
    structure_type: str = Form("screw"),
    screw_diameter: float = Form(0.0),
    screw_pitch: float = Form(0.0),
    screw_lead: float = Form(0.0),
    cone_angle: float = Form(0.0),
    gap_size: float = Form(0.0),
    compression_ratio: float = Form(0.0),
    rotation_speed: float = Form(0.0),
    feed_rate: float = Form(0.0),
    material_type: str = Form(""),
    moisture_content: float = Form(70.0),
    description: str = Form(""),
):
    db = get_db()
    cur = db.execute(
        """INSERT INTO press_structures
           (weir_id, name, structure_type, screw_diameter, screw_pitch, screw_lead,
            cone_angle, gap_size, compression_ratio, rotation_speed, feed_rate,
            material_type, moisture_content, description)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            weir_id, name, structure_type,
            screw_diameter, screw_pitch, screw_lead,
            cone_angle, gap_size, compression_ratio,
            rotation_speed, feed_rate,
            material_type, moisture_content, description,
        ),
    )
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/optimization#structures", status_code=303)


@router.post("/weirs/{weir_id}/experiments")
def create_experiment(
    weir_id: int,
    name: str = Form(...),
    structure_id: Optional[str] = Form(""),
    status: str = Form("draft"),
    juice_yield: float = Form(0.0),
    peak_pressure: float = Form(0.0),
    residue_moisture: float = Form(0.0),
    steady_juice_time: float = Form(0.0),
    energy_consumption: float = Form(0.0),
    throughput: float = Form(0.0),
    experiment_date: Optional[str] = Form(None),
    operator: str = Form(""),
    notes: str = Form(""),
):
    structure_id_val = int(structure_id) if structure_id else None
    db = get_db()
    if structure_id_val:
        structure = db.execute(
            "SELECT * FROM press_structures WHERE id = ?", (structure_id_val,)
        ).fetchone()
        if structure and juice_yield <= 0:
            params = _get_structure_dict(structure)
            metrics = simulate_press(params)
            juice_yield = metrics["juice_yield"]
            peak_pressure = metrics["peak_pressure"]
            residue_moisture = metrics["residue_moisture"]
            steady_juice_time = metrics["steady_juice_time"]
            energy_consumption = metrics["energy_consumption"]
            throughput = metrics["throughput"]

    cur = db.execute(
        """INSERT INTO press_experiments
           (weir_id, structure_id, name, status, juice_yield, peak_pressure,
            residue_moisture, steady_juice_time, energy_consumption, throughput,
            experiment_date, operator, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            weir_id, structure_id_val, name, status,
            juice_yield, peak_pressure, residue_moisture,
            steady_juice_time, energy_consumption, throughput,
            experiment_date, operator, notes,
        ),
    )
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/optimization#experiments", status_code=303)


@router.post("/structures/{structure_id}/delete")
def delete_structure(structure_id: int):
    db = get_db()
    structure = db.execute(
        "SELECT * FROM press_structures WHERE id = ?", (structure_id,)
    ).fetchone()
    if not structure:
        db.close()
        raise HTTPException(status_code=404, detail="结构不存在")
    weir_id = structure["weir_id"]
    db.execute("DELETE FROM press_structures WHERE id = ?", (structure_id,))
    db.execute("DELETE FROM structure_change_logs WHERE structure_id = ?", (structure_id,))
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/optimization#structures", status_code=303)


@router.post("/experiments/{experiment_id}/delete")
def delete_experiment(experiment_id: int):
    db = get_db()
    exp = db.execute(
        "SELECT * FROM press_experiments WHERE id = ?", (experiment_id,)
    ).fetchone()
    if not exp:
        db.close()
        raise HTTPException(status_code=404, detail="实验不存在")
    weir_id = exp["weir_id"]
    db.execute("DELETE FROM press_experiments WHERE id = ?", (experiment_id,))
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/optimization#experiments", status_code=303)


@router.post("/optimization/{task_id}/delete")
def delete_optimization_task(task_id: int):
    db = get_db()
    task = db.execute(
        "SELECT * FROM optimization_tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if not task:
        db.close()
        raise HTTPException(status_code=404, detail="任务不存在")
    weir_id = task["weir_id"]
    db.execute("DELETE FROM optimization_results WHERE task_id = ?", (task_id,))
    db.execute("DELETE FROM optimization_tasks WHERE id = ?", (task_id,))
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/optimization#tasks", status_code=303)


@router.post("/rankings/{ranking_id}/delete")
def delete_ranking(ranking_id: int):
    db = get_db()
    ranking = db.execute(
        "SELECT * FROM scheme_rankings WHERE id = ?", (ranking_id,)
    ).fetchone()
    if not ranking:
        db.close()
        raise HTTPException(status_code=404, detail="排序不存在")
    weir_id = ranking["weir_id"]
    db.execute("DELETE FROM scheme_rankings WHERE id = ?", (ranking_id,))
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/optimization#rankings", status_code=303)


@router.get("/api/structures/{structure_id}/simulate")
def simulate_structure(structure_id: int):
    db = get_db()
    structure = db.execute(
        "SELECT * FROM press_structures WHERE id = ?", (structure_id,)
    ).fetchone()
    if not structure:
        db.close()
        raise HTTPException(status_code=404, detail="结构不存在")

    params = _get_structure_dict(structure)
    metrics = simulate_press(params)
    fitness = compute_fitness(metrics)

    db.close()
    return {
        "structure": params,
        "metrics": metrics,
        "fitness_score": fitness,
        "metric_labels": METRIC_LABELS,
        "metric_units": METRIC_UNITS,
    }
