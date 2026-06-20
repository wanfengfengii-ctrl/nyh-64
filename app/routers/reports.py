import json
from typing import Optional, List, Dict
from fastapi import APIRouter, Request, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from app.database import get_db
from app.calc_press import (
    compare_experiments,
    rank_schemes,
    METRIC_LABELS,
    METRIC_UNITS,
    METRIC_OBJECTIVES,
)
from app.models import STRUCTURE_TYPE_LABELS

router = APIRouter()

COMPARISON_TYPE_LABELS = {
    "side_by_side": "并排对比",
    "radar": "雷达图对比",
    "trend": "趋势对比",
    "detailed": "详细对比",
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


@router.get("/weirs/{weir_id}/compare", response_class=HTMLResponse)
def compare_page(request: Request, weir_id: int):
    db = get_db()
    weir = db.execute("SELECT * FROM weirs WHERE id = ?", (weir_id,)).fetchone()
    if not weir:
        db.close()
        raise HTTPException(status_code=404, detail="堰坝不存在")

    experiments = db.execute(
        "SELECT * FROM press_experiments WHERE weir_id = ? ORDER BY id DESC",
        (weir_id,),
    ).fetchall()

    comparisons = db.execute(
        "SELECT * FROM report_comparisons WHERE weir_id = ? ORDER BY id DESC",
        (weir_id,),
    ).fetchall()

    structures = db.execute(
        "SELECT * FROM press_structures WHERE weir_id = ? ORDER BY id DESC",
        (weir_id,),
    ).fetchall()

    structure_map = {s["id"]: dict(s) for s in structures}

    db.close()

    return getattr(request.app.state, "templates", None).TemplateResponse(
        request,
        "compare.html",
        {
            "weir": weir,
            "experiments": [_get_experiment_dict(e) for e in experiments],
            "comparisons": [dict(c) for c in comparisons],
            "structure_map": structure_map,
            "structure_type_labels": STRUCTURE_TYPE_LABELS,
            "comparison_type_labels": COMPARISON_TYPE_LABELS,
            "metric_labels": METRIC_LABELS,
            "metric_units": METRIC_UNITS,
            "metric_objectives": METRIC_OBJECTIVES,
        },
    )


@router.post("/weirs/{weir_id}/comparisons")
def create_comparison(
    weir_id: int,
    name: str = Form(...),
    experiment_ids: str = Form(""),
    comparison_type: str = Form("side_by_side"),
    include_metrics: str = Form(""),
):
    exp_id_list = [int(x.strip()) for x in experiment_ids.split(",") if x.strip().isdigit()]
    if len(exp_id_list) < 2:
        raise HTTPException(status_code=400, detail="请选择至少两个实验进行对比")

    db = get_db()
    placeholders = ",".join("?" * len(exp_id_list))
    experiments = db.execute(
        f"SELECT * FROM press_experiments WHERE id IN ({placeholders}) ORDER BY id",
        exp_id_list,
    ).fetchall()

    if len(experiments) < 2:
        db.close()
        raise HTTPException(status_code=404, detail="未找到足够的实验数据")

    exp_dicts = [_get_experiment_dict(e) for e in experiments]

    metrics_to_include = [
        m.strip() for m in include_metrics.split(",") if m.strip()
    ] if include_metrics else None

    comparison_result = compare_experiments(exp_dicts, metrics_to_include)

    report_content = json.dumps(comparison_result)

    cur = db.execute(
        """INSERT INTO report_comparisons
           (weir_id, name, experiment_ids, comparison_type, include_metrics, report_content)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            weir_id, name, experiment_ids,
            comparison_type, include_metrics, report_content,
        ),
    )
    db.commit()
    db.close()

    return RedirectResponse(
        url=f"/weirs/{weir_id}/compare#comparison-{cur.lastrowid}",
        status_code=303,
    )


@router.get("/api/comparisons/{comparison_id}/results")
def get_comparison_results(comparison_id: int):
    db = get_db()
    comparison = db.execute(
        "SELECT * FROM report_comparisons WHERE id = ?", (comparison_id,)
    ).fetchone()
    if not comparison:
        db.close()
        raise HTTPException(status_code=404, detail="对比不存在")

    exp_ids = [int(x.strip()) for x in comparison["experiment_ids"].split(",") if x.strip().isdigit()]
    placeholders = ",".join("?" * len(exp_ids)) if exp_ids else ""
    experiments = []
    if exp_ids:
        experiments = db.execute(
            f"SELECT * FROM press_experiments WHERE id IN ({placeholders}) ORDER BY id",
            exp_ids,
        ).fetchall()

    results = json.loads(comparison["report_content"]) if comparison["report_content"] else {}

    structure_map = {}
    for e in experiments:
        if e["structure_id"]:
            s = db.execute(
                "SELECT * FROM press_structures WHERE id = ?", (e["structure_id"],)
            ).fetchone()
            if s:
                structure_map[e["structure_id"]] = dict(s)

    db.close()

    return {
        "comparison": dict(comparison),
        "experiments": [_get_experiment_dict(e) for e in experiments],
        "results": results,
        "structure_map": structure_map,
        "metric_labels": METRIC_LABELS,
        "metric_units": METRIC_UNITS,
        "metric_objectives": METRIC_OBJECTIVES,
        "comparison_type_labels": COMPARISON_TYPE_LABELS,
    }


@router.post("/comparisons/{comparison_id}/delete")
def delete_comparison(comparison_id: int):
    db = get_db()
    comparison = db.execute(
        "SELECT * FROM report_comparisons WHERE id = ?", (comparison_id,)
    ).fetchone()
    if not comparison:
        db.close()
        raise HTTPException(status_code=404, detail="对比不存在")
    weir_id = comparison["weir_id"]
    db.execute("DELETE FROM report_comparisons WHERE id = ?", (comparison_id,))
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/compare", status_code=303)


@router.get("/api/weirs/{weir_id}/experiments/compare")
def compare_experiments_api(
    weir_id: int,
    experiment_ids: str = Query(..., description="逗号分隔的实验ID列表"),
    include_metrics: Optional[str] = Query(None),
):
    exp_id_list = [int(x.strip()) for x in experiment_ids.split(",") if x.strip().isdigit()]
    if len(exp_id_list) < 2:
        raise HTTPException(status_code=400, detail="请选择至少两个实验进行对比")

    db = get_db()
    placeholders = ",".join("?" * len(exp_id_list))
    experiments = db.execute(
        f"SELECT * FROM press_experiments WHERE id IN ({placeholders}) ORDER BY id",
        exp_id_list,
    ).fetchall()

    if len(experiments) < 2:
        db.close()
        raise HTTPException(status_code=404, detail="未找到足够的实验数据")

    exp_dicts = [_get_experiment_dict(e) for e in experiments]

    metrics_to_include = None
    if include_metrics:
        metrics_to_include = [m.strip() for m in include_metrics.split(",") if m.strip()]

    result = compare_experiments(exp_dicts, metrics_to_include)

    structure_map = {}
    for e in experiments:
        if e["structure_id"]:
            s = db.execute(
                "SELECT * FROM press_structures WHERE id = ?", (e["structure_id"],)
            ).fetchone()
            if s:
                structure_map[e["structure_id"]] = dict(s)

    db.close()

    return {
        "experiments": exp_dicts,
        "comparison": result,
        "structure_map": structure_map,
        "metric_labels": METRIC_LABELS,
        "metric_units": METRIC_UNITS,
    }
