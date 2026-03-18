"""진입점 shim — 기존 `uvicorn app:app` 명령어 호환 유지."""

from app.main import app  # noqa: F401

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
