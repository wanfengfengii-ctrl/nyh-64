import json
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from app.database import get_db
from app.calc import (
    compute_main_canal_flow,
    compute_time_series,
    check_over_allocation,
    compute_distribution,
    filter_continuous_dates,
    compute_coverage,
    run_consistency_checks,
)
from app.models import FARM_TYPE_LABELS

router = APIRouter()

RULE_LABELS = {
    "equal": "均分",
    "downstream_first": "优先下游",
    "acreage_ratio": "按田亩比例",
}

def _build_branch_canals(db, main_canal_id):
    bcs = db.execute("SELECT * FROM branch_canals WHERE main_canal_id = ? ORDER BY position, id", (main_canal_id,)).fetchall()
    result = []
    for bc in bcs:
        gates = db.execute("SELECT * FROM gates WHERE branch_canal_id = ? ORDER BY id", (bc["id"],)).fetchall()
        if gates:
            avg_opening = sum(g["opening"] for g in gates) / len(gates)
            gate_names = "、".join(g["name"] for g in gates)
        else:
            avg_opening = 100
            gate_names = ""
        result.append({
            "id": bc["id"],
            "name": bc["name"],
            "width": bc["width"],
            "acreage": bc["acreage"],
            "farm_type": bc["farm_type"] or "general",
            "position": bc["position"],
            "gate_opening": avg_opening,
            "gate_name": gate_names,
        })
    return result

@router.get("/weirs/{weir_id}/schemes", response_class=HTMLResponse)
def schemes_page(request: Request, weir_id: int):
    db = get_db()
    weir = db.execute("SELECT * FROM weirs WHERE id = ?", (weir_id,)).fetchone()
    if not weir:
        db.close()
        raise HTTPException(status_code=404, detail="堰坝不存在")
    schemes = db.execute("SELECT * FROM schemes WHERE weir_id = ? ORDER BY id DESC", (weir_id,)).fetchall()
    main_canals = db.execute("SELECT * FROM main_canals WHERE weir_id = ?", (weir_id,)).fetchall()
    branch_canals_map = {}
    for mc in main_canals:
        branch_canals_map[mc["id"]] = _build_branch_canals(db, mc["id"])
    water_levels = db.execute("SELECT * FROM water_levels WHERE weir_id = ? ORDER BY date", (weir_id,)).fetchall()
    scheme_versions = {}
    for s in schemes:
        if s["parent_id"]:
            parent = db.execute("SELECT id, name, version FROM schemes WHERE id = ?", (s["parent_id"],)).fetchone()
            scheme_versions[s["id"]] = parent
    db.close()
    return getattr(request.app.state, "templates", None).TemplateResponse(
        request, "schemes.html",
        {
            "weir": weir,
            "schemes": schemes,
            "main_canals": main_canals,
            "branch_canals_map": branch_canals_map,
            "water_levels": water_levels,
            "rule_labels": RULE_LABELS,
            "farm_type_labels": FARM_TYPE_LABELS,
            "scheme_versions": scheme_versions,
        },
    )

@router.post("/weirs/{weir_id}/schemes")
def create_scheme(weir_id: int, name: str = Form(...), rule: str = Form("equal"), change_note: str = Form("")):
    if rule not in ("equal", "downstream_first", "acreage_ratio"):
        raise HTTPException(status_code=400, detail="无效的分水规则")
    db = get_db()
    db.execute(
        "INSERT INTO schemes (weir_id, name, rule, status, version, change_note) VALUES (?, ?, ?, 'draft', 1, ?)",
        (weir_id, name, rule, change_note),
    )
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/schemes", status_code=303)

