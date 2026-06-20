import json
from typing import Optional, List, Dict
from fastapi import APIRouter, Request, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from app.database import get_db
from app.calc_press import (
    analyze_experiment_review,
    compute_fitness,
    METRIC_LABELS,
    METRIC_UNITS,
)

router = APIRouter()

REVIEW_TYPE_LABELS = {
    "full": "完整复盘",
    "quick": "快速复盘",
    "metrics": "指标复盘",
    "process": "过程复盘",
}

ASSESSMENT_LABELS = {
    "excellent": "优秀",
    "good": "良好",
    "fair": "一般",
    "poor": "较差",
    "incomplete": "不完整",
}

PRIORITY_LABELS = {
    "high": "高",
    "medium": "中",
    "low": "低",
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


@router.get("/weirs/{weir_id}/review", response_class=HTMLResponse)
def review_page(request: Request, weir_id: int):
    db = get_db()
    weir = db.execute("SELECT * FROM weirs WHERE id = ?", (weir_id,)).fetchone()
    if not weir:
        db.close()
        raise HTTPException(status_code=404, detail="堰坝不存在")

    experiments = db.execute(
        "SELECT * FROM press_experiments WHERE weir_id = ? ORDER BY created_at ASC",
        (weir_id,),
    ).fetchall()

    reviews = db.execute(
        "SELECT * FROM experiment_reviews WHERE weir_id = ? ORDER BY id DESC",
        (weir_id,),
    ).fetchall()

    structures = db.execute(
        "SELECT * FROM press_structures WHERE weir_id = ? ORDER BY id DESC",
        (weir_id,),
    ).fetchall()

    structure_map = {s["id"]: dict(s) for s in structures}

    change_logs = db.execute(
        """SELECT scl.*, ps.name as structure_name
           FROM structure_change_logs scl
           JOIN press_structures ps ON scl.structure_id = ps.id
           WHERE ps.weir_id = ?
           ORDER BY scl.created_at ASC""",
        (weir_id,),
    ).fetchall()

    db.close()

    return getattr(request.app.state, "templates", None).TemplateResponse(
        request,
        "review.html",
        {
            "weir": weir,
            "experiments": [_get_experiment_dict(e) for e in experiments],
            "reviews": [dict(r) for r in reviews],
            "structure_map": structure_map,
            "change_logs": [dict(l) for l in change_logs],
            "review_type_labels": REVIEW_TYPE_LABELS,
            "assessment_labels": ASSESSMENT_LABELS,
            "priority_labels": PRIORITY_LABELS,
            "metric_labels": METRIC_LABELS,
            "metric_units": METRIC_UNITS,
        },
    )


@router.post("/weirs/{weir_id}/reviews")
def create_review(
    weir_id: int,
    name: str = Form(...),
    experiment_ids: str = Form(""),
    review_type: str = Form("full"),
    success_summary: str = Form(""),
    issue_summary: str = Form(""),
    lesson_learned: str = Form(""),
    improvement_suggestions: str = Form(""),
    key_findings: str = Form(""),
    reviewer: str = Form(""),
):
    exp_id_list = [int(x.strip()) for x in experiment_ids.split(",") if x.strip().isdigit()]

    db = get_db()
    experiments = []
    if exp_id_list:
        placeholders = ",".join("?" * len(exp_id_list))
        experiments = db.execute(
            f"SELECT * FROM press_experiments WHERE id IN ({placeholders}) ORDER BY created_at ASC",
            exp_id_list,
        ).fetchall()
    else:
        experiments = db.execute(
            "SELECT * FROM press_experiments WHERE weir_id = ? ORDER BY created_at ASC",
            (weir_id,),
        ).fetchall()

    if not experiments:
        db.close()
        raise HTTPException(status_code=400, detail="没有可复盘的实验数据")

    exp_dicts = [_get_experiment_dict(e) for e in experiments]
    analysis = analyze_experiment_review(exp_dicts, review_type)

    final_success = success_summary or analysis["success_summary"]
    final_issues = issue_summary or analysis["issue_summary"]
    final_lessons = lesson_learned or analysis["lesson_learned"]

    suggestions_list = analysis["improvement_suggestions"]
    if improvement_suggestions:
        suggestions_list.append({
            "priority": "medium",
            "content": improvement_suggestions,
            "expected_improvement": "用户自定义建议",
        })
    suggestions_json = json.dumps(suggestions_list)

    findings_list = analysis["key_findings"]
    if key_findings:
        findings_list.append(key_findings)
    findings_json = json.dumps(findings_list)

    cur = db.execute(
        """INSERT INTO experiment_reviews
           (weir_id, name, experiment_ids, review_type,
            success_summary, issue_summary, lesson_learned,
            improvement_suggestions, key_findings, reviewer)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            weir_id, name, experiment_ids, review_type,
            final_success, final_issues, final_lessons,
            suggestions_json, findings_json, reviewer,
        ),
    )

    if reviewer:
        db.execute(
            "UPDATE experiment_reviews SET reviewed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (cur.lastrowid,),
        )

    db.commit()
    db.close()

    return RedirectResponse(
        url=f"/weirs/{weir_id}/review#review-{cur.lastrowid}",
        status_code=303,
    )


@router.get("/api/reviews/{review_id}/results")
def get_review_results(review_id: int):
    db = get_db()
    review = db.execute(
        "SELECT * FROM experiment_reviews WHERE id = ?", (review_id,)
    ).fetchone()
    if not review:
        db.close()
        raise HTTPException(status_code=404, detail="复盘不存在")

    exp_ids = [int(x.strip()) for x in review["experiment_ids"].split(",") if x.strip().isdigit()]
    experiments = []
    if exp_ids:
        placeholders = ",".join("?" * len(exp_ids))
        experiments = db.execute(
            f"SELECT * FROM press_experiments WHERE id IN ({placeholders}) ORDER BY created_at ASC",
            exp_ids,
        ).fetchall()
    else:
        experiments = db.execute(
            "SELECT * FROM press_experiments WHERE weir_id = ? ORDER BY created_at ASC",
            (review["weir_id"],),
        ).fetchall()

    exp_dicts = [_get_experiment_dict(e) for e in experiments]
    analysis = analyze_experiment_review(exp_dicts, review["review_type"])

    improvement_suggestions = json.loads(review["improvement_suggestions"]) if review["improvement_suggestions"] else []
    key_findings = json.loads(review["key_findings"]) if review["key_findings"] else []

    structure_map = {}
    for e in experiments:
        if e["structure_id"]:
            s = db.execute(
                "SELECT * FROM press_structures WHERE id = ?", (e["structure_id"],)
            ).fetchone()
            if s:
                structure_map[e["structure_id"]] = dict(s)

    timelines = []
    for i, exp in enumerate(exp_dicts):
        timelines.append({
            "step": i + 1,
            "experiment_id": exp["id"],
            "experiment_name": exp["name"],
            "date": exp["created_at"],
            "metrics": {
                "juice_yield": exp["juice_yield"],
                "peak_pressure": exp["peak_pressure"],
                "residue_moisture": exp["residue_moisture"],
                "steady_juice_time": exp["steady_juice_time"],
            },
            "fitness": compute_fitness(exp),
            "notes": exp["notes"],
        })

    db.close()

    return {
        "review": dict(review),
        "experiments": exp_dicts,
        "analysis": analysis,
        "timeline": timelines,
        "improvement_suggestions": improvement_suggestions,
        "key_findings": key_findings,
        "structure_map": structure_map,
        "metric_labels": METRIC_LABELS,
        "metric_units": METRIC_UNITS,
        "assessment_labels": ASSESSMENT_LABELS,
        "priority_labels": PRIORITY_LABELS,
    }


@router.post("/reviews/{review_id}/delete")
def delete_review(review_id: int):
    db = get_db()
    review = db.execute(
        "SELECT * FROM experiment_reviews WHERE id = ?", (review_id,)
    ).fetchone()
    if not review:
        db.close()
        raise HTTPException(status_code=404, detail="复盘不存在")
    weir_id = review["weir_id"]
    db.execute("DELETE FROM experiment_reviews WHERE id = ?", (review_id,))
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/review", status_code=303)


@router.get("/api/weirs/{weir_id}/review/preview")
def preview_review(
    weir_id: int,
    experiment_ids: Optional[str] = Query(None),
    review_type: str = Query("full"),
):
    db = get_db()
    experiments = []
    if experiment_ids:
        exp_id_list = [int(x.strip()) for x in experiment_ids.split(",") if x.strip().isdigit()]
        if exp_id_list:
            placeholders = ",".join("?" * len(exp_id_list))
            experiments = db.execute(
                f"SELECT * FROM press_experiments WHERE id IN ({placeholders}) ORDER BY created_at ASC",
                exp_id_list,
            ).fetchall()

    if not experiments:
        experiments = db.execute(
            "SELECT * FROM press_experiments WHERE weir_id = ? ORDER BY created_at ASC",
            (weir_id,),
        ).fetchall()

    if not experiments:
        db.close()
        return {
            "analysis": None,
            "message": "没有可复盘的实验数据",
        }

    exp_dicts = [_get_experiment_dict(e) for e in experiments]
    analysis = analyze_experiment_review(exp_dicts, review_type)

    timelines = []
    for i, exp in enumerate(exp_dicts):
        timelines.append({
            "step": i + 1,
            "experiment_id": exp["id"],
            "experiment_name": exp["name"],
            "date": exp["created_at"],
            "metrics": {
                "juice_yield": exp["juice_yield"],
                "peak_pressure": exp["peak_pressure"],
                "residue_moisture": exp["residue_moisture"],
                "steady_juice_time": exp["steady_juice_time"],
            },
            "fitness": compute_fitness(exp),
        })

    db.close()

    return {
        "total_experiments": len(exp_dicts),
        "analysis": analysis,
        "timeline": timelines,
        "metric_labels": METRIC_LABELS,
        "metric_units": METRIC_UNITS,
        "assessment_labels": ASSESSMENT_LABELS,
    }
