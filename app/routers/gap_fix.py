import json
from datetime import datetime
from fastapi import APIRouter, Request, Form, HTTPException, Body
from fastapi.responses import HTMLResponse, RedirectResponse
from app.database import get_db
from app.calc import (
    detect_gap_segments,
    generate_gap_fix_suggestions,
    compute_impact_analysis,
    scan_water_level_quality,
    compute_main_canal_flow,
    compute_distribution,
    compute_coverage,
    filter_continuous_dates,
)
from app.models import (
    GapFixRecordCreate,
    GapFixConfirm,
    GapFixBatchApply,
)

router = APIRouter()

METHOD_LABELS = {
    "linear_interpolate": "线性插值",
    "spline_interpolate": "样条插值",
    "rule_based": "规则补录",
    "previous_day": "前日延续",
    "next_day": "后日参考",
    "monthly_average": "月均补录",
    "weekly_average": "周均补录",
    "manual": "人工录入",
}

CONFIDENCE_LABELS = {
    "high": "高",
    "medium": "中",
    "low": "低",
}

CONFIDENCE_COLORS = {
    "high": "var(--success)",
    "medium": "var(--accent)",
    "low": "var(--danger)",
}

STATUS_LABELS = {
    "pending": "待确认",
    "confirmed": "已确认",
    "rejected": "已驳回",
    "applied": "已入库",
}

STATUS_COLORS = {
    "pending": "#f39c12",
    "confirmed": "var(--success)",
    "rejected": "var(--danger)",
    "applied": "var(--info)",
}


def _build_branch_canals(db, main_canal_id):
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
        avg_opening = sum(g["opening"] for g in gates) / len(gates) if gates else 100
        result.append({
            "id": bc["id"],
            "name": bc["name"],
            "width": bc["width"],
            "acreage": bc["acreage"],
            "farm_type": bc["farm_type"] or "general",
            "position": bc["position"],
            "gate_opening": avg_opening,
        })
    return result


@router.get("/weirs/{weir_id}/gap-fix", response_class=HTMLResponse)
def gap_fix_page(request: Request, weir_id: int):
    db = get_db()
    weir = db.execute("SELECT * FROM weirs WHERE id = ?", (weir_id,)).fetchone()
    if not weir:
        db.close()
        raise HTTPException(status_code=404, detail="堰坝不存在")
    water_levels = db.execute(
        "SELECT * FROM water_levels WHERE weir_id = ? ORDER BY date", (weir_id,)
    ).fetchall()
    main_canals = db.execute(
        "SELECT * FROM main_canals WHERE weir_id = ?", (weir_id,)
    ).fetchall()
    fix_records = db.execute(
        "SELECT * FROM gap_fix_records WHERE weir_id = ? ORDER BY date DESC",
        (weir_id,),
    ).fetchall()
    quality = scan_water_level_quality([dict(wl) for wl in water_levels])
    wl_dicts = [dict(wl) for wl in water_levels]
    dates = [wl["date"] for wl in wl_dicts]
    gaps = detect_gap_segments(dates)
    suggestions = generate_gap_fix_suggestions(wl_dicts, gaps)
    db.close()
    return getattr(request.app.state, "templates", None).TemplateResponse(
        request,
        "gap_fix.html",
        {
            "weir": weir,
            "water_levels": water_levels,
            "main_canals": main_canals,
            "fix_records": fix_records,
            "quality": quality,
            "gaps": gaps,
            "suggestions": suggestions,
            "method_labels": METHOD_LABELS,
            "confidence_labels": CONFIDENCE_LABELS,
            "confidence_colors": CONFIDENCE_COLORS,
            "status_labels": STATUS_LABELS,
            "status_colors": STATUS_COLORS,
        },
    )


