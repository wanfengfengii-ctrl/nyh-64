from typing import List, Dict, Optional
from fastapi import APIRouter, Request, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from app.database import get_db
from app.calc import (
    compute_main_canal_flow,
    compute_distribution,
    compute_coverage,
    filter_continuous_dates,
)
from app.models import (
    ScheduleLogCreate,
    GateChangeCreate,
    FARM_TYPE_LABELS,
)

router = APIRouter()

RULE_LABELS = {
    "equal": "均分",
    "downstream_first": "优先下游",
    "acreage_ratio": "按田亩比例",
}


def _build_branch_canals_with_gates(db, main_canal_id):
    bcs = db.execute(
        "SELECT * FROM branch_canals WHERE main_canal_id = ? ORDER BY position, id",
        (main_canal_id,),
    ).fetchall()
    result = []
    for bc in bcs:
        gates = db.execute(
            "SELECT * FROM gates WHERE branch_canal_id = ? ORDER BY id",
            (bc["id"],),
        ).fetchall()
        result.append(
            {
                "id": bc["id"],
                "name": bc["name"],
                "width": bc["width"],
                "acreage": bc["acreage"],
                "farm_type": bc["farm_type"] or "general",
                "position": bc["position"],
                "gates": [dict(g) for g in gates],
            }
        )
    return result


def _compute_metrics_for_state(
    db, weir_id, main_canal_id, branch_canals, water_level, rule
):
    if not main_canal_id or not branch_canals or water_level <= 0:
        return {
            "total_flow": 0.0,
            "avg_coverage": 0.0,
            "branch_flows": {},
            "branch_coverages": {},
        }

    mc = db.execute(
        "SELECT * FROM main_canals WHERE id = ?", (main_canal_id,)
    ).fetchone()
    if not mc:
        return {
            "total_flow": 0.0,
            "avg_coverage": 0.0,
            "branch_flows": {},
            "branch_coverages": {},
        }

    total_flow = compute_main_canal_flow(water_level, mc["width"])

    branch_data = []
    for bc in branch_canals:
        if bc["gates"]:
            avg_opening = sum(g["opening"] for g in bc["gates"]) / len(bc["gates"])
        else:
            avg_opening = 100
        branch_data.append(
            {
                "id": bc["id"],
                "name": bc["name"],
                "position": bc["position"],
                "width": bc["width"],
                "acreage": bc["acreage"],
                "farm_type": bc["farm_type"],
                "gate_opening": avg_opening,
                "water_level": water_level,
            }
        )

    distribution = compute_distribution(total_flow, branch_data, rule)

    branch_flows = {}
    branch_coverages = {}
    total_coverage = 0.0
    count = 0

    for br in distribution:
        bc_original = next((b for b in branch_data if b["id"] == br["branch_canal_id"]), None)
        if bc_original:
            coverage = compute_coverage(
                br["flow"],
                bc_original.get("acreage", 0),
                bc_original.get("farm_type", "general"),
                water_level,
            )
        else:
            coverage = 0.0
        branch_flows[br["branch_canal_id"]] = round(br["flow"], 4)
        branch_coverages[br["branch_canal_id"]] = round(coverage, 4)
        total_coverage += coverage
        count += 1

    avg_coverage = round(total_coverage / count, 4) if count > 0 else 0.0

    return {
        "total_flow": round(total_flow, 4),
        "avg_coverage": avg_coverage,
        "branch_flows": branch_flows,
        "branch_coverages": branch_coverages,
    }


