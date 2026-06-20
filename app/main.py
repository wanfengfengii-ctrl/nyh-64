from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.database import init_db
from app.routers import weirs, canals, waterlevels, schemes, scenarios, schedule_logs, optimization, tracking, reports, review, gap_fix

app = FastAPI(title="传统堰坝分水研究系统")

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
app.state.templates = templates

init_db()

app.include_router(weirs.router)
app.include_router(canals.router)
app.include_router(waterlevels.router)
app.include_router(schemes.router)
app.include_router(scenarios.router)
app.include_router(schedule_logs.router)
app.include_router(optimization.router)
app.include_router(tracking.router)
app.include_router(reports.router)
app.include_router(review.router)
app.include_router(gap_fix.router)

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