@router.get("/weirs/{weir_id}/gap-fix/scan")
def scan_gaps(weir_id: int):
    db = get_db()
    weir = db.execute("SELECT * FROM weirs WHERE id = ?", (weir_id,)).fetchone()
    if not weir:
        db.close()
        raise HTTPException(status_code=404, detail="堰坝不存在")
    water_levels = db.execute(
        "SELECT * FROM water_levels WHERE weir_id = ? ORDER BY date", (weir_id,)
    ).fetchall()
    wl_dicts = [dict(wl) for wl in water_levels]
    quality = scan_water_level_quality(wl_dicts)
    dates = [wl["date"] for wl in wl_dicts]
    gaps = detect_gap_segments(dates)
    suggestions = generate_gap_fix_suggestions(wl_dicts, gaps)
    db.execute(
        """INSERT INTO gap_scan_summaries
           (weir_id, total_records, missing_count, gap_segments, longest_gap_days, simulated_count)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            weir_id,
            quality["total_records"],
            quality["missing_count"],
            len(gaps),
            quality["longest_gap_days"],
            quality["simulated_count"],
        ),
    )
    db.commit()
    db.close()
    return {
        "quality": quality,
        "gaps": gaps,
        "suggestions": suggestions,
    }


@router.get("/weirs/{weir_id}/gap-fix/suggestions")
def get_suggestions(weir_id: int):
    db = get_db()
    weir = db.execute("SELECT * FROM weirs WHERE id = ?", (weir_id,)).fetchone()
    if not weir:
        db.close()
        raise HTTPException(status_code=404, detail="堰坝不存在")
    water_levels = db.execute(
        "SELECT * FROM water_levels WHERE weir_id = ? ORDER BY date", (weir_id,)
    ).fetchall()
    wl_dicts = [dict(wl) for wl in water_levels]
    dates = [wl["date"] for wl in wl_dicts]
    gaps = detect_gap_segments(dates)
    suggestions = generate_gap_fix_suggestions(wl_dicts, gaps)
    db.close()
    return {"suggestions": suggestions}


@router.post("/gap-fix/apply")
def apply_fix_record(
    weir_id: int = Form(...),
    date: str = Form(...),
    fixed_level: float = Form(...),
    method: str = Form("linear_interpolate"),
    confidence_level: str = Form("medium"),
    basis: str = Form(""),
    operator: str = Form("系统管理员"),
    notes: str = Form(""),
    main_canal_id: int = Form(0),
):
    if fixed_level < 0:
        raise HTTPException(status_code=400, detail="水位不能为负数")
    db = get_db()
    weir = db.execute("SELECT * FROM weirs WHERE id = ?", (weir_id,)).fetchone()
    if not weir:
        db.close()
        raise HTTPException(status_code=404, detail="堰坝不存在")
    existing_wl = db.execute(
        "SELECT * FROM water_levels WHERE weir_id = ? AND date = ?", (weir_id, date)
    ).fetchone()
    original_level = existing_wl["level"] if existing_wl else None
    impact_flow_before = 0.0
    impact_flow_after = 0.0
    impact_cov_before = 0.0
    impact_cov_after = 0.0
    impact_pub_before = 0
    impact_pub_after = 0
    if main_canal_id and main_canal_id > 0:
        mc = db.execute(
            "SELECT * FROM main_canals WHERE id = ?", (main_canal_id,)
        ).fetchone()
        if mc:
            branch_canals = _build_branch_canals(db, main_canal_id)
            default_rule = "equal"
            active_scheme = db.execute(
                "SELECT * FROM schemes WHERE weir_id = ? AND status = 'published' ORDER BY id DESC LIMIT 1",
                (weir_id,),
            ).fetchone()
            if active_scheme:
                default_rule = active_scheme["rule"]
            impact = compute_impact_analysis(
                weir_id, date, original_level, fixed_level,
                mc["width"], branch_canals, default_rule,
            )
            impact_flow_before = impact["flow_before"]
            impact_flow_after = impact["flow_after"]
            impact_cov_before = impact["coverage_before"]
            impact_cov_after = impact["coverage_after"]
            impact_pub_before = 1 if impact["publishable_before"] else 0
            impact_pub_after = 1 if impact["publishable_after"] else 0
    existing_fix = db.execute(
        "SELECT id FROM gap_fix_records WHERE weir_id = ? AND date = ?",
        (weir_id, date),
    ).fetchone()
    if existing_fix:
        db.execute(
            """UPDATE gap_fix_records SET
               fixed_level=?, method=?, confidence_level=?, basis=?,
               operator=?, notes=?, status='pending',
               impact_total_flow_before=?, impact_total_flow_after=?,
               impact_avg_coverage_before=?, impact_avg_coverage_after=?,
               impact_scheme_publishable_before=?, impact_scheme_publishable_after=?
               WHERE id=?""",
            (
                fixed_level, method, confidence_level, basis,
                operator, notes,
                impact_flow_before, impact_flow_after,
                impact_cov_before, impact_cov_after,
                impact_pub_before, impact_pub_after,
                existing_fix["id"],
            ),
        )
    else:
        db.execute(
            """INSERT INTO gap_fix_records
               (weir_id, date, original_level, fixed_level, method, confidence_level,
                basis, status, operator, notes,
                impact_total_flow_before, impact_total_flow_after,
                impact_avg_coverage_before, impact_avg_coverage_after,
                impact_scheme_publishable_before, impact_scheme_publishable_after)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                weir_id, date, original_level, fixed_level, method, confidence_level,
                basis, operator, notes,
                impact_flow_before, impact_flow_after,
                impact_cov_before, impact_cov_after,
                impact_pub_before, impact_pub_after,
            ),
        )
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/gap-fix", status_code=303)


