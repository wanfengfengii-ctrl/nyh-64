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
    date_list = [d.strip() for d in dates.strip().split("\n") if d.strip()]
    level_list = [float(l.strip()) for l in levels.strip().split("\n") if l.strip()]
    if len(date_list) != len(level_list):
        raise HTTPException(status_code=400, detail="日期与水位数量不匹配")
    for l in level_list:
        if l < 0:
            raise HTTPException(status_code=400, detail="水位不能为负数")
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
