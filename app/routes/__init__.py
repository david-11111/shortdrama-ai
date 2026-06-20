from fastapi import APIRouter

from app.routes.agent_runs import router as agent_runs_router
from app.routes.admin import router as admin_router
from app.routes.auth import router as auth_router
from app.routes.credits import router as credits_router
from app.routes.director import router as director_router
from app.routes.keyframes import router as keyframes_router
from app.routes.media import router as media_router
from app.routes.payment import router as payment_router
from app.routes.prompt import router as prompt_router
from app.routes.reports import router as reports_router
from app.routes.tasks import router as tasks_router
from app.routes.users import router as users_router
from app.routes.ltx_desktop import router as ltx_desktop_router
from app.routes.webhooks import router as webhooks_router
from app.routes.workbench import router as workbench_router

api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(tasks_router)
api_router.include_router(credits_router)
api_router.include_router(payment_router)
api_router.include_router(admin_router)
api_router.include_router(reports_router)
api_router.include_router(webhooks_router)
api_router.include_router(workbench_router)
api_router.include_router(prompt_router)
api_router.include_router(director_router)
api_router.include_router(keyframes_router)
api_router.include_router(media_router)
api_router.include_router(agent_runs_router)
api_router.include_router(ltx_desktop_router)
