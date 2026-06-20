from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from app.database import get_db

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    db = get_db()
    weirs = db.execute("SELECT * FROM weirs ORDER BY id").fetchall()
    db.close()
    return getattr(request.app.state, "templates", None).TemplateResponse(request, "index.html", {"weirs": weirs})

@router.get("/weirs", response_class=HTMLResponse)
def weirs_page(request: Request):
    db = get_db()
    weirs = db.execute("SELECT * FROM weirs ORDER BY id").fetchall()
    db.close()
    return getattr(request.app.state, "templates", None).TemplateResponse(request, "weirs.html", {"weirs": weirs})

@router.post("/weirs")
def create_weir(name: str = Form(...), location: str = Form(""), description: str = Form("")):
    db = get_db()
    db.execute("INSERT INTO weirs (name, location, description) VALUES (?, ?, ?)", (name, location, description))
    db.commit()
    db.close()
    return RedirectResponse(url="/weirs", status_code=303)

@router.get("/weirs/{weir_id}/edit", response_class=HTMLResponse)
def edit_weir_page(request: Request, weir_id: int):
    db = get_db()
    weir = db.execute("SELECT * FROM weirs WHERE id = ?", (weir_id,)).fetchone()
    db.close()
    if not weir:
        raise HTTPException(status_code=404, detail="堰坝不存在")
    return getattr(request.app.state, "templates", None).TemplateResponse(request, "weir_edit.html", {"weir": weir})

@router.post("/weirs/{weir_id}/edit")
def update_weir(weir_id: int, name: str = Form(...), location: str = Form(""), description: str = Form("")):
    db = get_db()
    db.execute("UPDATE weirs SET name=?, location=?, description=? WHERE id=?", (name, location, description, weir_id))
    db.commit()
    db.close()
    return RedirectResponse(url="/weirs", status_code=303)

@router.post("/weirs/{weir_id}/delete")
def delete_weir(weir_id: int):
    db = get_db()
    db.execute("DELETE FROM weirs WHERE id = ?", (weir_id,))
    db.commit()
    db.close()
    return RedirectResponse(url="/weirs", status_code=303)