@router.post("/gap-fix/{record_id}/confirm")
def confirm_fix_record(record_id: int, confirmed_by: str = Form("审核员"), notes: str = Form("")):
    db = get_db()
    record = db.execute(
        "SELECT * FROM gap_fix_records WHERE id = ?", (record_id,)
    ).fetchone()
    if not record:
        db.close()
        raise HTTPException(status_code=404, detail="修复记录不存在")
    weir_id = record["weir_id"]
    db.execute(
        "UPDATE gap_fix_records SET status='confirmed', confirmed_by=?, confirmed_at=CURRENT_TIMESTAMP, notes=? WHERE id=?",
        (confirmed_by, notes, record_id),
    )
    existing = db.execute(
        "SELECT id FROM water_levels WHERE weir_id = ? AND date = ?",
        (weir_id, record["date"]),
    ).fetchone()
    if existing:
        db.execute(
            "UPDATE water_levels SET level=?, is_simulated=1 WHERE id=?",
            (record["fixed_level"], existing["id"]),
        )
    else:
        db.execute(
            "INSERT INTO water_levels (weir_id, date, level, is_simulated) VALUES (?, ?, ?, 1)",
            (weir_id, record["date"], record["fixed_level"]),
        )
    db.execute(
        "UPDATE gap_fix_records SET status='applied' WHERE id=?",
        (record_id,),
    )
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/gap-fix", status_code=303)


@router.post("/gap-fix/{record_id}/reject")
def reject_fix_record(record_id: int, confirmed_by: str = Form("审核员"), notes: str = Form("")):
    db = get_db()
    record = db.execute(
        "SELECT * FROM gap_fix_records WHERE id = ?", (record_id,)
    ).fetchone()
    if not record:
        db.close()
        raise HTTPException(status_code=404, detail="修复记录不存在")
    weir_id = record["weir_id"]
    db.execute(
        "UPDATE gap_fix_records SET status='rejected', confirmed_by=?, confirmed_at=CURRENT_TIMESTAMP, notes=? WHERE id=?",
        (confirmed_by, notes, record_id),
    )
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/gap-fix", status_code=303)


@router.post("/gap-fix/{record_id}/delete")
def delete_fix_record(record_id: int):
    db = get_db()
    record = db.execute(
        "SELECT * FROM gap_fix_records WHERE id = ?", (record_id,)
    ).fetchone()
    if not record:
        db.close()
        raise HTTPException(status_code=404, detail="修复记录不存在")
    weir_id = record["weir_id"]
    db.execute("DELETE FROM gap_fix_records WHERE id = ?", (record_id,))
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/gap-fix", status_code=303)


