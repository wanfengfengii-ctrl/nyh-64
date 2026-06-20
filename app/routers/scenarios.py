import json
from typing import Optional, List
from fastapi import APIRouter, Request, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from app.database import get_db
from app.calc import (
    compute_main_canal_flow,
    compute_time_series,
    check_over_allocation,
    filter_continuous_dates,
    detect_missing_dates,
    suggest_filled_levels,
    detect_anomalies,
    run_consistency_checks,
    get_year_from_date,
    RULE_FUNCTIONS,
)
from app.models import (
    SeasonalRuleCreate,
    SeasonalRuleUpdate,
    ScenarioCreate,
    FARM_TYPE_LABELS,
)

router = APIRouter()

RULE_LABELS = {
    "equal": "均分",
    "downstream_first": "优先下游",
    "acreage_ratio": "按田亩比例",
}
SEASON_NAMES = {
    1: "春季", 2: "春季", 3: "春季",
    4: "夏季", 5: "夏季", 6: "夏季",
    7: "秋季", 8: "秋季", 9: "秋季",
    10: "冬季", 11: "冬季", 12: "冬季",
}
ANOMALY_LABELS = {
    "outlier": "离群值",
    "sudden_change": "骤变",
    "negative": "负值",
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


@router.get("/weirs/{weir_id}/scenarios", response_class=HTMLResponse)
def scenarios_page(request: Request, weir_id: int):
    db = get_db()
    weir = db.execute("SELECT * FROM weirs WHERE id = ?", (weir_id,)).fetchone()
    if not weir:
        db.close()
        raise HTTPException(status_code=404, detail="堰坝不存在")

    main_canals = db.execute(
        "SELECT * FROM main_canals WHERE weir_id = ?", (weir_id,)
    ).fetchall()
    branch_canals_map = {}
    for mc in main_canals:
        branch_canals_map[mc["id"]] = _build_branch_canals(db, mc["id"])

    seasonal_rules = db.execute(
        "SELECT * FROM seasonal_rules WHERE weir_id = ? ORDER BY start_month, id",
        (weir_id,),
    ).fetchall()

    scenarios = db.execute(
        "SELECT * FROM scenarios WHERE weir_id = ? ORDER BY id DESC", (weir_id,)
    ).fetchall()
    scenario_rules = {}
    for s in scenarios:
        links = db.execute(
            """SELECT sr.* FROM seasonal_rules sr
               JOIN scenario_seasonal_rule_links l ON l.seasonal_rule_id = sr.id
               WHERE l.scenario_id = ? ORDER BY sr.start_month""",
            (s["id"],),
        ).fetchall()
        scenario_rules[s["id"]] = links

    water_levels = db.execute(
        "SELECT * FROM water_levels WHERE weir_id = ? ORDER BY date", (weir_id,)
    ).fetchall()
    wl_dicts = [{"date": wl["date"], "level": wl["level"]} for wl in water_levels]
    date_list = [wl["date"] for wl in water_levels]
    years = sorted(list({get_year_from_date(d) for d in date_list if get_year_from_date(d) > 0}))
    missing_dates = detect_missing_dates(date_list)
    fill_suggestions = suggest_filled_levels(missing_dates, wl_dicts)
    anomalies = detect_anomalies(wl_dicts)

    unresolved_anomalies = db.execute(
        "SELECT * FROM data_anomalies WHERE weir_id = ? AND is_resolved = 0 ORDER BY date",
        (weir_id,),
    ).fetchall()

    db.close()
    return getattr(request.app.state, "templates", None).TemplateResponse(
        request,
        "scenarios.html",
        {
            "weir": weir,
            "main_canals": main_canals,
            "branch_canals_map": branch_canals_map,
            "seasonal_rules": seasonal_rules,
            "scenarios": scenarios,
            "scenario_rules": scenario_rules,
            "water_levels": water_levels,
            "available_years": years,
            "missing_dates": missing_dates[:50],
            "fill_suggestions": fill_suggestions[:50],
            "anomalies": anomalies,
            "unresolved_anomalies": unresolved_anomalies,
            "rule_labels": RULE_LABELS,
            "farm_type_labels": FARM_TYPE_LABELS,
            "anomaly_labels": ANOMALY_LABELS,
            "season_names": SEASON_NAMES,
        },
    )


@router.post("/weirs/{weir_id}/seasonal-rules")
def create_seasonal_rule(
    weir_id: int,
    name: str = Form(...),
    description: str = Form(""),
    start_month: int = Form(1),
    end_month: int = Form(12),
    rule: str = Form("equal"),
    priority_farm_type: str = Form(""),
    priority_ratio: float = Form(1.0),
    water_level_threshold: float = Form(0),
):
    if rule not in ("equal", "downstream_first", "acreage_ratio"):
        raise HTTPException(status_code=400, detail="无效的分水规则")
    if start_month < 1 or start_month > 12 or end_month < 1 or end_month > 12:
        raise HTTPException(status_code=400, detail="月份必须在1-12之间")
    if priority_ratio <= 0:
        raise HTTPException(status_code=400, detail="优先级系数必须大于0")

    db = get_db()
    db.execute(
        """INSERT INTO seasonal_rules
           (weir_id, name, description, start_month, end_month, rule,
            priority_farm_type, priority_ratio, water_level_threshold)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            weir_id, name, description, start_month, end_month, rule,
            priority_farm_type, priority_ratio, water_level_threshold,
        ),
    )
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/scenarios", status_code=303)


@router.post("/seasonal-rules/{rule_id}/edit")
def update_seasonal_rule(
    rule_id: int,
    name: str = Form(...),
    description: str = Form(""),
    start_month: int = Form(1),
    end_month: int = Form(12),
    rule: str = Form("equal"),
    priority_farm_type: str = Form(""),
    priority_ratio: float = Form(1.0),
    water_level_threshold: float = Form(0),
):
    if rule not in ("equal", "downstream_first", "acreage_ratio"):
        raise HTTPException(status_code=400, detail="无效的分水规则")
    if start_month < 1 or start_month > 12 or end_month < 1 or end_month > 12:
        raise HTTPException(status_code=400, detail="月份必须在1-12之间")
    if priority_ratio <= 0:
        raise HTTPException(status_code=400, detail="优先级系数必须大于0")

    db = get_db()
    sr = db.execute("SELECT * FROM seasonal_rules WHERE id = ?", (rule_id,)).fetchone()
    if not sr:
        db.close()
        raise HTTPException(status_code=404, detail="季节规则不存在")
    weir_id = sr["weir_id"]
    db.execute(
        """UPDATE seasonal_rules SET
           name = ?, description = ?, start_month = ?, end_month = ?,
           rule = ?, priority_farm_type = ?, priority_ratio = ?,
           water_level_threshold = ? WHERE id = ?""",
        (
            name, description, start_month, end_month, rule,
            priority_farm_type, priority_ratio, water_level_threshold, rule_id,
        ),
    )
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/scenarios", status_code=303)


@router.post("/seasonal-rules/{rule_id}/delete")
def delete_seasonal_rule(rule_id: int):
    db = get_db()
    sr = db.execute("SELECT * FROM seasonal_rules WHERE id = ?", (rule_id,)).fetchone()
    if not sr:
        db.close()
        raise HTTPException(status_code=404, detail="季节规则不存在")
    weir_id = sr["weir_id"]
    db.execute("DELETE FROM scenario_seasonal_rule_links WHERE seasonal_rule_id = ?", (rule_id,))
    db.execute("DELETE FROM seasonal_rules WHERE id = ?", (rule_id,))
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/scenarios", status_code=303)


@router.post("/weirs/{weir_id}/scenarios")
def create_scenario(
    weir_id: int,
    name: str = Form(...),
    description: str = Form(""),
    main_canal_id: Optional[int] = Form(None),
    year_from: str = Form(""),
    year_to: str = Form(""),
    seasonal_rule_ids: str = Form(""),
):
    db = get_db()
    yf = int(year_from) if year_from.strip() else None
    yt = int(year_to) if year_to.strip() else None
    rule_ids = [int(x.strip()) for x in seasonal_rule_ids.split(",") if x.strip()]

    cur = db.execute(
        """INSERT INTO scenarios
           (weir_id, name, description, main_canal_id, year_from, year_to, scenario_type, status)
           VALUES (?, ?, ?, ?, ?, ?, 'historical', 'draft')""",
        (weir_id, name, description, main_canal_id, yf, yt),
    )
    scenario_id = cur.lastrowid
    for rid in rule_ids:
        try:
            db.execute(
                """INSERT OR IGNORE INTO scenario_seasonal_rule_links
                   (scenario_id, seasonal_rule_id) VALUES (?, ?)""",
                (scenario_id, rid),
            )
        except Exception:
            pass
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/scenarios", status_code=303)


@router.post("/scenarios/{scenario_id}/delete")
def delete_scenario(scenario_id: int):
    db = get_db()
    s = db.execute("SELECT * FROM scenarios WHERE id = ?", (scenario_id,)).fetchone()
    if not s:
        db.close()
        raise HTTPException(status_code=404, detail="场景不存在")
    weir_id = s["weir_id"]
    db.execute("DELETE FROM scenario_results WHERE scenario_id = ?", (scenario_id,))
    db.execute("DELETE FROM scenario_seasonal_rule_links WHERE scenario_id = ?", (scenario_id,))
    db.execute("DELETE FROM scenarios WHERE id = ?", (scenario_id,))
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/scenarios", status_code=303)


@router.post("/scenarios/{scenario_id}/run")
def run_scenario(scenario_id: int):
    db = get_db()
    scenario = db.execute("SELECT * FROM scenarios WHERE id = ?", (scenario_id,)).fetchone()
    if not scenario:
        db.close()
        raise HTTPException(status_code=404, detail="场景不存在")
    weir_id = scenario["weir_id"]
    if not scenario["main_canal_id"]:
        db.close()
        raise HTTPException(status_code=400, detail="请选择主渠")

    mc = db.execute(
        "SELECT * FROM main_canals WHERE id = ?", (scenario["main_canal_id"],)
    ).fetchone()
    if not mc:
        db.close()
        raise HTTPException(status_code=404, detail="主渠不存在")

    branch_canals = _build_branch_canals(db, scenario["main_canal_id"])
    if not branch_canals:
        db.close()
        raise HTTPException(status_code=400, detail="主渠下没有支渠")

    rule_links = db.execute(
        "SELECT seasonal_rule_id FROM scenario_seasonal_rule_links WHERE scenario_id = ?",
        (scenario_id,),
    ).fetchall()
    seasonal_rules = []
    for link in rule_links:
        sr = db.execute(
            "SELECT * FROM seasonal_rules WHERE id = ?", (link["seasonal_rule_id"],)
        ).fetchone()
        if sr:
            seasonal_rules.append(dict(sr))

    water_levels = db.execute(
        "SELECT * FROM water_levels WHERE weir_id = ? ORDER BY date", (weir_id,)
    ).fetchall()
    wl_data = []
    for wl in water_levels:
        year = get_year_from_date(wl["date"])
        if scenario["year_from"] and year < scenario["year_from"]:
            continue
        if scenario["year_to"] and year > scenario["year_to"]:
            continue
        wl_data.append({"date": wl["date"], "level": wl["level"]})

    if not wl_data:
        db.close()
        raise HTTPException(status_code=400, detail="所选年份范围内没有水位数据")

    all_dates = [wl["date"] for wl in wl_data]
    continuous_dates = filter_continuous_dates(all_dates)
    filtered_levels = [wl for wl in wl_data if wl["date"] in continuous_dates]
    if not filtered_levels:
        db.close()
        raise HTTPException(status_code=400, detail="没有有效的水位数据")

    ts = compute_time_series(
        filtered_levels, mc["width"], branch_canals, "equal", seasonal_rules
    )

    db.execute("DELETE FROM scenario_results WHERE scenario_id = ?", (scenario_id,))
    for record in ts:
        if record["over_allocated"]:
            db.close()
            raise HTTPException(
                status_code=400,
                detail=f"日期 {record['date']} 存在超配水量，无法保存推演结果",
            )
        for br in record["branches"]:
            db.execute(
                """INSERT INTO scenario_results
                   (scenario_id, seasonal_rule_id, date, branch_canal_id, flow, coverage)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    scenario_id,
                    record.get("seasonal_rule_id"),
                    record["date"],
                    br["branch_canal_id"],
                    br["flow"],
                    br.get("coverage", 0),
                ),
            )
    db.execute(
        "UPDATE scenarios SET status = 'computed' WHERE id = ?", (scenario_id,)
    )
    db.commit()
    db.close()
    return RedirectResponse(
        url=f"/weirs/{weir_id}/scenarios#scenario-{scenario_id}", status_code=303
    )


