"""동기 Job 실행 헬퍼.

run_job(job_type, fn, ...) → (Job, result)

현재는 동기 실행이지만 job store에 PENDING → RUNNING → SUCCEEDED/FAILED 상태를 기록한다.
향후 fn을 BackgroundTasks 또는 워커로 옮기면 비동기 전환이 완료된다.

사용 예:
    job, data = run_job(
        "parse_script",
        lambda: parse_script(text),
        result_summary=lambda d: {"title": d.get("title"), "lines": len(d.get("lines") or [])},
    )
"""

import logging
from typing import Any, Callable, Optional

from app.schemas.job import Job, JobStatus
from app.services.job_store import create_job, update_job

logger = logging.getLogger(__name__)


def run_job(
    job_type: str,
    fn: Callable[[], Any],
    session_id: Optional[str] = None,
    result_summary: Optional[Callable[[Any], dict]] = None,
) -> tuple[Job, Any]:
    """fn()을 실행하며 job 상태를 기록한다.

    Args:
        job_type:       "parse_script" | "parse_pdf" | "generate_rehearsal"
        fn:             실제 작업 callable (인자 없음)
        session_id:     연관 세션 ID (없으면 None)
        result_summary: 성공 시 job에 저장할 요약 dict를 만드는 콜백.
                        None이면 빈 dict 저장 (전체 결과는 저장하지 않음)

    Returns:
        (job, fn()의 반환값)

    Raises:
        fn()이 던진 예외를 그대로 re-raise. job 상태는 FAILED로 기록된 후다.
    """
    job = create_job(job_type, session_id=session_id)
    logger.info("[JobRunner] %s 시작 — job_id=%s...", job_type, job.job_id[:8])

    job = update_job(job.job_id, JobStatus.RUNNING)

    try:
        result = fn()
        summary = result_summary(result) if result_summary else {}
        job = update_job(job.job_id, JobStatus.SUCCEEDED, result=summary)
        logger.info("[JobRunner] %s 완료 — job_id=%s...", job_type, job.job_id[:8])
        return job, result
    except Exception as e:
        update_job(job.job_id, JobStatus.FAILED, error=f"{type(e).__name__}: {e}")
        logger.warning("[JobRunner] %s 실패 — job_id=%s... error=%s", job_type, job.job_id[:8], e)
        raise
