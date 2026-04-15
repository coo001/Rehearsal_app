"""POST /api/parse-script — GPT-4o 대본 파싱.
   POST /api/parse-pdf    — PDF 직접 파싱.
   POST /api/extract-pdf  — PDF 파일에서 텍스트 추출.
"""

import io
import json
import logging
import re
import time

from fastapi import APIRouter, File, HTTPException, UploadFile

logger = logging.getLogger(__name__)
from pypdf import PdfReader

from app.schemas.requests import ParseScriptRequest
from app.schemas.responses import ExtractPdfResponse, ParsedScriptResponse
from app.services.job_runner import run_job
from app.services.script_parser import parse_script, parse_script_pdf, PDFTruncationError
from app.utils.response import json_response

router = APIRouter()


# ── PDF 텍스트 전처리 헬퍼 ────────────────────────────────────────

def _preprocess_pdf_text(text: str) -> str:
    """PDF에서 추출한 텍스트의 흔한 노이즈를 제거한다."""
    text = re.sub(r'(?m)(?<=\n)\n\s*\d{1,3}\s*\n(?=\n)', '\n\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def repair_pdf_text(text: str) -> str:
    """PDF layout 추출 후 남은 '번 한글+숫자' 순서 깨짐 보정."""
    def fix_line(line: str) -> str:
        m = re.match(r'^번\s+(.+?)(\d{1,2})(.*)', line)
        if m:
            return f"{m.group(2)}번 {m.group(1).rstrip()}{m.group(3)}"
        return line
    return "\n".join(fix_line(l) for l in text.split("\n"))


def _extract_pages(reader: PdfReader) -> tuple[list[str], list[int]]:
    """PdfReader에서 페이지별 텍스트를 추출한다. (text, skipped_pages) 반환."""
    pages: list[str] = []
    skipped: list[int] = []
    for i, page in enumerate(reader.pages):
        try:
            pages.append(page.extract_text(extraction_mode="layout") or "")
        except Exception as e:
            logger.warning("[PDF] 페이지 %d 추출 실패 (skip): %s", i + 1, e)
            skipped.append(i + 1)
            pages.append("")
    return pages, skipped


def _pages_to_text(pages: list[str]) -> str:
    return "\n\n".join(p.strip() for p in pages if p.strip())


def _script_summary(d: dict) -> dict:
    return {
        "title": d.get("title"),
        "characters": len(d.get("characters") or []),
        "lines": len(d.get("lines") or []),
    }


# ── 상수 ─────────────────────────────────────────────────────────

MAX_PDF_PAGES = 150
PDF_DIRECT_MAX_PAGES = 40


# ── 엔드포인트 ────────────────────────────────────────────────────

@router.post("/parse-script", response_model=ParsedScriptResponse)
async def parse_script_endpoint(req: ParseScriptRequest):
    if not req.script.strip():
        raise HTTPException(400, "대본 내용을 입력해주세요.")

    input_chars = len(req.script)
    logger.info("[Route] /parse-script 호출 - 입력: %d자", input_chars)

    try:
        _, data = run_job(
            "parse_script",
            lambda: parse_script(req.script),
            result_summary=lambda d: {**_script_summary(d), "input_chars": input_chars},
        )
        return json_response(data)
    except json.JSONDecodeError as e:
        raise HTTPException(
            500,
            f"대본 파싱 실패 (LLM 응답 JSON 오류). "
            f"입력 {input_chars}자 - 서버 로그에서 LLM 원문을 확인하세요. 오류: {e}",
        )
    except RuntimeError as e:
        raise HTTPException(500, f"대본 파싱 중 오류: {e}")
    except Exception as e:
        raise HTTPException(500, f"대본 파싱 중 오류 ({type(e).__name__}): {e}")


@router.post("/parse-pdf", response_model=ParsedScriptResponse)
async def parse_pdf_direct(file: UploadFile = File(...)):
    """PDF를 GPT-4o에 직접 전달해 대본을 파싱한다.

    PDF_DIRECT_MAX_PAGES 이하: Files API direct parse (reading order 깨짐 회피)
    초과: text extraction + 청크 파싱 fallback
    """
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "PDF 파일만 지원합니다.")

    content = await file.read()
    reader = PdfReader(io.BytesIO(content))
    total_pages = len(reader.pages)

    if total_pages > MAX_PDF_PAGES:
        raise HTTPException(
            422,
            f"PDF 페이지 수가 너무 많습니다 ({total_pages}페이지). "
            f"{MAX_PDF_PAGES}페이지 이하로 나눠 업로드해주세요.",
        )

    def _parse() -> dict:
        """full parse 로직 (direct → fallback 포함). run_job에 넘기는 단위."""
        if total_pages > PDF_DIRECT_MAX_PAGES:
            logger.info("[parse-pdf] %d페이지 > %d → text fallback", total_pages, PDF_DIRECT_MAX_PAGES)
            pages, _ = _extract_pages(reader)
            full_text = _pages_to_text(pages)
            if not full_text:
                raise HTTPException(422, "PDF에서 텍스트를 추출할 수 없습니다.")
            full_text = repair_pdf_text(_preprocess_pdf_text(full_text))
            logger.info("[parse-pdf] 추출 텍스트: %d자, 성공 페이지: %d/%d",
                        len(full_text), sum(1 for p in pages if p.strip()), total_pages)
            return parse_script(full_text)

        try:
            return parse_script_pdf(content, file.filename or "script.pdf", total_pages)
        except PDFTruncationError as e:
            logger.warning("[parse-pdf] direct parse 실패: %s → text fallback", e)
            pages_fb, _ = _extract_pages(reader)
            full_text_fb = _pages_to_text(pages_fb)
            if not full_text_fb:
                raise HTTPException(422, "PDF direct parse가 잘렸고 텍스트 추출도 실패했습니다.")
            full_text_fb = repair_pdf_text(_preprocess_pdf_text(full_text_fb))
            logger.info("[parse-pdf] fallback 추출 텍스트: %d자, 성공 페이지: %d/%d",
                        len(full_text_fb), sum(1 for p in pages_fb if p.strip()), total_pages)
            return parse_script(full_text_fb)

    try:
        _, data = run_job(
            "parse_pdf",
            _parse,
            result_summary=lambda d: {**_script_summary(d), "total_pages": total_pages},
        )
        return json_response(data)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        logger.warning("[parse-pdf] LLM JSON 파싱 실패: %s", e)
        raise HTTPException(500, f"PDF 파싱 실패 (LLM JSON 오류): {e}")
    except Exception as e:
        logger.warning("[parse-pdf] 예외 발생 (%s): %s", type(e).__name__, e)
        raise HTTPException(500, f"PDF 파싱 중 오류 ({type(e).__name__}): {e}")


