"""Job 저장소.

JobRepository  — 저장소 인터페이스 (ABC)
FileJobRepository — 파일 기반 구현 (data/jobs/*.json)

공개 함수(create_job, get_job, update_job)는 기본 구현(_repo)에 위임한다.
향후 DB 구현은 JobRepository를 상속해 _repo에 교체하면 된다.

session_store.py와 동일한 패턴.
"""

import json
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.schemas.job import Job, JobStatus

logger = logging.getLogger(__name__)


# ── 인터페이스 ────────────────────────────────────────────────────

class JobRepository(ABC):
    @abstractmethod
    def create(self, job_type: str, session_id: Optional[str] = None) -> Job:
        """새 Job을 PENDING 상태로 생성해 반환."""
        ...

    @abstractmethod
    def get(self, job_id: str) -> Optional[Job]:
        """job_id로 조회. 없으면 None."""
        ...

    @abstractmethod
    def update(
        self,
        job_id: str,
        status: JobStatus,
        result: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Optional[Job]:
        """상태를 갱신한다. job_id가 없으면 None 반환."""
        ...


# ── 파일 기반 구현 ────────────────────────────────────────────────

_JOBS_DIR = Path("data/jobs")


class FileJobRepository(JobRepository):
    """data/jobs/{job_id}.json 파일 기반 구현."""

    def __init__(self) -> None:
        _JOBS_DIR.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        p = _JOBS_DIR / f"{job_id}.json"
        if not p.resolve().is_relative_to(_JOBS_DIR.resolve()):
            raise ValueError(f"Invalid job_id: {job_id!r}")
        return p

    def _load_raw(self, job_id: str) -> Optional[dict]:
        p = self._path(job_id)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error("[Job] 로드 실패 %s: %s", job_id, e)
            return None

    def _save_raw(self, data: dict) -> None:
        self._path(data["job_id"]).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def create(self, job_type: str, session_id: Optional[str] = None) -> Job:
        now = datetime.now(timezone.utc).isoformat()
        job = Job(
            job_id=str(uuid.uuid4()),
            job_type=job_type,
            status=JobStatus.PENDING,
            created_at=now,
            updated_at=now,
            session_id=session_id,
        )
        self._save_raw(job.model_dump())
        logger.info("[Job] 생성 %s... type=%s", job.job_id[:8], job_type)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        raw = self._load_raw(job_id)
        if raw is None:
            return None
        try:
            return Job.model_validate(raw)
        except Exception as e:
            logger.error("[Job] 역직렬화 실패 %s: %s", job_id, e)
            return None

    def update(
        self,
        job_id: str,
        status: JobStatus,
        result: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Optional[Job]:
        raw = self._load_raw(job_id)
        if raw is None:
            logger.warning("[Job] update 대상 없음: %s", job_id)
            return None
        raw["status"] = status.value
        raw["updated_at"] = datetime.now(timezone.utc).isoformat()
        if result is not None:
            raw["result"] = result
        if error is not None:
            raw["error"] = error
        self._save_raw(raw)
        logger.info("[Job] 상태 변경 %s... → %s", job_id[:8], status.value)
        try:
            return Job.model_validate(raw)
        except Exception as e:
            logger.error("[Job] 역직렬화 실패 (update 후) %s: %s", job_id, e)
            return None


# ── 기본 인스턴스 ─────────────────────────────────────────────────

_repo: JobRepository = FileJobRepository()


# ── 공개 함수 ─────────────────────────────────────────────────────

def create_job(job_type: str, session_id: Optional[str] = None) -> Job:
    return _repo.create(job_type, session_id)


def get_job(job_id: str) -> Optional[Job]:
    return _repo.get(job_id)


def update_job(
    job_id: str,
    status: JobStatus,
    result: Optional[dict[str, Any]] = None,
    error: Optional[str] = None,
) -> Optional[Job]:
    return _repo.update(job_id, status, result, error)
