"""Job 상태 모델.

parse-script / parse-pdf / generate-rehearsal 같은 장기 작업의
상태를 추적하기 위한 도메인 모델이다.

현재는 동기 흐름에서 직접 사용하지 않지만,
이후 비동기 전환 시 API 계약의 기반이 된다.
"""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel


class JobStatus(str, Enum):
    """작업 생명주기 상태."""
    PENDING   = "pending"    # 생성됨, 아직 시작 전
    RUNNING   = "running"    # 처리 중
    SUCCEEDED = "succeeded"  # 완료 (result 있음)
    FAILED    = "failed"     # 실패 (error 있음)


class Job(BaseModel):
    """단일 장기 작업의 메타데이터."""
    job_id:     str
    job_type:   str                      # "parse_script" | "parse_pdf" | "generate_rehearsal"
    status:     JobStatus
    created_at: str                      # ISO 8601 UTC
    updated_at: str
    session_id: Optional[str] = None     # 연관 세션 (없을 수 있음)
    result:     Optional[dict[str, Any]] = None  # 성공 시 결과 payload
    error:      Optional[str] = None     # 실패 시 오류 메시지
