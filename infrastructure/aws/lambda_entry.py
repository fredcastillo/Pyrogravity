"""Route public application requests and preserve the scientific demo endpoints."""

from mangum import Mangum

from infrastructure.demo.app import api as demo_api


async def application(scope, receive, send):
    path = scope.get("path", "")
    if path.startswith("/api/v1/ai/"):
        from app.main import app

        await app(scope, receive, send)
        return
    await demo_api(scope, receive, send)


handler = Mangum(application, lifespan="off")
