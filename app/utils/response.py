import json

from fastapi.responses import Response


def json_response(data) -> Response:
    """한국어 포함 JSON을 bytes로 직렬화해 반환.

    FastAPI/Starlette의 JSONResponse는 str 길이로 Content-Length를 계산해
    한국어(1자 = 3바이트)에서 불일치가 발생한다. bytes를 직접 넘기면 정확하다.
    """
    body: bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return Response(content=body, media_type="application/json")
