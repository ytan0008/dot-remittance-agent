"""Standalone server: the workspace UI at / and the API at /api, matching the Docker Nginx layout."""
from pathlib import Path
from starlette.staticfiles import StaticFiles
from .api import create_app

DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


class Standalone:
    def __init__(self):
        self.api = create_app()
        self.static = StaticFiles(directory=DIST, html=True)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.api(scope, receive, send)
        path = scope.get("path", "")
        if path == "/api" or path.startswith("/api/"):
            scope = dict(scope, root_path="/api")  # docs and OpenAPI then resolve under /api
            return await self.api(scope, receive, send)
        if scope["type"] == "http" and not (DIST / path.lstrip("/")).is_file():
            scope = dict(scope, path="/")  # single-page fallback
        return await self.static(scope, receive, send)


app = Standalone()