@router.post("/schemes/{scheme_id}/new-version")
def create_new_version(scheme_id: int, name: str = Form(...), rule: str = Form("equal"), change_note: str = Form("")):
    if rule not in ("equal", "downstream_first", "acreage_ratio"):
        raise HTTPException(status_code=400, detail="无效的分水规则")
    db = get_db()
    parent = db.execute("SELECT * FROM schemes WHERE id = ?", (scheme_id,)).fetchone()
    if not parent:
        db.close()
        raise HTTPException(status_code=404, detail="父方案不存在")
    weir_id = parent["weir_id"]
    new_version = (parent["version"] or 1) + 1
    cur = db.execute(
        """INSERT INTO schemes
           (weir_id, name, rule, status, version, parent_id, change_note, main_canal_id)
           VALUES (?, ?, ?, 'draft', ?, ?, ?, ?)""",
        (weir_id, name, rule, new_version, scheme_id, change_note, parent["main_canal_id"]),
    )
    new_scheme_id = cur.lastrowid
    if parent["main_canal_id"]:
        old_results = db.execute(
            "SELECT * FROM scheme_results WHERE scheme_id = ?", (scheme_id,)
        ).fetchall()
        for r in old_results:
            db.execute(
                """INSERT INTO scheme_results (scheme_id, date, branch_canal_id, flow, coverage)
                   VALUES (?, ?, ?, ?, ?)""",
                (new_scheme_id, r["date"], r["branch_canal_id"], r["flow"], r["coverage"] or 0),
            )
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/schemes", status_code=303)

@router.post("/schemes/{scheme_id}/update-rule")
def update_scheme_rule(scheme_id: int, rule: str = Form(...)):
    if rule not in ("equal", "downstream_first", "acreage_ratio"):
        raise HTTPException(status_code=400, detail="无效的分水规则")
    db = get_db()
    scheme = db.execute("SELECT * FROM schemes WHERE id = ?", (scheme_id,)).fetchone()
    if not scheme:
        db.close()
        raise HTTPException(status_code=404, detail="方案不存在")
    weir_id = scheme["weir_id"]
    main_canal_id = scheme["main_canal_id"]
    db.execute("DELETE FROM scheme_results WHERE scheme_id = ?", (scheme_id,))
    db.execute("UPDATE schemes SET rule = ?, status = 'draft' WHERE id = ?", (rule, scheme_id,))
    if main_canal_id:
        mc = db.execute("SELECT * FROM main_canals WHERE id = ?", (main_canal_id,)).fetchone()
        if mc:
            branch_canals = _build_branch_canals(db, main_canal_id)
            water_levels = db.execute("SELECT * FROM water_levels WHERE weir_id = ? ORDER BY date", (weir_id,)).fetchall()
            if branch_canals and water_levels:
                all_dates = [wl["date"] for wl in water_levels]
                continuous_dates = filter_continuous_dates(all_dates)
                filtered_levels = [wl for wl in water_levels if wl["date"] in continuous_dates]
                if filtered_levels:
                    ts = compute_time_series(
                        [{"date": wl["date"], "level": wl["level"]} for wl in filtered_levels],
                        mc["width"],
                        branch_canals,
                        rule,
                    )
                    over_alloc = False
                    for record in ts:
                        if record["over_allocated"]:
                            over_alloc = True
                            break
                    if not over_alloc:
                        for record in ts:
                            for br in record["branches"]:
                                db.execute(
                                    """INSERT INTO scheme_results
                                       (scheme_id, date, branch_canal_id, flow, coverage)
                                       VALUES (?, ?, ?, ?, ?)""",
                                    (
                                        scheme_id, record["date"],
                                        br["branch_canal_id"], br["flow"],
                                        br.get("coverage", 0),
                                    ),
                                )
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/schemes", status_code=303)

@router.post("/schemes/{scheme_id}/delete")
def delete_scheme(scheme_id: int):
    db = get_db()
    scheme = db.execute("SELECT * FROM schemes WHERE id = ?", (scheme_id,)).fetchone()
    if not scheme:
        db.close()
        raise HTTPException(status_code=404, detail="方案不存在")
    weir_id = scheme["weir_id"]
    db.execute("DELETE FROM scheme_results WHERE scheme_id = ?", (scheme_id,))
    db.execute("UPDATE schemes SET parent_id = NULL WHERE parent_id = ?", (scheme_id,))
    db.execute("DELETE FROM schemes WHERE id = ?", (scheme_id,))
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/schemes", status_code=303)

