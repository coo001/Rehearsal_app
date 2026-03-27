"""POST /api/parse-script — GPT-4o 대본 파싱.
   POST /api/extract-pdf  — PDF 파일에서 텍스트 추출.
"""

import io
import json
import re
import time

from fastapi import APIRouter, File, HTTPException, UploadFile
from pypdf import PdfReader

from app.schemas.requests import ParseScriptRequest
from app.services.script_parser import parse_script, parse_script_pdf, PDFTruncationError
from app.utils.response import json_response

router = APIRouter()


def _preprocess_pdf_text(text: str) -> str:
    """PDF에서 추출한 텍스트의 흔한 노이즈를 제거한다.

    - 3줄 이상 연속 빈 줄 → 2줄로 축소
    - 단독 페이지 번호 줄(숫자만 있는 줄) 제거
    """
    # 단독 숫자 줄(페이지 번호) 제거 — 앞뒤가 빈 줄인 경우만 제거해 오탐 방지
    text = re.sub(r'(?m)(?<=\n)\n\s*\d{1,3}\s*\n(?=\n)', '\n\n', text)
    # 3줄 이상 빈 줄 → 2줄
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def repair_pdf_text(text: str) -> str:
    """PDF layout 추출 후 남은 '번 한글+숫자' 순서 깨짐 보정.

    layout 모드로 대부분의 reading order가 복원되지만,
    폰트 인코딩 문제로 남는 패턴을 처리한다.

    예: '번 배심원8'        → '8번 배심원'
        '번 배심원장1 ( )' → '1번 배심원장 ( )'
    """
    def fix_line(line: str) -> str:
        # '번 KOREAN_TEXT + NUMBER [tail]' 형태만 보정
        m = re.match(r'^번\s+(.+?)(\d{1,2})(.*)', line)
        if m:
            body = m.group(1).rstrip()
            num = m.group(2)
            tail = m.group(3)
            return f"{num}번 {body}{tail}"
        return line

    return "\n".join(fix_line(l) for l in text.split("\n"))


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


MAX_PDF_PAGES = 150  # 이 이상은 추출이 과도하게 느려질 수 있음
PDF_DIRECT_MAX_PAGES = 40  # 이 이하: Responses API direct parse / 초과: text extraction + chunked parse
# direct parse는 PDF를 시각적으로 직접 읽어 한국어 인코딩 문제 없음
# max_output_tokens=65_536 기준 ~1,600줄 처리 가능 → 40페이지 이하 안전
# pypdf text extraction은 한국어 극본에서 불완전한 경우가 많아 fallback으로만 사용


@router.post("/parse-pdf")
async def parse_pdf_direct(file: UploadFile = File(...)):
    """PDF를 GPT-4o에 직접 전달해 대본을 파싱한다.

    50페이지 이하: Files API direct parse (reading order 깨짐 회피)
    50페이지 초과: text extraction + 청크 파싱 fallback
    """
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
                f"{MAX_PDF_PAGES}페이지 이하로 나눠 업로드해주세요."
            )

        if total_pages > PDF_DIRECT_MAX_PAGES:
            # Fallback: text extraction + 청크 파싱 (기존 경로)
            print(f"[parse-pdf] {total_pages}페이지 > {PDF_DIRECT_MAX_PAGES} → text fallback")
            pages: list[str] = []
            for i, page in enumerate(reader.pages):
                try:
                    pages.append(page.extract_text(extraction_mode="layout") or "")
                except Exception as e:
                    print(f"[PDF] 페이지 {i+1} 추출 실패 (skip): {e}")
                    pages.append("")
            full_text = "\n\n".join(p.strip() for p in pages if p.strip())
            if not full_text:
                raise HTTPException(422, "PDF에서 텍스트를 추출할 수 없습니다.")
            full_text = _preprocess_pdf_text(full_text)
            full_text = repair_pdf_text(full_text)
            data = parse_script(full_text)
        else:
            try:
                data = parse_script_pdf(content, file.filename or "script.pdf", total_pages)
            except PDFTruncationError as e:
                # direct parse 결과 잘림 → text extraction + chunked parse fallback
                print(f"[parse-pdf] {e}")
                print(f"[parse-pdf] text extraction fallback 시도 중...")
                pages_fb: list[str] = []
                for i, page in enumerate(reader.pages):
                    try:
                        pages_fb.append(page.extract_text(extraction_mode="layout") or "")
                    except Exception:
                        pages_fb.append("")
                full_text_fb = "\n\n".join(p.strip() for p in pages_fb if p.strip())
                if not full_text_fb:
                    raise HTTPException(422, "PDF direct parse가 잘렸고 텍스트 추출도 실패했습니다. 대본을 나눠 업로드해주세요.")
                full_text_fb = _preprocess_pdf_text(full_text_fb)
                full_text_fb = repair_pdf_text(full_text_fb)
                data = parse_script(full_text_fb)

        return json_response(data)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        raise HTTPException(500, f"PDF 파싱 실패 (LLM JSON 오류): {e}")
    except Exception as e:
        raise HTTPException(500, f"PDF 파싱 중 오류 ({type(e).__name__}): {e}")


@router.post("/extract-pdf")
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
                f"{MAX_PDF_PAGES}페이지 이하로 나눠 업로드해주세요."
            )

        print(f"[PDF] 추출 시작 - {total_pages}페이지")
        t_total = time.time()

        pages: list[str] = []
        skipped: list[int] = []
        for i, page in enumerate(reader.pages):
            t_page = time.time()
            try:
                text = page.extract_text(extraction_mode="layout") or ""
                elapsed = time.time() - t_page
                if elapsed > 3.0:
                    print(f"[PDF] 페이지 {i + 1}/{total_pages} 느림 ({elapsed:.1f}s)")
                pages.append(text)
            except Exception as e:
                print(f"[PDF] 페이지 {i + 1}/{total_pages} 추출 실패 (skip): {e}")
                skipped.append(i + 1)
                pages.append("")

        full_text = "\n\n".join(p.strip() for p in pages if p.strip())

        if not full_text:
            raise HTTPException(
                422,
                "PDF에서 텍스트를 추출할 수 없습니다. "
                "스캔 이미지 PDF이거나 텍스트가 없는 파일입니다."
            )

        full_text = _preprocess_pdf_text(full_text)
        full_text = repair_pdf_text(full_text)

        total_elapsed = time.time() - t_total
        skip_info = f", 실패 skip {len(skipped)}페이지" if skipped else ""
        print(
            f"[PDF] 추출 완료 - {total_pages}페이지{skip_info}, "
            f"{len(full_text)}자, {total_elapsed:.1f}s"
        )

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