@router.post("/gap-fix/batch-apply")
def batch_apply_fixes(
    weir_id: int = Form(...),
    operator: str = Form("系统管理员"),
    main_canal_id: int = Form(0),
):
    db = get_db()
    weir = db.execute("SELECT * FROM weirs WHERE id = ?", (weir_id,)).fetchone()
    if not weir:
        db.close()
        raise HTTPException(status_code=404, detail="堰坝不存在")
    water_levels = db.execute(
        "SELECT * FROM water_levels WHERE weir_id = ? ORDER BY date", (weir_id,)
    ).fetchall()
    wl_dicts = [dict(wl) for wl in water_levels]
    dates = [wl["date"] for wl in wl_dicts]
    gaps = detect_gap_segments(dates)
    suggestions = generate_gap_fix_suggestions(wl_dicts, gaps)
    mc_width = 0.0
    branch_canals = []
    default_rule = "equal"
    if main_canal_id and main_canal_id > 0:
        mc = db.execute(
            "SELECT * FROM main_canals WHERE id = ?", (main_canal_id,)
        ).fetchone()
        if mc:
            mc_width = mc["width"]
            branch_canals = _build_branch_canals(db, main_canal_id)
            active_scheme = db.execute(
                "SELECT * FROM schemes WHERE weir_id = ? AND status = 'published' ORDER BY id DESC LIMIT 1",
                (weir_id,),
            ).fetchone()
            if active_scheme:
                default_rule = active_scheme["rule"]
    applied_count = 0
    for sug in suggestions:
        fixed_level = sug["recommended_level"]
        method = sug["recommended_method"]
        confidence = sug["recommended_confidence"]
        basis = sug["recommended_basis"]
        date = sug["date"]
        existing_wl = db.execute(
            "SELECT * FROM water_levels WHERE weir_id = ? AND date = ?",
            (weir_id, date),
        ).fetchone()
        original_level = existing_wl["level"] if existing_wl else None
        impact_flow_before = 0.0
        impact_flow_after = 0.0
        impact_cov_before = 0.0
        impact_cov_after = 0.0
        impact_pub_before = 0
        impact_pub_after = 0
        if mc_width > 0 and branch_canals:
            impact = compute_impact_analysis(
                weir_id, date, original_level, fixed_level,
                mc_width, branch_canals, default_rule,
            )
            impact_flow_before = impact["flow_before"]
            impact_flow_after = impact["flow_after"]
            impact_cov_before = impact["coverage_before"]
            impact_cov_after = impact["coverage_after"]
            impact_pub_before = 1 if impact["publishable_before"] else 0
            impact_pub_after = 1 if impact["publishable_after"] else 0
        existing_fix = db.execute(
            "SELECT id FROM gap_fix_records WHERE weir_id = ? AND date = ?",
            (weir_id, date),
        ).fetchone()
        if existing_fix:
            db.execute(
                """UPDATE gap_fix_records SET
                   fixed_level=?, method=?, confidence_level=?, basis=?,
                   operator=?, status='pending',
                   impact_total_flow_before=?, impact_total_flow_after=?,
                   impact_avg_coverage_before=?, impact_avg_coverage_after=?,
                   impact_scheme_publishable_before=?, impact_scheme_publishable_after=?
                   WHERE id=?""",
                (
                    fixed_level, method, confidence, basis, operator,
                    impact_flow_before, impact_flow_after,
                    impact_cov_before, impact_cov_after,
                    impact_pub_before, impact_pub_after,
                    existing_fix["id"],
                ),
            )
        else:
            db.execute(
                """INSERT INTO gap_fix_records
                   (weir_id, date, original_level, fixed_level, method, confidence_level,
                    basis, status, operator,
                    impact_total_flow_before, impact_total_flow_after,
                    impact_avg_coverage_before, impact_avg_coverage_after,
                    impact_scheme_publishable_before, impact_scheme_publishable_after)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    weir_id, date, original_level, fixed_level, method, confidence,
                    basis, operator,
                    impact_flow_before, impact_flow_after,
                    impact_cov_before, impact_cov_after,
                    impact_pub_before, impact_pub_after,
                ),
            )
        applied_count += 1
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/gap-fix", status_code=303)


@router.get("/gap-fix/{record_id}/impact")
def get_fix_impact(record_id: int, main_canal_id: int = 0):
    db = get_db()
    record = db.execute(
        "SELECT * FROM gap_fix_records WHERE id = ?", (record_id,)
    ).fetchone()
    if not record:
        db.close()
        raise HTTPException(status_code=404, detail="修复记录不存在")
    if not main_canal_id:
        schemes = db.execute(
            "SELECT main_canal_id FROM schemes WHERE weir_id = ? AND main_canal_id IS NOT NULL LIMIT 1",
            (record["weir_id"],),
        ).fetchone()
        if schemes:
            main_canal_id = schemes["main_canal_id"]
    if not main_canal_id:
        db.close()
        return {
            "has_impact": False,
            "message": "请先选择主渠以查看影响分析",
        }
    mc = db.execute(
        "SELECT * FROM main_canals WHERE id = ?", (main_canal_id,)
    ).fetchone()
    if not mc:
        db.close()
        raise HTTPException(status_code=404, detail="主渠不存在")
    branch_canals = _build_branch_canals(db, main_canal_id)
    default_rule = "equal"
    active_scheme = db.execute(
        "SELECT * FROM schemes WHERE weir_id = ? AND status = 'published' ORDER BY id DESC LIMIT 1",
        (record["weir_id"],),
    ).fetchone()
    if active_scheme:
        default_rule = active_scheme["rule"]
    impact = compute_impact_analysis(
        record["weir_id"], record["date"],
        record["original_level"], record["fixed_level"],
        mc["width"], branch_canals, default_rule,
    )
    db.close()
    return {"has_impact": True, "impact": impact}


@router.get("/weirs/{weir_id}/gap-fix/records")
def list_fix_records(weir_id: int, status: str = ""):
    db = get_db()
    if status:
        records = db.execute(
            "SELECT * FROM gap_fix_records WHERE weir_id = ? AND status = ? ORDER BY date DESC",
            (weir_id, status),
        ).fetchall()
    else:
        records = db.execute(
            "SELECT * FROM gap_fix_records WHERE weir_id = ? ORDER BY date DESC",
            (weir_id,),
        ).fetchall()
    result = [dict(r) for r in records]
    db.close()
    return {"records": result}
