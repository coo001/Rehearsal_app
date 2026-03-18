"""POST /api/parse-script — GPT-4o 대본 파싱.
   POST /api/extract-pdf  — PDF 파일에서 텍스트 추출.
"""

import io
import json
import re

from fastapi import APIRouter, File, HTTPException, UploadFile
from pypdf import PdfReader

from app.schemas.requests import ParseScriptRequest
from app.services.script_parser import parse_script
from app.utils.response import json_response

router = APIRouter()


def _preprocess_pdf_text(text: str) -> str:
    """PDF에서 추출한 텍스트의 흔한 노이즈를 제거한다.

    - 3줄 이상 연속 빈 줄 → 2줄로 축소
    - 단독 페이지 번호 줄(숫자만 있는 줄) 제거
    """
    # 단독 숫자 줄(페이지 번호) 제거
    text = re.sub(r'(?m)^\s*\d{1,3}\s*$', '', text)
    # 3줄 이상 빈 줄 → 2줄
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


@router.post("/parse-script")
async def parse_script_endpoint(req: ParseScriptRequest):
    if not req.script.strip():
        raise HTTPException(400, "대본 내용을 입력해주세요.")

    input_chars = len(req.script)
    print(f"[Route] /parse-script 호출 - 입력: {input_chars}자")

    try:
        data = parse_script(req.script)
        return json_response(data)
    except json.JSONDecodeError as e:
        # 단일 경로에서 LLM 응답이 잘린 경우 (finish_reason='length' 가능성 높음)
        # 서버 로그에서 [Parser] 원문을 확인할 것
        raise HTTPException(
            500,
            f"대본 파싱 실패 (LLM 응답 JSON 오류). "
            f"입력 {input_chars}자 - 서버 로그에서 LLM 원문을 확인하세요. 오류: {e}"
        )
    except RuntimeError as e:
        # 청크 파싱 실패 또는 병합 실패 — 어느 청크인지 메시지에 포함됨
        raise HTTPException(500, f"대본 파싱 중 오류: {e}")
    except Exception as e:
        raise HTTPException(500, f"대본 파싱 중 오류 ({type(e).__name__}): {e}")


@router.post("/extract-pdf")
async def extract_pdf(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "PDF 파일만 지원합니다.")
    try:
        content = await file.read()
        reader = PdfReader(io.BytesIO(content))
        pages = [page.extract_text() or "" for page in reader.pages]
        full_text = "\n\n".join(p.strip() for p in pages if p.strip())

        if not full_text:
            raise HTTPException(
                422,
                "PDF에서 텍스트를 추출할 수 없습니다. "
                "스캔 이미지 PDF이거나 텍스트가 없는 파일입니다."
            )

        full_text = _preprocess_pdf_text(full_text)
        print(f"[PDF] 추출 완료 - {len(reader.pages)}페이지, {len(full_text)}자")

        return json_response({
            "text": full_text,
            "char_count": len(full_text),
            "total_pages": len(reader.pages),
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"PDF 처리 실패: {e}")