@router.get("/scenarios/{scenario_id}/chart-data")
def scenario_chart_data(scenario_id: int):
    db = get_db()
    scenario = db.execute("SELECT * FROM scenarios WHERE id = ?", (scenario_id,)).fetchone()
    if not scenario:
        db.close()
        return {"dates": [], "branches": [], "flows": {}, "coverages": {}}

    results = db.execute(
        "SELECT * FROM scenario_results WHERE scenario_id = ? ORDER BY date",
        (scenario_id,),
    ).fetchall()
    if not results:
        db.close()
        return {"dates": [], "branches": [], "flows": {}, "coverages": {}}

    dates = sorted(list({r["date"] for r in results}))
    branch_ids = sorted(list({r["branch_canal_id"] for r in results}))
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
            r = next(
                (r for r in results if r["date"] == d and r["branch_canal_id"] == bid),
                None,
            )
            flows[bid].append(round(r["flow"], 4) if r else 0.0)
            coverages[bid].append(round(r["coverage"], 4) if r else 0.0)

    summary = {
        "total_flow": 0.0,
        "avg_flow_per_branch": {},
        "avg_coverage_per_branch": {},
        "overall_avg_coverage": 0.0,
    }
    total_cov_sum = 0.0
    total_cov_count = 0
    for bid in branch_ids:
        avg_flow = sum(flows[bid]) / len(flows[bid]) if flows[bid] else 0
        avg_cov = sum(coverages[bid]) / len(coverages[bid]) if coverages[bid] else 0
        summary["avg_flow_per_branch"][bid] = round(avg_flow, 4)
        summary["avg_coverage_per_branch"][bid] = round(avg_cov, 4)
        summary["total_flow"] += sum(flows[bid])
        total_cov_sum += sum(coverages[bid])
        total_cov_count += len(coverages[bid])
    summary["total_flow"] = round(summary["total_flow"], 4)
    summary["overall_avg_coverage"] = round(
        total_cov_sum / total_cov_count, 4
    ) if total_cov_count > 0 else 0.0

    db.close()
    return {
        "dates": dates,
        "branches": [{"id": bid, "name": branch_names[bid]} for bid in branch_ids],
        "flows": flows,
        "coverages": coverages,
        "summary": summary,
    }