@router.post("/extract-pdf", response_model=ExtractPdfResponse)
async def extract_pdf(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "PDF 파일만 지원합니다.")
    try:
        content = await file.read()
        reader = PdfReader(io.BytesIO(content))
        total_pages = len(reader.pages)

        if total_pages > MAX_PDF_PAGES:
            raise HTTPException(
                422,
                f"PDF 페이지 수가 너무 많습니다 ({total_pages}페이지). "
                f"{MAX_PDF_PAGES}페이지 이하로 나눠 업로드해주세요.",
            )

        logger.info("[PDF] 추출 시작 - %d페이지", total_pages)
        t_total = time.time()

        pages, skipped = _extract_pages(reader)
        # 느린 페이지 개별 로깅
        for i, page in enumerate(reader.pages):
            t_page = time.time()
            try:
                page.extract_text(extraction_mode="layout")
                if time.time() - t_page > 3.0:
                    logger.info("[PDF] 페이지 %d/%d 느림 (%.1fs)", i + 1, total_pages, time.time() - t_page)
            except Exception:
                pass

        full_text = _pages_to_text(pages)
        if not full_text:
            raise HTTPException(
                422,
                "PDF에서 텍스트를 추출할 수 없습니다. "
                "스캔 이미지 PDF이거나 텍스트가 없는 파일입니다.",
            )

        full_text = repair_pdf_text(_preprocess_pdf_text(full_text))
        skip_info = f", 실패 skip {len(skipped)}페이지" if skipped else ""
        logger.info("[PDF] 추출 완료 - %d페이지%s, %d자, %.1fs",
                    total_pages, skip_info, len(full_text), time.time() - t_total)

        return json_response({
            "text": full_text,
            "char_count": len(full_text),
            "total_pages": total_pages,
            "skipped_pages": skipped,
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"PDF 처리 실패: {e}")
