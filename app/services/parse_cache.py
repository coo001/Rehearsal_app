"""파싱 결과 캐시 I/O.

키 형식: MD5(prompt_hash:content_hash)
캐시 파일: data/parse_cache/{key}.json
"""

import json
from pathlib import Path

CACHE_DIR = Path("data/parse_cache")


def load_cache(key: str) -> dict | None:
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def save_cache(key: str, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{key}.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
