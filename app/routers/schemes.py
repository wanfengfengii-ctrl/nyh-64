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
)

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
        },
    )

@router.post("/weirs/{weir_id}/schemes")
def create_scheme(weir_id: int, name: str = Form(...), rule: str = Form("equal")):
    if rule not in ("equal", "downstream_first", "acreage_ratio"):
        raise HTTPException(status_code=400, detail="无效的分水规则")
    db = get_db()
    db.execute("INSERT INTO schemes (weir_id, name, rule, status) VALUES (?, ?, ?, 'draft')", (weir_id, name, rule))
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
                                    "INSERT INTO scheme_results (scheme_id, date, branch_canal_id, flow) VALUES (?, ?, ?, ?)",
                                    (scheme_id, record["date"], br["branch_canal_id"], br["flow"]),
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
                "INSERT INTO scheme_results (scheme_id, date, branch_canal_id, flow) VALUES (?, ?, ?, ?)",
                (scheme_id, record["date"], br["branch_canal_id"], br["flow"]),
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
    dates = list(set(r["date"] for r in results))
    for d in dates:
        date_results = [r for r in results if r["date"] == d]
        wl = db.execute("SELECT * FROM water_levels WHERE weir_id = ? AND date = ?", (weir_id, d)).fetchone()
        if not wl:
            continue
        total_flow = compute_main_canal_flow(wl["level"], mc["width"])
        total_allocated = sum(r["flow"] for r in date_results)
        if total_allocated > total_flow:
            db.close()
            raise HTTPException(status_code=400, detail=f"日期 {d} 存在超配水量（分配{total_allocated:.2f} > 来水{total_flow:.2f}），不能发布方案")
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
        raise HTTPException(status_code=404, detail="方案不存在")
    weir_id = scheme["weir_id"]
    results = db.execute("SELECT * FROM scheme_results WHERE scheme_id = ?", (scheme_id,)).fetchall()
    if not results:
        db.close()
        return {"dates": [], "branches": [], "flows": {}}
    dates = sorted(list(set(r["date"] for r in results)))
    branch_ids = sorted(list(set(r["branch_canal_id"] for r in results)))
    branch_names = {}
    for bid in branch_ids:
        bc = db.execute("SELECT * FROM branch_canals WHERE id = ?", (bid,)).fetchone()
        branch_names[bid] = bc["name"] if bc else f"支渠{bid}"
    flows = {}
    for bid in branch_ids:
        flows[bid] = []
        for d in dates:
            r = next((r for r in results if r["date"] == d and r["branch_canal_id"] == bid), None)
            flows[bid].append(round(r["flow"], 4) if r else 0.0)
    db.close()
    return {
        "dates": dates,
        "branches": [{"id": bid, "name": branch_names[bid]} for bid in branch_ids],
        "flows": flows,
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
        rule_result = {"rule": rule_key, "label": rule_label, "dates": [], "branches": {}}
        for bc in branch_canals:
            rule_result["branches"][bc["id"]] = {"name": bc["name"], "flows": []}
        for record in ts:
            rule_result["dates"].append(record["date"])
            for br in record["branches"]:
                if br["branch_canal_id"] in rule_result["branches"]:
                    rule_result["branches"][br["branch_canal_id"]]["flows"].append(round(br["flow"], 4))
        rules_data.append(rule_result)
    db.close()
    return {"rules": rules_data, "branch_canals": [{"id": bc["id"], "name": bc["name"]} for bc in branch_canals]}