@router.get("/weirs/{weir_id}/scenario-compare-data")
def scenario_compare_data(
    weir_id: int,
    main_canal_id: int,
    scenario_ids: str = Query(""),
):
    db = get_db()
    weir = db.execute("SELECT * FROM weirs WHERE id = ?", (weir_id,)).fetchone()
    if not weir:
        db.close()
        return {"scenarios": []}

    mc = db.execute("SELECT * FROM main_canals WHERE id = ?", (main_canal_id,)).fetchone()
    if not mc:
        db.close()
        return {"scenarios": []}

    branch_canals = _build_branch_canals(db, main_canal_id)
    if not branch_canals:
        db.close()
        return {"scenarios": []}

    water_levels = db.execute(
        "SELECT * FROM water_levels WHERE weir_id = ? ORDER BY date", (weir_id,)
    ).fetchall()
    if not water_levels:
        db.close()
        return {"scenarios": []}

    all_dates = [wl["date"] for wl in water_levels]
    continuous_dates = filter_continuous_dates(all_dates)
    filtered_levels = [
        {"date": wl["date"], "level": wl["level"]}
        for wl in water_levels if wl["date"] in continuous_dates
    ]

    scenarios_list = []
    sid_list = [int(s.strip()) for s in scenario_ids.split(",") if s.strip()]

    all_schemes_data = []
    for rule_key, rule_label in RULE_LABELS.items():
        ts = compute_time_series(filtered_levels, mc["width"], branch_canals, rule_key)
        scenario_entry = {
            "id": f"rule-{rule_key}",
            "name": f"基础规则：{rule_label}",
            "type": "rule",
            "dates": [],
            "branch_flows": {bc["id"]: [] for bc in branch_canals},
            "branch_coverages": {bc["id"]: [] for bc in branch_canals},
        }
        for record in ts:
            scenario_entry["dates"].append(record["date"])
            br_map = {br["branch_canal_id"]: br for br in record["branches"]}
            for bc in branch_canals:
                br = br_map.get(bc["id"], {"flow": 0, "coverage": 0})
                scenario_entry["branch_flows"][bc["id"]].append(
                    round(br.get("flow", 0), 4)
                )
                scenario_entry["branch_coverages"][bc["id"]].append(
                    round(br.get("coverage", 0), 4)
                )
        all_schemes_data.append(scenario_entry)

    for sid in sid_list:
        s = db.execute("SELECT * FROM scenarios WHERE id = ?", (sid,)).fetchone()
        if not s:
            continue
        rule_links = db.execute(
            "SELECT seasonal_rule_id FROM scenario_seasonal_rule_links WHERE scenario_id = ?",
            (sid,),
        ).fetchall()
        seasonal_rules = []
        for link in rule_links:
            sr = db.execute(
                "SELECT * FROM seasonal_rules WHERE id = ?",
                (link["seasonal_rule_id"],),
            ).fetchone()
            if sr:
                seasonal_rules.append(dict(sr))

        s_wl_data = []
        for wl in water_levels:
            year = get_year_from_date(wl["date"])
            if s["year_from"] and year < s["year_from"]:
                continue
            if s["year_to"] and year > s["year_to"]:
                continue
            s_wl_data.append({"date": wl["date"], "level": wl["level"]})

        ts = compute_time_series(
            s_wl_data, mc["width"], branch_canals, "equal", seasonal_rules
        )
        scenario_entry = {
            "id": f"scenario-{sid}",
            "name": s["name"],
            "type": "scenario",
            "dates": [],
            "branch_flows": {bc["id"]: [] for bc in branch_canals},
            "branch_coverages": {bc["id"]: [] for bc in branch_canals},
        }
        for record in ts:
            scenario_entry["dates"].append(record["date"])
            br_map = {br["branch_canal_id"]: br for br in record["branches"]}
            for bc in branch_canals:
                br = br_map.get(bc["id"], {"flow": 0, "coverage": 0})
                scenario_entry["branch_flows"][bc["id"]].append(
                    round(br.get("flow", 0), 4)
                )
                scenario_entry["branch_coverages"][bc["id"]].append(
                    round(br.get("coverage", 0), 4)
                )
        all_schemes_data.append(scenario_entry)

    branch_info = [
        {"id": bc["id"], "name": bc["name"], "farm_type": bc["farm_type"], "acreage": bc["acreage"]}
        for bc in branch_canals
    ]

    db.close()
    return {"scenarios": all_schemes_data, "branch_canals": branch_info}


