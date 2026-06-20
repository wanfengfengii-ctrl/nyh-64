import json
from typing import Optional, List, Dict
from fastapi import APIRouter, Request, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from app.database import get_db
from app.calc_press import (
    calculate_change_effect,
    simulate_press,
    METRIC_LABELS,
    METRIC_UNITS,
    METRIC_OBJECTIVES,
)
from app.models import STRUCTURE_TYPE_LABELS

router = APIRouter()

PARAM_LABELS = {
    "screw_diameter": "螺杆直径",
    "screw_pitch": "螺距",
    "screw_lead": "导程",
    "cone_angle": "锥角",
    "gap_size": "间隙大小",
    "compression_ratio": "压缩比",
    "rotation_speed": "转速",
    "feed_rate": "进料速率",
    "moisture_content": "原料含水率",
}

PARAM_UNITS = {
    "screw_diameter": "mm",
    "screw_pitch": "mm",
    "screw_lead": "mm",
    "cone_angle": "°",
    "gap_size": "mm",
    "compression_ratio": "",
    "rotation_speed": "rpm",
    "feed_rate": "kg/h",
    "moisture_content": "%",
}


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


def _get_change_log_dict(log_row) -> Dict:
    return {
        "id": log_row["id"],
        "structure_id": log_row["structure_id"],
        "change_type": log_row["change_type"],
        "param_name": log_row["param_name"],
        "value_before": log_row["value_before"],
        "value_after": log_row["value_after"],
        "juice_yield_before": log_row["juice_yield_before"],
        "juice_yield_after": log_row["juice_yield_after"],
        "peak_pressure_before": log_row["peak_pressure_before"],
        "peak_pressure_after": log_row["peak_pressure_after"],
        "residue_moisture_before": log_row["residue_moisture_before"],
        "residue_moisture_after": log_row["residue_moisture_after"],
        "steady_time_before": log_row["steady_time_before"],
        "steady_time_after": log_row["steady_time_after"],
        "effect_description": log_row["effect_description"],
        "operator": log_row["operator"],
        "change_reason": log_row["change_reason"],
        "created_at": log_row["created_at"],
    }


@router.get("/weirs/{weir_id}/tracking", response_class=HTMLResponse)
def tracking_page(request: Request, weir_id: int):
    db = get_db()
    weir = db.execute("SELECT * FROM weirs WHERE id = ?", (weir_id,)).fetchone()
    if not weir:
        db.close()
        raise HTTPException(status_code=404, detail="堰坝不存在")

    structures = db.execute(
        "SELECT * FROM press_structures WHERE weir_id = ? ORDER BY id DESC",
        (weir_id,),
    ).fetchall()

    change_logs = db.execute(
        """SELECT scl.*, ps.name as structure_name
           FROM structure_change_logs scl
           JOIN press_structures ps ON scl.structure_id = ps.id
           WHERE ps.weir_id = ?
           ORDER BY scl.created_at DESC""",
        (weir_id,),
    ).fetchall()

    structure_stats = {}
    for s in structures:
        logs = db.execute(
            "SELECT * FROM structure_change_logs WHERE structure_id = ? ORDER BY created_at",
            (s["id"],),
        ).fetchall()
        if logs:
            first = logs[0]
            last = logs[-1]
            structure_stats[s["id"]] = {
                "change_count": len(logs),
                "first_change": first["created_at"],
                "last_change": last["created_at"],
                "juice_yield_change": round(
                    (last["juice_yield_after"] or 0) - (first["juice_yield_before"] or 0), 2
                ),
                "peak_pressure_change": round(
                    (last["peak_pressure_after"] or 0) - (first["peak_pressure_before"] or 0), 2
                ),
            }

    db.close()

    return getattr(request.app.state, "templates", None).TemplateResponse(
        request,
        "tracking.html",
        {
            "weir": weir,
            "structures": [_get_structure_dict(s) for s in structures],
            "change_logs": [dict(l) for l in change_logs],
            "structure_stats": structure_stats,
            "structure_type_labels": STRUCTURE_TYPE_LABELS,
            "metric_labels": METRIC_LABELS,
            "metric_units": METRIC_UNITS,
            "param_labels": PARAM_LABELS,
            "param_units": PARAM_UNITS,
        },
    )


