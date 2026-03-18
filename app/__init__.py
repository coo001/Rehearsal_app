# `uvicorn app:app` 호환 — app/ 패키지가 app.py보다 우선순위를 가지므로
# 여기서 FastAPI 인스턴스를 re-export한다.
from app.main import app  # noqa: F401