@router.get("/weirs/{weir_id}/data-quality")
def data_quality_report(weir_id: int):
    db = get_db()
    weir = db.execute("SELECT * FROM weirs WHERE id = ?", (weir_id,)).fetchone()
    if not weir:
        db.close()
        raise HTTPException(status_code=404, detail="堰坝不存在")

    water_levels = db.execute(
        "SELECT * FROM water_levels WHERE weir_id = ? ORDER BY date", (weir_id,)
    ).fetchall()
    wl_dicts = [{"date": wl["date"], "level": wl["level"]} for wl in water_levels]
    date_list = [wl["date"] for wl in water_levels]

    missing_dates = detect_missing_dates(date_list)
    fill_suggestions = suggest_filled_levels(missing_dates, wl_dicts)
    anomalies = detect_anomalies(wl_dicts)

    main_canals = db.execute(
        "SELECT * FROM main_canals WHERE weir_id = ?", (weir_id,)
    ).fetchall()
    quality_issues = []
    for mc in main_canals:
        bcs = db.execute(
            "SELECT * FROM branch_canals WHERE main_canal_id = ?", (mc["id"],)
        ).fetchall()
        if not bcs:
            quality_issues.append({
                "type": "no_branches",
                "detail": f"主渠「{mc['name']}」下没有支渠",
                "suggestion": "请在渠闸参数中添加支渠",
            })
        for bc in bcs:
            gs = db.execute(
                "SELECT * FROM gates WHERE branch_canal_id = ?", (bc["id"],)
            ).fetchall()
            if not gs:
                quality_issues.append({
                    "type": "no_gates",
                    "detail": f"支渠「{bc['name']}」下没有闸口",
                    "suggestion": "请为该支渠添加闸口，否则按全开计算",
                })
            if bc["acreage"] <= 0:
                quality_issues.append({
                    "type": "zero_acreage",
                    "detail": f"支渠「{bc['name']}」田亩数为0",
                    "suggestion": "按田亩比例分水规则将受影响，建议补充田亩数",
                })

    db.close()
    return {
        "water_level_count": len(water_levels),
        "missing_dates_count": len(missing_dates),
        "missing_dates_sample": missing_dates[:20],
        "fill_suggestions": fill_suggestions[:20],
        "anomalies": anomalies,
        "quality_issues": quality_issues,
    }


