from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.services.demo_profiles import DOCTORS

router = APIRouter(tags=['deployment'])


@router.get('/healthz')
@router.get('/api/healthz')
async def health(request: Request):
    try:
        with request.app.state.container.database.connection() as db:
            db.execute('SELECT 1').fetchone()
    except Exception:
        return JSONResponse({'status':'unavailable'}, status_code=503)
    return {'status':'ok'}


@router.get('/api/demo-access')
async def demo_configuration(request: Request):
    settings = request.app.state.container.settings
    return {'demo':settings.is_demo, 'synthetic_only':settings.is_demo,
            'doctors':[{'name':name, 'email':email} for _,name,email in DOCTORS] if settings.demo_profiles_enabled else []}
