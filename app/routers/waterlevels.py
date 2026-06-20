from datetime import datetime
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from app.database import get_db

router = APIRouter()

@router.get("/weirs/{weir_id}/waterlevels", response_class=HTMLResponse)
def waterlevels_page(request: Request, weir_id: int):
    db = get_db()
    weir = db.execute("SELECT * FROM weirs WHERE id = ?", (weir_id,)).fetchone()
    if not weir:
        db.close()
        raise HTTPException(status_code=404, detail="堰坝不存在")
    levels = db.execute("SELECT * FROM water_levels WHERE weir_id = ? ORDER BY date", (weir_id,)).fetchall()
    db.close()
    return getattr(request.app.state, "templates", None).TemplateResponse(
        request, "waterlevels.html", {"weir": weir, "levels": levels}
    )

@router.post("/weirs/{weir_id}/waterlevels")
def create_waterlevel(weir_id: int, date: str = Form(...), level: float = Form(...), is_simulated: str = Form("off")):
    if level < 0:
        raise HTTPException(status_code=400, detail="水位不能为负数")
    sim = 1 if is_simulated == "on" else 0
    db = get_db()
    existing = db.execute("SELECT id FROM water_levels WHERE weir_id = ? AND date = ?", (weir_id, date)).fetchone()
    if existing:
        db.execute("UPDATE water_levels SET level=?, is_simulated=? WHERE id=?", (level, sim, existing["id"]))
    else:
        db.execute("INSERT INTO water_levels (weir_id, date, level, is_simulated) VALUES (?, ?, ?, ?)", (weir_id, date, level, sim))
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/waterlevels", status_code=303)

@router.post("/weirs/{weir_id}/waterlevels/batch")
def batch_create_waterlevels(weir_id: int, dates: str = Form(...), levels: str = Form(...), is_simulated: str = Form("off")):
    sim = 1 if is_simulated == "on" else 0
    date_lines = [d.strip() for d in dates.strip().split("\n") if d.strip()]
    level_lines = [l.strip() for l in levels.strip().split("\n") if l.strip()]
    if len(date_lines) != len(level_lines):
        raise HTTPException(
            status_code=400,
            detail=f"日期行数({len(date_lines)}行)与水位行数({len(level_lines)}行)不匹配，请检查"
        )
    date_list = []
    level_list = []
    for i, (d, l) in enumerate(zip(date_lines, level_lines), 1):
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail=f"第{i}行日期格式错误：{d}，请使用 YYYY-MM-DD 格式")
        try:
            lv = float(l)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"第{i}行水位值错误：{l}，请填写数字")
        if lv < 0:
            raise HTTPException(status_code=400, detail=f"第{i}行水位不能为负数：{l}")
        date_list.append(dt.strftime("%Y-%m-%d"))
        level_list.append(lv)
    db = get_db()
    for d, l in zip(date_list, level_list):
        existing = db.execute("SELECT id FROM water_levels WHERE weir_id = ? AND date = ?", (weir_id, d)).fetchone()
        if existing:
            db.execute("UPDATE water_levels SET level=?, is_simulated=? WHERE id=?", (l, sim, existing["id"]))
        else:
            db.execute("INSERT INTO water_levels (weir_id, date, level, is_simulated) VALUES (?, ?, ?, ?)", (weir_id, d, l, sim))
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/waterlevels", status_code=303)

@router.post("/waterlevels/{level_id}/delete")
def delete_waterlevel(level_id: int):
    db = get_db()
    wl = db.execute("SELECT * FROM water_levels WHERE id = ?", (level_id,)).fetchone()
    if not wl:
        db.close()
        raise HTTPException(status_code=404, detail="水位记录不存在")
    weir_id = wl["weir_id"]
    db.execute("DELETE FROM water_levels WHERE id = ?", (level_id,))
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/waterlevels", status_code=303)