@router.post("/weirs/{weir_id}/anomalies/resolve-all")
def resolve_all_anomalies(weir_id: int):
    db = get_db()
    db.execute(
        "UPDATE data_anomalies SET is_resolved = 1 WHERE weir_id = ? AND is_resolved = 0",
        (weir_id,),
    )
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/scenarios", status_code=303)


@router.post("/weirs/{weir_id}/fill-missing")
def fill_missing_dates(
    weir_id: int,
    selected_dates: str = Form(""),
):
    db = get_db()
    weir = db.execute("SELECT * FROM weirs WHERE id = ?", (weir_id,)).fetchone()
    if not weir:
        db.close()
        raise HTTPException(status_code=404, detail="堰坝不存在")

    water_levels = db.execute(
        "SELECT * FROM water_levels WHERE weir_id = ? ORDER BY date", (weir_id,)
    ).fetchall()
    wl_dicts = [{"date": wl["date"], "level": wl["level"]} for wl in water_levels]
    date_list = [wl["date"] for wl in water_levels]
    missing_dates = detect_missing_dates(date_list)
    suggestions = {s["date"]: s["level"] for s in suggest_filled_levels(missing_dates, wl_dicts)}

    selected = [d.strip() for d in selected_dates.split(",") if d.strip()]
    filled_count = 0
    for d in selected:
        if d in suggestions:
            existing = db.execute(
                "SELECT id FROM water_levels WHERE weir_id = ? AND date = ?",
                (weir_id, d),
            ).fetchone()
            if not existing:
                db.execute(
                    "INSERT INTO water_levels (weir_id, date, level, is_simulated) VALUES (?, ?, ?, 1)",
                    (weir_id, d, suggestions[d]),
                )
                filled_count += 1
    db.commit()
    db.close()
    return RedirectResponse(
        url=f"/weirs/{weir_id}/scenarios#data-quality", status_code=303
    )