@router.get("/weirs/{weir_id}/schedule-logs", response_class=HTMLResponse)
def schedule_logs_page(request: Request, weir_id: int):
    db = get_db()
    weir = db.execute("SELECT * FROM weirs WHERE id = ?", (weir_id,)).fetchone()
    if not weir:
        db.close()
        raise HTTPException(status_code=404, detail="堰坝不存在")

    logs_raw = db.execute(
        """
        SELECT sl.*, s.name as scheme_name, s.status as scheme_status
        FROM schedule_logs sl
        LEFT JOIN schemes s ON sl.scheme_id = s.id
        WHERE sl.weir_id = ?
        ORDER BY sl.adjust_time DESC
        """,
        (weir_id,),
    ).fetchall()
    logs = [dict(l) for l in logs_raw]

    main_canals_raw = db.execute(
        "SELECT * FROM main_canals WHERE weir_id = ?", (weir_id,)
    ).fetchall()
    main_canals = [dict(mc) for mc in main_canals_raw]

    branch_canals_map = {}
    for mc in main_canals_raw:
        branch_canals_map[mc["id"]] = _build_branch_canals_with_gates(db, mc["id"])

    water_levels_raw = db.execute(
        "SELECT * FROM water_levels WHERE weir_id = ? ORDER BY date", (weir_id,)
    ).fetchall()
    water_levels = [dict(wl) for wl in water_levels_raw]

    schemes_raw = db.execute(
        "SELECT * FROM schemes WHERE weir_id = ? AND status = 'published' ORDER BY id DESC",
        (weir_id,),
    ).fetchall()
    schemes = [dict(s) for s in schemes_raw]

    operators = db.execute(
        "SELECT DISTINCT operator FROM schedule_logs WHERE weir_id = ?",
        (weir_id,),
    ).fetchall()
    operator_list = [o["operator"] for o in operators]

    db.close()

    return getattr(request.app.state, "templates", None).TemplateResponse(
        request,
        "schedule_logs.html",
        {
            "weir": dict(weir),
            "logs": logs,
            "main_canals": main_canals,
            "branch_canals_map": branch_canals_map,
            "water_levels": water_levels,
            "schemes": schemes,
            "rule_labels": RULE_LABELS,
            "farm_type_labels": FARM_TYPE_LABELS,
            "operator_list": operator_list,
        },
    )


@router.get("/weirs/{weir_id}/schedule-logs/new", response_class=HTMLResponse)
def new_schedule_log_page(request: Request, weir_id: int):
    db = get_db()
    weir = db.execute("SELECT * FROM weirs WHERE id = ?", (weir_id,)).fetchone()
    if not weir:
        db.close()
        raise HTTPException(status_code=404, detail="堰坝不存在")

    main_canals_raw = db.execute(
        "SELECT * FROM main_canals WHERE weir_id = ?", (weir_id,)
    ).fetchall()
    main_canals = [dict(mc) for mc in main_canals_raw]

    branch_canals_map = {}
    for mc in main_canals_raw:
        branch_canals_map[mc["id"]] = _build_branch_canals_with_gates(db, mc["id"])

    water_levels_raw = db.execute(
        "SELECT * FROM water_levels WHERE weir_id = ? ORDER BY date DESC", (weir_id,)
    ).fetchall()
    water_levels = [dict(wl) for wl in water_levels_raw]

    schemes_raw = db.execute(
        "SELECT * FROM schemes WHERE weir_id = ? ORDER BY id DESC",
        (weir_id,),
    ).fetchall()
    schemes = [dict(s) for s in schemes_raw]

    db.close()

    return getattr(request.app.state, "templates", None).TemplateResponse(
        request,
        "schedule_log_new.html",
        {
            "weir": dict(weir),
            "main_canals": main_canals,
            "branch_canals_map": branch_canals_map,
            "water_levels": water_levels,
            "schemes": schemes,
            "rule_labels": RULE_LABELS,
            "farm_type_labels": FARM_TYPE_LABELS,
        },
    )


