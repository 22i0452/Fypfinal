"""Restrict deployed receptionist tools to the existing signed-in demo doctors."""
from starlette.responses import JSONResponse, RedirectResponse


class DemoAccessMiddleware:
    def __init__(self, app, settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        protected = path.startswith('/api/desk/') or path == '/receptionist'
        if self.settings.is_demo and scope['type'] in {'http', 'websocket'} and protected:
            session = scope.get('session', {})
            identifier = session.get('user_id') or session.get('doctor_id')
            container = scope['app'].state.container
            user = container.auth_repository.get_by_id(identifier) if identifier else None
            if user is None or not user.active:
                if scope['type'] == 'websocket':
                    await send({'type':'websocket.close', 'code':4401})
                else:
                    response = (RedirectResponse('/consultation/login?next=/receptionist', status_code=302)
                                if path == '/receptionist' else JSONResponse({'detail':'Sign in to use the demo'},status_code=401))
                    await response(scope, receive, send)
                return
        await self.app(scope, receive, send)