@router.post("/schemes/{scheme_id}/compute")
def compute_scheme(scheme_id: int, main_canal_id: int = Form(...)):
    db = get_db()
    scheme = db.execute("SELECT * FROM schemes WHERE id = ?", (scheme_id,)).fetchone()
    if not scheme:
        db.close()
        raise HTTPException(status_code=404, detail="方案不存在")
    weir_id = scheme["weir_id"]
    mc = db.execute("SELECT * FROM main_canals WHERE id = ?", (main_canal_id,)).fetchone()
    if not mc:
        db.close()
        raise HTTPException(status_code=404, detail="主渠不存在")
    branch_canals = _build_branch_canals(db, main_canal_id)
    if not branch_canals:
        db.close()
        raise HTTPException(status_code=400, detail="该主渠下没有支渠，无法计算")
    water_levels = db.execute("SELECT * FROM water_levels WHERE weir_id = ? ORDER BY date", (weir_id,)).fetchall()
    if not water_levels:
        db.close()
        raise HTTPException(status_code=400, detail="没有水位数据，无法计算")
    all_dates = [wl["date"] for wl in water_levels]
    continuous_dates = filter_continuous_dates(all_dates)
    filtered_levels = [wl for wl in water_levels if wl["date"] in continuous_dates]
    if not filtered_levels:
        db.close()
        raise HTTPException(status_code=400, detail="没有连续的水位数据，无法计算")
    ts = compute_time_series(
        [{"date": wl["date"], "level": wl["level"]} for wl in filtered_levels],
        mc["width"],
        branch_canals,
        scheme["rule"],
    )
    db.execute("DELETE FROM scheme_results WHERE scheme_id = ?", (scheme_id,))
    for record in ts:
        if record["over_allocated"]:
            db.close()
            raise HTTPException(
                status_code=400,
                detail=f"日期 {record['date']} 存在超配水量，无法保存计算结果，请调整闸口开度或渠宽后重试"
            )
        for br in record["branches"]:
            db.execute(
                """INSERT INTO scheme_results
                   (scheme_id, date, branch_canal_id, flow, coverage)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    scheme_id, record["date"],
                    br["branch_canal_id"], br["flow"],
                    br.get("coverage", 0),
                ),
            )
    db.execute("UPDATE schemes SET status = 'draft', main_canal_id = ? WHERE id = ?", (main_canal_id, scheme_id,))
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/schemes", status_code=303)

@router.post("/schemes/{scheme_id}/publish")
def publish_scheme(scheme_id: int):
    db = get_db()
    scheme = db.execute("SELECT * FROM schemes WHERE id = ?", (scheme_id,)).fetchone()
    if not scheme:
        db.close()
        raise HTTPException(status_code=404, detail="方案不存在")
    weir_id = scheme["weir_id"]
    if not scheme["main_canal_id"]:
        db.close()
        raise HTTPException(status_code=400, detail="方案尚未计算，无法发布")
    results = db.execute("SELECT * FROM scheme_results WHERE scheme_id = ?", (scheme_id,)).fetchall()
    if not results:
        db.close()
        raise HTTPException(status_code=400, detail="方案尚未计算，无法发布")
    mc = db.execute("SELECT * FROM main_canals WHERE id = ?", (scheme["main_canal_id"],)).fetchone()
    if not mc:
        db.close()
        raise HTTPException(status_code=400, detail="主渠不存在，请重新计算方案")
    branch_canals = _build_branch_canals(db, scheme["main_canal_id"])
    water_levels = db.execute("SELECT * FROM water_levels WHERE weir_id = ? ORDER BY date", (weir_id,)).fetchall()

    ts_results = []
    dates = sorted(list({r["date"] for r in results}))
    for d in dates:
        day_results = [r for r in results if r["date"] == d]
        branches = []
        for r in day_results:
            bc = next((b for b in branch_canals if b["id"] == r["branch_canal_id"]), None)
            branches.append({
                "branch_canal_id": r["branch_canal_id"],
                "name": bc["name"] if bc else f"支渠{r['branch_canal_id']}",
                "flow": r["flow"],
                "coverage": r["coverage"] or 0,
            })
        wl = next((w for w in water_levels if w["date"] == d), None)
        total_flow = compute_main_canal_flow(wl["level"], mc["width"]) if wl else 0
        ts_results.append({
            "date": d,
            "branches": branches,
            "over_allocated": check_over_allocation(total_flow, branches),
        })
    wl_dicts = [{"date": wl["date"], "level": wl["level"]} for wl in water_levels]
    checks = run_consistency_checks(
        scheme_id, weir_id, scheme["main_canal_id"],
        ts_results, wl_dicts, branch_canals,
    )
    all_passed = all(c["passed"] for c in checks)
    if not all_passed:
        failed = [c["detail"] for c in checks if not c["passed"]]
        db.close()
        raise HTTPException(
            status_code=400,
            detail="发布前一致性校验未通过：" + "；".join(failed),
        )
    db.execute("DELETE FROM consistency_checks WHERE target_type = 'scheme' AND target_id = ?", (scheme_id,))
    for c in checks:
        db.execute(
            """INSERT INTO consistency_checks
               (target_type, target_id, check_type, passed, detail)
               VALUES ('scheme', ?, ?, ?, ?)""",
            (scheme_id, c["check_type"], 1 if c["passed"] else 0, c["detail"]),
        )
    db.execute("UPDATE schemes SET status = 'published' WHERE id = ?", (scheme_id,))
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/schemes", status_code=303)

@router.get("/schemes/{scheme_id}/chart-data")
def scheme_chart_data(scheme_id: int):
    db = get_db()
    scheme = db.execute("SELECT * FROM schemes WHERE id = ?", (scheme_id,)).fetchone()
    if not scheme:
        db.close()
        return {"dates": [], "branches": [], "flows": {}, "coverages": {}}
    weir_id = scheme["weir_id"]
    results = db.execute("SELECT * FROM scheme_results WHERE scheme_id = ?", (scheme_id,)).fetchall()
    if not results:
        db.close()
        return {"dates": [], "branches": [], "flows": {}, "coverages": {}}
    dates = sorted(list(set(r["date"] for r in results)))
    branch_ids = sorted(list(set(r["branch_canal_id"] for r in results)))
    branch_names = {}
    for bid in branch_ids:
        bc = db.execute("SELECT * FROM branch_canals WHERE id = ?", (bid,)).fetchone()
        branch_names[bid] = bc["name"] if bc else f"支渠{bid}"
    flows = {}
    coverages = {}
    for bid in branch_ids:
        flows[bid] = []
        coverages[bid] = []
        for d in dates:
            r = next((r for r in results if r["date"] == d and r["branch_canal_id"] == bid), None)
            flows[bid].append(round(r["flow"], 4) if r else 0.0)
            coverages[bid].append(round(r["coverage"], 4) if r and r["coverage"] else 0.0)
    db.close()
    return {
        "dates": dates,
        "branches": [{"id": bid, "name": branch_names[bid]} for bid in branch_ids],
        "flows": flows,
        "coverages": coverages,
    }

@router.get("/weirs/{weir_id}/compare-chart-data")
def compare_chart_data(weir_id: int, main_canal_id: int):
    db = get_db()
    weir = db.execute("SELECT * FROM weirs WHERE id = ?", (weir_id,)).fetchone()
    if not weir:
        db.close()
        raise HTTPException(status_code=404, detail="堰坝不存在")
    mc = db.execute("SELECT * FROM main_canals WHERE id = ?", (main_canal_id,)).fetchone()
    if not mc:
        db.close()
        raise HTTPException(status_code=404, detail="主渠不存在")
    branch_canals = _build_branch_canals(db, main_canal_id)
    if not branch_canals:
        db.close()
        return {"rules": []}
    water_levels = db.execute("SELECT * FROM water_levels WHERE weir_id = ? ORDER BY date", (weir_id,)).fetchall()
    if not water_levels:
        db.close()
        return {"rules": []}
    all_dates = [wl["date"] for wl in water_levels]
    continuous_dates = filter_continuous_dates(all_dates)
    filtered_levels = [wl for wl in water_levels if wl["date"] in continuous_dates]
    wl_data = [{"date": wl["date"], "level": wl["level"]} for wl in filtered_levels]
    rules_data = []
    for rule_key, rule_label in RULE_LABELS.items():
        ts = compute_time_series(wl_data, mc["width"], branch_canals, rule_key)
        rule_result = {
            "rule": rule_key, "label": rule_label,
            "dates": [], "branches": {},
            "total_flow": 0.0, "avg_coverage": 0.0,
        }
        for bc in branch_canals:
            rule_result["branches"][bc["id"]] = {
                "name": bc["name"], "flows": [], "coverages": [],
            }
        cov_sum = 0.0
        cov_count = 0
        for record in ts:
            rule_result["dates"].append(record["date"])
            rule_result["total_flow"] += record["total_flow"]
            for br in record["branches"]:
                if br["branch_canal_id"] in rule_result["branches"]:
                    rule_result["branches"][br["branch_canal_id"]]["flows"].append(round(br["flow"], 4))
                    cov = br.get("coverage", 0)
                    rule_result["branches"][br["branch_canal_id"]]["coverages"].append(round(cov, 4))
                    cov_sum += cov
                    cov_count += 1
        rule_result["total_flow"] = round(rule_result["total_flow"], 4)
        rule_result["avg_coverage"] = round(cov_sum / cov_count, 4) if cov_count > 0 else 0.0
        rules_data.append(rule_result)
    db.close()
    return {
        "rules": rules_data,
        "branch_canals": [
            {"id": bc["id"], "name": bc["name"],
             "farm_type": bc["farm_type"], "acreage": bc["acreage"]}
            for bc in branch_canals
        ],
    }

@router.get("/schemes/{scheme_id}/consistency-check")
def consistency_check(scheme_id: int):
    db = get_db()
    scheme = db.execute("SELECT * FROM schemes WHERE id = ?", (scheme_id,)).fetchone()
    if not scheme:
        db.close()
        return {"all_passed": False, "summary": "方案不存在", "checks": []}
    weir_id = scheme["weir_id"]
    results = db.execute("SELECT * FROM scheme_results WHERE scheme_id = ?", (scheme_id,)).fetchall()
    if not results or not scheme["main_canal_id"]:
        db.close()
        return {"all_passed": False, "summary": "方案尚未计算", "checks": [
            {"check_type": "方案完整性", "passed": False, "detail": "请先选择主渠并计算方案"}
        ]}
    mc = db.execute("SELECT * FROM main_canals WHERE id = ?", (scheme["main_canal_id"],)).fetchone()
    branch_canals = _build_branch_canals(db, scheme["main_canal_id"])
    water_levels = db.execute("SELECT * FROM water_levels WHERE weir_id = ? ORDER BY date", (weir_id,)).fetchall()

    ts_results = []
    dates = sorted(list({r["date"] for r in results}))
    for d in dates:
        day_results = [r for r in results if r["date"] == d]
        branches = []
        for r in day_results:
            bc = next((b for b in branch_canals if b["id"] == r["branch_canal_id"]), None)
            branches.append({
                "branch_canal_id": r["branch_canal_id"],
                "name": bc["name"] if bc else f"支渠{r['branch_canal_id']}",
                "flow": r["flow"],
                "coverage": r["coverage"] or 0,
            })
        wl = next((w for w in water_levels if w["date"] == d), None)
        total_flow = compute_main_canal_flow(wl["level"], mc["width"]) if wl else 0
        ts_results.append({
            "date": d, "branches": branches,
            "over_allocated": check_over_allocation(total_flow, branches),
        })
    wl_dicts = [{"date": wl["date"], "level": wl["level"]} for wl in water_levels]
    checks = run_consistency_checks(
        scheme_id, weir_id, scheme["main_canal_id"],
        ts_results, wl_dicts, branch_canals,
    )
    all_passed = all(c["passed"] for c in checks)
    failed = [c for c in checks if not c["passed"]]
    summary = f"共{len(checks)}项检查，通过{len(checks)-len(failed)}项，失败{len(failed)}项" if failed else "全部通过"
    db.close()
    return {"all_passed": all_passed, "summary": summary, "checks": checks}