@router.post("/weirs/{weir_id}/schedule-logs")
def create_schedule_log(
    request: Request,
    weir_id: int,
    main_canal_id: int = Form(...),
    scheme_id: Optional[int] = Form(None),
    operator: str = Form(...),
    adjust_reason: str = Form(...),
    water_level_date: str = Form(...),
    water_level: float = Form(...),
    rule_before: str = Form(...),
    rule_after: str = Form(...),
    notes: Optional[str] = Form(""),
):
    db = get_db()
    weir = db.execute("SELECT * FROM weirs WHERE id = ?", (weir_id,)).fetchone()
    if not weir:
        db.close()
        raise HTTPException(status_code=404, detail="堰坝不存在")

    form = request._form
    branch_canals = _build_branch_canals_with_gates(db, main_canal_id)

    gate_changes_data = []
    for bc in branch_canals:
        for g in bc["gates"]:
            before_key = f"gate_before_{g['id']}"
            after_key = f"gate_after_{g['id']}"
            if before_key in form and after_key in form:
                opening_before = int(form[before_key])
                opening_after = int(form[after_key])
                gate_changes_data.append(
                    {
                        "gate_id": g["id"],
                        "branch_canal_id": bc["id"],
                        "branch_canal_name": bc["name"],
                        "gate_name": g["name"],
                        "opening_before": opening_before,
                        "opening_after": opening_after,
                    }
                )

    branch_canals_before = []
    for bc in branch_canals:
        bc_copy = dict(bc)
        bc_copy["gates"] = []
        for g in bc["gates"]:
            gc = next(
                (x for x in gate_changes_data if x["gate_id"] == g["id"]), None
            )
            opening = gc["opening_before"] if gc else g["opening"]
            bc_copy["gates"].append({**dict(g), "opening": opening})
        branch_canals_before.append(bc_copy)

    metrics_before = _compute_metrics_for_state(
        db, weir_id, main_canal_id, branch_canals_before, water_level, rule_before
    )

    branch_canals_after = []
    for bc in branch_canals:
        bc_copy = dict(bc)
        bc_copy["gates"] = []
        for g in bc["gates"]:
            gc = next(
                (x for x in gate_changes_data if x["gate_id"] == g["id"]), None
            )
            opening = gc["opening_after"] if gc else g["opening"]
            bc_copy["gates"].append({**dict(g), "opening": opening})
        branch_canals_after.append(bc_copy)

    metrics_after = _compute_metrics_for_state(
        db, weir_id, main_canal_id, branch_canals_after, water_level, rule_after
    )

    cur = db.execute(
        """
        INSERT INTO schedule_logs
        (weir_id, scheme_id, operator, adjust_reason, water_level, water_level_date,
         rule_before, rule_after, total_flow_before, total_flow_after,
         avg_coverage_before, avg_coverage_after, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            weir_id,
            scheme_id,
            operator,
            adjust_reason,
            water_level,
            water_level_date,
            rule_before,
            rule_after,
            metrics_before["total_flow"],
            metrics_after["total_flow"],
            metrics_before["avg_coverage"],
            metrics_after["avg_coverage"],
            notes,
        ),
    )
    log_id = cur.lastrowid

    for gc in gate_changes_data:
        flow_before = metrics_before["branch_flows"].get(gc["branch_canal_id"], 0)
        flow_after = metrics_after["branch_flows"].get(gc["branch_canal_id"], 0)
        coverage_before = metrics_before["branch_coverages"].get(
            gc["branch_canal_id"], 0
        )
        coverage_after = metrics_after["branch_coverages"].get(
            gc["branch_canal_id"], 0
        )

        db.execute(
            """
            INSERT INTO gate_changes
            (schedule_log_id, gate_id, branch_canal_id, branch_canal_name,
             gate_name, opening_before, opening_after, flow_before, flow_after,
             coverage_before, coverage_after)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                log_id,
                gc["gate_id"],
                gc["branch_canal_id"],
                gc["branch_canal_name"],
                gc["gate_name"],
                gc["opening_before"],
                gc["opening_after"],
                flow_before,
                flow_after,
                coverage_before,
                coverage_after,
            ),
        )

    db.commit()
    db.close()

    return RedirectResponse(
        url=f"/weirs/{weir_id}/schedule-logs/{log_id}", status_code=303
    )


@router.get("/weirs/{weir_id}/schedule-logs/{log_id}", response_class=HTMLResponse)
def schedule_log_detail(request: Request, weir_id: int, log_id: int):
    db = get_db()
    weir = db.execute("SELECT * FROM weirs WHERE id = ?", (weir_id,)).fetchone()
    if not weir:
        db.close()
        raise HTTPException(status_code=404, detail="堰坝不存在")

    log_raw = db.execute(
        """
        SELECT sl.*, s.name as scheme_name, s.status as scheme_status
        FROM schedule_logs sl
        LEFT JOIN schemes s ON sl.scheme_id = s.id
        WHERE sl.id = ? AND sl.weir_id = ?
        """,
        (log_id, weir_id),
    ).fetchone()
    if not log_raw:
        db.close()
        raise HTTPException(status_code=404, detail="调度日志不存在")
    log = dict(log_raw)

    gate_changes_raw = db.execute(
        "SELECT * FROM gate_changes WHERE schedule_log_id = ? ORDER BY id",
        (log_id,),
    ).fetchall()
    gate_changes = [dict(gc) for gc in gate_changes_raw]

    main_canals_raw = db.execute(
        "SELECT * FROM main_canals WHERE weir_id = ?", (weir_id,)
    ).fetchall()
    main_canals = [dict(mc) for mc in main_canals_raw]

    db.close()

    return getattr(request.app.state, "templates", None).TemplateResponse(
        request,
        "schedule_log_detail.html",
        {
            "weir": dict(weir),
            "log": log,
            "gate_changes": gate_changes,
            "main_canals": main_canals,
            "rule_labels": RULE_LABELS,
        },
    )


