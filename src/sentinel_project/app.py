from __future__ import annotations

from fastapi import FastAPI

from sentinel_project.api.api import app as api_app

app = FastAPI(title="Sentinel Project")
app.mount("/api", api_app)


@app.get("/")
def home() -> dict[str, str]:
    return {"message": "Sentinel Project is running."}