@router.get("/schemes/{scheme_id}/consistency-check")
def consistency_check(scheme_id: int):
    db = get_db()
    scheme = db.execute("SELECT * FROM schemes WHERE id = ?", (scheme_id,)).fetchone()
    if not scheme:
        db.close()
        raise HTTPException(status_code=404, detail="方案不存在")

    weir_id = scheme["weir_id"]
    if not scheme["main_canal_id"]:
        db.close()
        return {"checks": [], "all_passed": False, "summary": "方案尚未计算"}

    mc = db.execute(
        "SELECT * FROM main_canals WHERE id = ?", (scheme["main_canal_id"],)
    ).fetchone()
    if not mc:
        db.close()
        return {"checks": [], "all_passed": False, "summary": "关联的主渠已被删除"}

    branch_canals = _build_branch_canals(db, scheme["main_canal_id"])
    water_levels = db.execute(
        "SELECT * FROM water_levels WHERE weir_id = ? ORDER BY date", (weir_id,)
    ).fetchall()
    results = db.execute(
        "SELECT * FROM scheme_results WHERE scheme_id = ?", (scheme_id,)
    ).fetchall()

    ts_results = []
    if results:
        dates = sorted(list({r["date"] for r in results}))
        for d in dates:
            day_results = [r for r in results if r["date"] == d]
            branches = []
            for r in day_results:
                bc = next(
                    (b for b in branch_canals if b["id"] == r["branch_canal_id"]),
                    None,
                )
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

    db.execute("DELETE FROM consistency_checks WHERE target_type = 'scheme' AND target_id = ?", (scheme_id,))
    for c in checks:
        db.execute(
            """INSERT INTO consistency_checks
               (target_type, target_id, check_type, passed, detail)
               VALUES ('scheme', ?, ?, ?, ?)""",
            (scheme_id, c["check_type"], 1 if c["passed"] else 0, c["detail"]),
        )
    db.commit()
    db.close()
    return {"checks": checks, "all_passed": all_passed, "summary": "全部通过" if all_passed else "存在问题需要修正"}