@router.post("/weirs/{weir_id}/schedule-logs/{log_id}/apply")
def apply_schedule_log(weir_id: int, log_id: int):
    db = get_db()
    log = db.execute(
        "SELECT * FROM schedule_logs WHERE id = ? AND weir_id = ?",
        (log_id, weir_id),
    ).fetchone()
    if not log:
        db.close()
        raise HTTPException(status_code=404, detail="调度日志不存在")

    gate_changes = db.execute(
        "SELECT * FROM gate_changes WHERE schedule_log_id = ?", (log_id,)
    ).fetchall()

    for gc in gate_changes:
        if gc["gate_id"]:
            db.execute(
                "UPDATE gates SET opening = ? WHERE id = ?",
                (gc["opening_after"], gc["gate_id"]),
            )

    db.execute(
        "UPDATE schedule_logs SET published = 1, published_at = CURRENT_TIMESTAMP WHERE id = ?",
        (log_id,),
    )

    db.commit()
    db.close()

    return RedirectResponse(
        url=f"/weirs/{weir_id}/schedule-logs/{log_id}", status_code=303
    )


@router.post("/weirs/{weir_id}/schedule-logs/{log_id}/delete")
def delete_schedule_log(weir_id: int, log_id: int):
    db = get_db()
    log = db.execute(
        "SELECT * FROM schedule_logs WHERE id = ? AND weir_id = ?",
        (log_id, weir_id),
    ).fetchone()
    if not log:
        db.close()
        raise HTTPException(status_code=404, detail="调度日志不存在")

    db.execute("DELETE FROM gate_changes WHERE schedule_log_id = ?", (log_id,))
    db.execute("DELETE FROM schedule_logs WHERE id = ?", (log_id,))

    db.commit()
    db.close()

    return RedirectResponse(
        url=f"/weirs/{weir_id}/schedule-logs", status_code=303
    )


@router.get("/api/weirs/{weir_id}/schedule-logs/timeline")
def get_timeline_data(
    weir_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    operator: Optional[str] = None,
):
    db = get_db()
    query = """
        SELECT sl.*, s.name as scheme_name
        FROM schedule_logs sl
        LEFT JOIN schemes s ON sl.scheme_id = s.id
        WHERE sl.weir_id = ?
    """
    params = [weir_id]

    if start_date:
        query += " AND date(sl.adjust_time) >= date(?)"
        params.append(start_date)
    if end_date:
        query += " AND date(sl.adjust_time) <= date(?)"
        params.append(end_date)
    if operator:
        query += " AND sl.operator = ?"
        params.append(operator)

    query += " ORDER BY sl.adjust_time ASC"

    logs = db.execute(query, params).fetchall()

    result = []
    for log in logs:
        gate_changes = db.execute(
            "SELECT * FROM gate_changes WHERE schedule_log_id = ?",
            (log["id"],),
        ).fetchall()

        result.append(
            {
                "id": log["id"],
                "adjust_time": log["adjust_time"],
                "operator": log["operator"],
                "adjust_reason": log["adjust_reason"],
                "water_level": log["water_level"],
                "water_level_date": log["water_level_date"],
                "rule_before": log["rule_before"],
                "rule_after": log["rule_after"],
                "total_flow_before": log["total_flow_before"],
                "total_flow_after": log["total_flow_after"],
                "avg_coverage_before": log["avg_coverage_before"],
                "avg_coverage_after": log["avg_coverage_after"],
                "published": bool(log["published"]),
                "published_at": log["published_at"],
                "scheme_name": log["scheme_name"],
                "notes": log["notes"],
                "gate_changes": [
                    {
                        "id": gc["id"],
                        "gate_id": gc["gate_id"],
                        "branch_canal_id": gc["branch_canal_id"],
                        "branch_canal_name": gc["branch_canal_name"],
                        "gate_name": gc["gate_name"],
                        "opening_before": gc["opening_before"],
                        "opening_after": gc["opening_after"],
                        "flow_before": gc["flow_before"],
                        "flow_after": gc["flow_after"],
                        "coverage_before": gc["coverage_before"],
                        "coverage_after": gc["coverage_after"],
                    }
                    for gc in gate_changes
                ],
            }
        )

    db.close()
    return {"events": result}