@router.post("/structures/{structure_id}/update")
def update_structure(
    structure_id: int,
    name: Optional[str] = Form(None),
    structure_type: Optional[str] = Form(None),
    screw_diameter: Optional[float] = Form(None),
    screw_pitch: Optional[float] = Form(None),
    screw_lead: Optional[float] = Form(None),
    cone_angle: Optional[float] = Form(None),
    gap_size: Optional[float] = Form(None),
    compression_ratio: Optional[float] = Form(None),
    rotation_speed: Optional[float] = Form(None),
    feed_rate: Optional[float] = Form(None),
    material_type: Optional[str] = Form(None),
    moisture_content: Optional[float] = Form(None),
    description: Optional[str] = Form(None),
    operator: str = Form(""),
    change_reason: str = Form(""),
):
    db = get_db()
    structure = db.execute(
        "SELECT * FROM press_structures WHERE id = ?", (structure_id,)
    ).fetchone()
    if not structure:
        db.close()
        raise HTTPException(status_code=404, detail="结构不存在")
    weir_id = structure["weir_id"]

    params_before = _get_structure_dict(structure)
    metrics_before = simulate_press(params_before)

    updates = []
    update_values = []
    param_changes = []

    field_map = {
        "name": name,
        "structure_type": structure_type,
        "screw_diameter": screw_diameter,
        "screw_pitch": screw_pitch,
        "screw_lead": screw_lead,
        "cone_angle": cone_angle,
        "gap_size": gap_size,
        "compression_ratio": compression_ratio,
        "rotation_speed": rotation_speed,
        "feed_rate": feed_rate,
        "material_type": material_type,
        "moisture_content": moisture_content,
        "description": description,
    }

    numeric_params = [
        "screw_diameter", "screw_pitch", "screw_lead",
        "cone_angle", "gap_size", "compression_ratio",
        "rotation_speed", "feed_rate", "moisture_content",
    ]

    for field, value in field_map.items():
        if value is not None:
            updates.append(f"{field} = ?")
            update_values.append(value)
            if field in numeric_params:
                old_val = structure[field]
                if abs(old_val - value) > 1e-9:
                    param_changes.append({
                        "param_name": field,
                        "value_before": old_val,
                        "value_after": value,
                    })

    if not updates:
        db.close()
        return RedirectResponse(
            url=f"/weirs/{weir_id}/tracking#structure-{structure_id}",
            status_code=303,
        )

    update_values.append(structure_id)
    db.execute(
        f"UPDATE press_structures SET {', '.join(updates)} WHERE id = ?",
        update_values,
    )

    if param_changes:
        updated_structure = db.execute(
            "SELECT * FROM press_structures WHERE id = ?", (structure_id,)
        ).fetchone()
        params_after = _get_structure_dict(updated_structure)
        metrics_after = simulate_press(params_after)

        effect = calculate_change_effect(params_before, params_after)
        effect_desc_parts = []
        for metric, info in effect["metrics_effect"].items():
            if info["change_pct"] != 0:
                direction = "↑" if info["is_improvement"] else "↓"
                label = METRIC_LABELS.get(metric, metric)
                effect_desc_parts.append(
                    f"{label}{direction} {info['change_pct']:+.1f}%"
                )
        effect_description = "; ".join(effect_desc_parts) if effect_desc_parts else "无显著变化"

        for pc in param_changes:
            metric_effect = effect["metrics_effect"]
            db.execute(
                """INSERT INTO structure_change_logs
                   (structure_id, change_type, param_name, value_before, value_after,
                    juice_yield_before, juice_yield_after,
                    peak_pressure_before, peak_pressure_after,
                    residue_moisture_before, residue_moisture_after,
                    steady_time_before, steady_time_after,
                    effect_description, operator, change_reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    structure_id,
                    "parameter_change",
                    pc["param_name"],
                    pc["value_before"],
                    pc["value_after"],
                    metrics_before["juice_yield"],
                    metrics_after["juice_yield"],
                    metrics_before["peak_pressure"],
                    metrics_after["peak_pressure"],
                    metrics_before["residue_moisture"],
                    metrics_after["residue_moisture"],
                    metrics_before["steady_juice_time"],
                    metrics_after["steady_juice_time"],
                    effect_description,
                    operator,
                    change_reason,
                ),
            )

    db.commit()
    db.close()

    return RedirectResponse(
        url=f"/weirs/{weir_id}/tracking#structure-{structure_id}",
        status_code=303,
    )


@router.post("/structure-changes/{change_id}/delete")
def delete_change_log(change_id: int):
    db = get_db()
    log = db.execute(
        "SELECT * FROM structure_change_logs WHERE id = ?", (change_id,)
    ).fetchone()
    if not log:
        db.close()
        raise HTTPException(status_code=404, detail="变更记录不存在")

    structure = db.execute(
        "SELECT * FROM press_structures WHERE id = ?", (log["structure_id"],)
    ).fetchone()
    weir_id = structure["weir_id"] if structure else 0

    db.execute("DELETE FROM structure_change_logs WHERE id = ?", (change_id,))
    db.commit()
    db.close()

    return RedirectResponse(url=f"/weirs/{weir_id}/tracking#logs", status_code=303)


@router.get("/api/structures/{structure_id}/compare")
def compare_structure_versions(
    structure_id: int,
    param_name: Optional[str] = Query(None),
    value_before: Optional[float] = Query(None),
    value_after: Optional[float] = Query(None),
):
    db = get_db()
    structure = db.execute(
        "SELECT * FROM press_structures WHERE id = ?", (structure_id,)
    ).fetchone()
    if not structure:
        db.close()
        raise HTTPException(status_code=404, detail="结构不存在")

    params_before = _get_structure_dict(structure)
    params_after = dict(params_before)

    if param_name and value_before is not None and value_after is not None:
        params_before[param_name] = value_before
        params_after[param_name] = value_after

    effect = calculate_change_effect(params_before, params_after)

    db.close()
    return {
        "params_before": params_before,
        "params_after": params_after,
        "effect": effect,
        "metric_labels": METRIC_LABELS,
        "metric_units": METRIC_UNITS,
        "param_labels": PARAM_LABELS,
        "param_units": PARAM_UNITS,
    }


@router.get("/api/structures/{structure_id}/change-history")
def get_structure_change_history(structure_id: int):
    db = get_db()
    structure = db.execute(
        "SELECT * FROM press_structures WHERE id = ?", (structure_id,)
    ).fetchone()
    if not structure:
        db.close()
        raise HTTPException(status_code=404, detail="结构不存在")

    logs = db.execute(
        "SELECT * FROM structure_change_logs WHERE structure_id = ? ORDER BY created_at ASC",
        (structure_id,),
    ).fetchall()

    history = []
    current_params = _get_structure_dict(structure)

    for log in reversed(logs):
        log_dict = _get_change_log_dict(log)
        history.append({
            "change": log_dict,
            "params_snapshot": dict(current_params),
        })
        if log["param_name"] in current_params:
            current_params[log["param_name"]] = log["value_before"]

    history.reverse()

    db.close()
    return {
        "structure": _get_structure_dict(structure),
        "history": history,
        "metric_labels": METRIC_LABELS,
        "param_labels": PARAM_LABELS,
    }


@router.get("/api/weirs/{weir_id}/tracking/summary")
def get_tracking_summary(weir_id: int):
    db = get_db()
    weir = db.execute("SELECT * FROM weirs WHERE id = ?", (weir_id,)).fetchone()
    if not weir:
        db.close()
        raise HTTPException(status_code=404, detail="堰坝不存在")

    structures = db.execute(
        "SELECT * FROM press_structures WHERE weir_id = ?", (weir_id,)
    ).fetchall()

    total_changes = db.execute(
        """SELECT COUNT(*) as cnt FROM structure_change_logs scl
           JOIN press_structures ps ON scl.structure_id = ps.id
           WHERE ps.weir_id = ?""",
        (weir_id,),
    ).fetchone()["cnt"]

    improvements = db.execute(
        """SELECT COUNT(*) as cnt FROM structure_change_logs scl
           JOIN press_structures ps ON scl.structure_id = ps.id
           WHERE ps.weir_id = ?
           AND (juice_yield_after > juice_yield_before
                OR peak_pressure_after < peak_pressure_before
                OR residue_moisture_after < residue_moisture_before)""",
        (weir_id,),
    ).fetchone()["cnt"]

    avg_yield_improvement = 0
    if total_changes > 0:
        result = db.execute(
            """SELECT AVG(juice_yield_after - juice_yield_before) as avg
               FROM structure_change_logs scl
               JOIN press_structures ps ON scl.structure_id = ps.id
               WHERE ps.weir_id = ?""",
            (weir_id,),
        ).fetchone()
        avg_yield_improvement = round(result["avg"] or 0, 2)

    most_changed_param = db.execute(
        """SELECT param_name, COUNT(*) as cnt
           FROM structure_change_logs scl
           JOIN press_structures ps ON scl.structure_id = ps.id
           WHERE ps.weir_id = ?
           GROUP BY param_name
           ORDER BY cnt DESC
           LIMIT 1""",
        (weir_id,),
    ).fetchone()

    db.close()

    return {
        "total_structures": len(structures),
        "total_changes": total_changes,
        "improvement_count": improvements,
        "improvement_rate": round(improvements / total_changes * 100, 1) if total_changes > 0 else 0,
        "avg_yield_improvement": avg_yield_improvement,
        "most_changed_param": most_changed_param["param_name"] if most_changed_param else None,
        "most_changed_count": most_changed_param["cnt"] if most_changed_param else 0,
        "param_labels": PARAM_LABELS,
    }
