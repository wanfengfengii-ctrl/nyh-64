from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from app.database import get_db

router = APIRouter()

@router.get("/weirs/{weir_id}/canals", response_class=HTMLResponse)
def canals_page(request: Request, weir_id: int):
    db = get_db()
    weir = db.execute("SELECT * FROM weirs WHERE id = ?", (weir_id,)).fetchone()
    if not weir:
        db.close()
        raise HTTPException(status_code=404, detail="堰坝不存在")
    main_canals = db.execute("SELECT * FROM main_canals WHERE weir_id = ? ORDER BY id", (weir_id,)).fetchall()
    main_canal_ids = [mc["id"] for mc in main_canals]
    branch_canals = {}
    gates = {}
    for mc_id in main_canal_ids:
        bcs = db.execute("SELECT * FROM branch_canals WHERE main_canal_id = ? ORDER BY position, id", (mc_id,)).fetchall()
        branch_canals[mc_id] = bcs
        for bc in bcs:
            gs = db.execute("SELECT * FROM gates WHERE branch_canal_id = ? ORDER BY id", (bc["id"],)).fetchall()
            gates[bc["id"]] = gs
    db.close()
    return getattr(request.app.state, "templates", None).TemplateResponse(
        request, "canals.html",
        {
            "weir": weir,
            "main_canals": main_canals,
            "branch_canals": branch_canals,
            "gates": gates,
        },
    )

@router.post("/weirs/{weir_id}/main-canals")
def create_main_canal(weir_id: int, name: str = Form(...), width: float = Form(1.0), description: str = Form("")):
    if width < 0:
        raise HTTPException(status_code=400, detail="主渠宽度不能为负数")
    db = get_db()
    db.execute("INSERT INTO main_canals (weir_id, name, width, description) VALUES (?, ?, ?, ?)", (weir_id, name, width, description))
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/canals", status_code=303)

@router.post("/main-canals/{canal_id}/edit")
def update_main_canal(canal_id: int, name: str = Form(...), width: float = Form(1.0), description: str = Form("")):
    if width < 0:
        raise HTTPException(status_code=400, detail="主渠宽度不能为负数")
    db = get_db()
    mc = db.execute("SELECT * FROM main_canals WHERE id = ?", (canal_id,)).fetchone()
    if not mc:
        db.close()
        raise HTTPException(status_code=404, detail="主渠不存在")
    db.execute("UPDATE main_canals SET name=?, width=?, description=? WHERE id=?", (name, width, description, canal_id))
    db.commit()
    weir_id = mc["weir_id"]
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/canals", status_code=303)

@router.post("/main-canals/{canal_id}/delete")
def delete_main_canal(canal_id: int):
    db = get_db()
    mc = db.execute("SELECT * FROM main_canals WHERE id = ?", (canal_id,)).fetchone()
    if not mc:
        db.close()
        raise HTTPException(status_code=404, detail="主渠不存在")
    weir_id = mc["weir_id"]
    db.execute("DELETE FROM main_canals WHERE id = ?", (canal_id,))
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/canals", status_code=303)

@router.post("/main-canals/{canal_id}/branch-canals")
def create_branch_canal(canal_id: int, name: str = Form(...), width: float = Form(0.5), acreage: float = Form(0.0), position: int = Form(0), description: str = Form("")):
    if width < 0:
        raise HTTPException(status_code=400, detail="支渠宽度不能为负数")
    if acreage < 0:
        raise HTTPException(status_code=400, detail="田亩数不能为负数")
    db = get_db()
    mc = db.execute("SELECT * FROM main_canals WHERE id = ?", (canal_id,)).fetchone()
    if not mc:
        db.close()
        raise HTTPException(status_code=404, detail="主渠不存在")
    db.execute("INSERT INTO branch_canals (main_canal_id, name, width, acreage, position, description) VALUES (?, ?, ?, ?, ?, ?)", (canal_id, name, width, acreage, position, description))
    db.commit()
    weir_id = mc["weir_id"]
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/canals", status_code=303)

