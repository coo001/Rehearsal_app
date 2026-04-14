"""공통 로깅 설정.

setup_logging() 을 앱 시작 시 한 번만 호출한다.
각 모듈은 logging.getLogger(__name__) 으로 자체 로거를 생성한다.
"""

import logging
import os


def setup_logging() -> None:
    """루트 로거가 아직 설정되지 않았으면 기본 포맷으로 초기화한다.

    uvicorn이 먼저 핸들러를 등록한 경우에는 basicConfig가 무시되므로
    uvicorn의 포맷이 그대로 유지된다.
    """
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(levelname)s %(name)s: %(message)s",
        )

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    # 앱 전용 로거 레벨 설정 (하위 모듈 app.* 모두 적용)
    logging.getLogger("app").setLevel(level)

    # 외부 라이브러리 불필요한 DEBUG 억제
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