@router.get("/api/weirs/{weir_id}/schedule-logs/compare")
def get_compare_data(
    weir_id: int,
    log_ids: str = Query(..., description="逗号分隔的日志ID列表"),
):
    db = get_db()
    log_id_list = [int(x.strip()) for x in log_ids.split(",") if x.strip().isdigit()]

    result = []
    branch_names = {}
    all_branch_ids = set()

    for log_id in log_id_list:
        log = db.execute(
            "SELECT * FROM schedule_logs WHERE id = ? AND weir_id = ?",
            (log_id, weir_id),
        ).fetchone()
        if not log:
            continue

        gate_changes = db.execute(
            "SELECT * FROM gate_changes WHERE schedule_log_id = ?", (log_id,)
        ).fetchall()

        branch_data = {}
        for gc in gate_changes:
            all_branch_ids.add(gc["branch_canal_id"])
            branch_names[gc["branch_canal_id"]] = gc["branch_canal_name"]
            branch_data[gc["branch_canal_id"]] = {
                "flow_before": gc["flow_before"],
                "flow_after": gc["flow_after"],
                "flow_delta": round(gc["flow_after"] - gc["flow_before"], 4),
                "coverage_before": gc["coverage_before"],
                "coverage_after": gc["coverage_after"],
                "coverage_delta": round(
                    gc["coverage_after"] - gc["coverage_before"], 4
                ),
                "opening_before": gc["opening_before"],
                "opening_after": gc["opening_after"],
            }

        result.append(
            {
                "log_id": log["id"],
                "adjust_time": log["adjust_time"],
                "operator": log["operator"],
                "adjust_reason": log["adjust_reason"],
                "rule_before": log["rule_before"],
                "rule_after": log["rule_after"],
                "total_flow_before": log["total_flow_before"],
                "total_flow_after": log["total_flow_after"],
                "total_flow_delta": round(
                    log["total_flow_after"] - log["total_flow_before"], 4
                ),
                "avg_coverage_before": log["avg_coverage_before"],
                "avg_coverage_after": log["avg_coverage_after"],
                "avg_coverage_delta": round(
                    log["avg_coverage_after"] - log["avg_coverage_before"], 4
                ),
                "published": bool(log["published"]),
                "branches": branch_data,
            }
        )

    db.close()

    return {
        "comparisons": result,
        "branches": [
            {"id": bid, "name": branch_names.get(bid, f"支渠{bid}")}
            for bid in sorted(all_branch_ids)
        ],
        "rule_labels": RULE_LABELS,
    }


@router.get("/api/weirs/{weir_id}/schedule-logs/{log_id}")
def get_log_detail_api(weir_id: int, log_id: int):
    db = get_db()
    log = db.execute(
        """
        SELECT sl.*, s.name as scheme_name
        FROM schedule_logs sl
        LEFT JOIN schemes s ON sl.scheme_id = s.id
        WHERE sl.id = ? AND sl.weir_id = ?
        """,
        (log_id, weir_id),
    ).fetchone()
    if not log:
        db.close()
        raise HTTPException(status_code=404, detail="调度日志不存在")

    gate_changes = db.execute(
        "SELECT * FROM gate_changes WHERE schedule_log_id = ?", (log_id,)
    ).fetchall()

    db.close()

    return {
        "id": log["id"],
        "adjust_time": log["adjust_time"],
        "operator": log["operator"],
        "adjust_reason": log["adjust_reason"],
        "water_level": log["water_level"],
        "water_level_date": log["water_level_date"],
        "rule_before": log["rule_before"],
        "rule_after": log["rule_after"],
        "total_flow_before": log["total_flow_before"],
        "total_flow_after": log["total_flow_after"],
        "avg_coverage_before": log["avg_coverage_before"],
        "avg_coverage_after": log["avg_coverage_after"],
        "published": bool(log["published"]),
        "published_at": log["published_at"],
        "scheme_name": log["scheme_name"],
        "notes": log["notes"],
        "gate_changes": [
            {
                "id": gc["id"],
                "gate_id": gc["gate_id"],
                "branch_canal_id": gc["branch_canal_id"],
                "branch_canal_name": gc["branch_canal_name"],
                "gate_name": gc["gate_name"],
                "opening_before": gc["opening_before"],
                "opening_after": gc["opening_after"],
                "flow_before": gc["flow_before"],
                "flow_after": gc["flow_after"],
                "coverage_before": gc["coverage_before"],
                "coverage_after": gc["coverage_after"],
            }
            for gc in gate_changes
        ],
    }