@router.post("/branch-canals/{bc_id}/edit")
def update_branch_canal(bc_id: int, name: str = Form(...), width: float = Form(0.5), acreage: float = Form(0.0), position: int = Form(0), description: str = Form("")):
    if width < 0:
        raise HTTPException(status_code=400, detail="支渠宽度不能为负数")
    if acreage < 0:
        raise HTTPException(status_code=400, detail="田亩数不能为负数")
    db = get_db()
    bc = db.execute("SELECT * FROM branch_canals WHERE id = ?", (bc_id,)).fetchone()
    if not bc:
        db.close()
        raise HTTPException(status_code=404, detail="支渠不存在")
    db.execute("UPDATE branch_canals SET name=?, width=?, acreage=?, position=?, description=? WHERE id=?", (name, width, acreage, position, description, bc_id))
    db.commit()
    mc = db.execute("SELECT * FROM main_canals WHERE id = ?", (bc["main_canal_id"],)).fetchone()
    weir_id = mc["weir_id"]
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/canals", status_code=303)

@router.post("/branch-canals/{bc_id}/delete")
def delete_branch_canal(bc_id: int):
    db = get_db()
    bc = db.execute("SELECT * FROM branch_canals WHERE id = ?", (bc_id,)).fetchone()
    if not bc:
        db.close()
        raise HTTPException(status_code=404, detail="支渠不存在")
    mc = db.execute("SELECT * FROM main_canals WHERE id = ?", (bc["main_canal_id"],)).fetchone()
    weir_id = mc["weir_id"]
    db.execute("DELETE FROM branch_canals WHERE id = ?", (bc_id,))
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/canals", status_code=303)

@router.post("/branch-canals/{bc_id}/gates")
def create_gate(bc_id: int, name: str = Form(...), opening: int = Form(100), description: str = Form("")):
    if opening < 0 or opening > 100:
        raise HTTPException(status_code=400, detail="闸口开度必须在0-100之间")
    db = get_db()
    bc = db.execute("SELECT * FROM branch_canals WHERE id = ?", (bc_id,)).fetchone()
    if not bc:
        db.close()
        raise HTTPException(status_code=404, detail="支渠不存在")
    db.execute("INSERT INTO gates (branch_canal_id, name, opening, description) VALUES (?, ?, ?, ?)", (bc_id, name, opening, description))
    db.commit()
    mc = db.execute("SELECT * FROM main_canals WHERE id = ?", (bc["main_canal_id"],)).fetchone()
    weir_id = mc["weir_id"]
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/canals", status_code=303)

@router.post("/gates/{gate_id}/edit")
def update_gate(gate_id: int, name: str = Form(...), opening: int = Form(100), description: str = Form("")):
    if opening < 0 or opening > 100:
        raise HTTPException(status_code=400, detail="闸口开度必须在0-100之间")
    db = get_db()
    gate = db.execute("SELECT * FROM gates WHERE id = ?", (gate_id,)).fetchone()
    if not gate:
        db.close()
        raise HTTPException(status_code=404, detail="闸口不存在")
    db.execute("UPDATE gates SET name=?, opening=?, description=? WHERE id=?", (name, opening, description, gate_id))
    db.commit()
    bc = db.execute("SELECT * FROM branch_canals WHERE id = ?", (gate["branch_canal_id"],)).fetchone()
    mc = db.execute("SELECT * FROM main_canals WHERE id = ?", (bc["main_canal_id"],)).fetchone()
    weir_id = mc["weir_id"]
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/canals", status_code=303)

@router.post("/gates/{gate_id}/delete")
def delete_gate(gate_id: int):
    db = get_db()
    gate = db.execute("SELECT * FROM gates WHERE id = ?", (gate_id,)).fetchone()
    if not gate:
        db.close()
        raise HTTPException(status_code=404, detail="闸口不存在")
    bc = db.execute("SELECT * FROM branch_canals WHERE id = ?", (gate["branch_canal_id"],)).fetchone()
    mc = db.execute("SELECT * FROM main_canals WHERE id = ?", (bc["main_canal_id"],)).fetchone()
    weir_id = mc["weir_id"]
    db.execute("DELETE FROM gates WHERE id = ?", (gate_id,))
    db.commit()
    db.close()
    return RedirectResponse(url=f"/weirs/{weir_id}/canals", status_code=303)
