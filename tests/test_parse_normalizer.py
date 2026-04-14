"""Tests for parse_normalizer pure functions.

normalize_script_text / _split_into_chunks / _strip_json_fences /
canonicalize_character_name / build_alias_map / remap_result
"""

import pytest

from app.services.parse_normalizer import (
    _split_into_chunks,
    _strip_json_fences,
    build_alias_map,
    canonicalize_character_name,
    normalize_script_text,
    remap_result,
)


# ── normalize_script_text ────────────────────────────────────────


class TestNormalizeScriptText:
    def test_crlf_converted_to_lf(self):
        assert normalize_script_text("a\r\nb") == "a\nb"

    def test_cr_only_converted_to_lf(self):
        assert normalize_script_text("a\rb") == "a\nb"

    def test_trailing_whitespace_stripped_per_line(self):
        result = normalize_script_text("hello   \nworld  ")
        assert result == "hello\nworld"

    def test_three_blank_lines_collapsed(self):
        # impl keeps up to 2 blank lines; 4+ blank lines → 2 blank lines
        result = normalize_script_text("a\n\n\n\n\nb")  # 4 blank lines between a and b
        assert "\n\n\n\n" not in result   # no 3+ consecutive blank lines remain

    def test_two_blank_lines_preserved(self):
        result = normalize_script_text("a\n\nb")
        assert result == "a\n\nb"

    def test_leading_trailing_whitespace_stripped(self):
        result = normalize_script_text("  \n\nhello\n\n  ")
        assert result == "hello"

    def test_empty_string(self):
        assert normalize_script_text("") == ""

    def test_single_line_unchanged(self):
        assert normalize_script_text("안녕하세요") == "안녕하세요"

    def test_mixed_crlf_and_cr(self):
        result = normalize_script_text("a\r\nb\rc\nd")
        assert "\r" not in result
        assert result == "a\nb\nc\nd"


# ── _strip_json_fences ────────────────────────────────────────────


class TestStripJsonFences:
    def test_plain_dict_unchanged(self):
        raw = '{"key": "val"}'
        assert _strip_json_fences(raw) == raw

    def test_removes_json_fence(self):
        raw = "```json\n{\"key\": \"val\"}\n```"
        assert _strip_json_fences(raw) == '{"key": "val"}'

    def test_removes_plain_fence(self):
        raw = "```\n{\"key\": \"val\"}\n```"
        assert _strip_json_fences(raw) == '{"key": "val"}'

    def test_removes_prefix_text(self):
        raw = "Here is the result:\n{\"key\": \"val\"}"
        assert _strip_json_fences(raw) == '{"key": "val"}'

    def test_removes_suffix_text(self):
        raw = '{"key": "val"}\nDone.'
        assert _strip_json_fences(raw) == '{"key": "val"}'


# ── _split_into_chunks ────────────────────────────────────────────


class TestSplitIntoChunks:
    def test_short_text_single_chunk(self):
        text = "짧은 대본\n\n두 번째 블록"
        chunks = _split_into_chunks(text, max_chars=1000)
        assert len(chunks) == 1

    def test_long_text_splits_multiple_chunks(self):
        blocks = ["블록 {}\n".format(i) + "가" * 200 for i in range(20)]
        text = "\n\n".join(blocks)
        chunks = _split_into_chunks(text, max_chars=500)
        assert len(chunks) > 1

    def test_all_content_preserved(self):
        blocks = ["블록{}".format(i) for i in range(50)]
        text = "\n\n".join(blocks)
        chunks = _split_into_chunks(text, max_chars=100)
        rejoined = "\n\n".join(chunks)
        for b in blocks:
            assert b in rejoined

    def test_single_large_block_no_newlines(self):
        # No double-newlines → single block larger than max_chars
        # Should fall back to line-level splitting or return as-is without crashing
        text = "가" * 5000
        chunks = _split_into_chunks(text, max_chars=1000)
        assert len(chunks) >= 1
        assert all(len(c) > 0 for c in chunks)

    def test_empty_text_returns_list(self):
        chunks = _split_into_chunks("", max_chars=1000)
        assert isinstance(chunks, list)
        assert len(chunks) >= 1

    def test_chunk_boundaries_do_not_split_blocks(self):
        # Blocks should not be cut in the middle
        blocks = ["A" * 100 for _ in range(10)]
        text = "\n\n".join(blocks)
        chunks = _split_into_chunks(text, max_chars=250)
        for chunk in chunks:
            # Each chunk is a join of whole blocks — no block should be split
            for part in chunk.split("\n\n"):
                assert len(part) == 100 or len(part) == 0


# ── canonicalize_character_name ───────────────────────────────────


class TestCanonicalizeCharacterName:
    def test_strips_leading_trailing_spaces(self):
        assert canonicalize_character_name("  홍길동  ") == "홍길동"

    def test_collapses_internal_whitespace(self):
        assert canonicalize_character_name("홍  길동") == "홍 길동"

    def test_removes_leading_번_noise(self):
        assert canonicalize_character_name("번 배심원8") == "배심원8"

    def test_removes_번_with_number_suffix(self):
        assert canonicalize_character_name("번 배심원장1") == "배심원장1"

    def test_no_change_for_clean_name(self):
        assert canonicalize_character_name("배심원8") == "배심원8"

    def test_empty_string(self):
        assert canonicalize_character_name("") == ""

    def test_번_not_removed_mid_name(self):
        # Only leading '번 ' should be stripped
        name = "홍길동번"
        assert canonicalize_character_name(name) == "홍길동번"


# ── build_alias_map ───────────────────────────────────────────────


class TestBuildAliasMap:
    def test_clean_names_map_to_themselves(self):
        alias = build_alias_map(["홍길동", "변학도"])
        assert alias["홍길동"] == "홍길동"
        assert alias["변학도"] == "변학도"

    def test_번_variant_maps_to_first_clean_occurrence(self):
        # "배심원8" appears first; "번 배심원8" canonicalises to same → remapped
        alias = build_alias_map(["배심원8", "번 배심원8"])
        assert alias["번 배심원8"] == "배심원8"

    def test_both_variants_share_canonical(self):
        alias = build_alias_map(["번 배심원8", "배심원8"])
        assert alias["번 배심원8"] == alias["배심원8"]

    def test_unique_names_no_remapping(self):
        alias = build_alias_map(["A", "B", "C"])
        assert alias == {"A": "A", "B": "B", "C": "C"}

    def test_empty_list(self):
        assert build_alias_map([]) == {}


# ── remap_result ──────────────────────────────────────────────────


class TestRemapResult:
    def _base(self):
        return {
            "characters": ["번 배심원8", "판사"],
            "character_descriptions": {"번 배심원8": "묘사", "판사": "권위적"},
            "character_analysis": {"번 배심원8": {"summary": "x"}},
            "relationships": {"번 배심원8 -> 판사": "갈등"},
            "lines": [
                {"character": "번 배심원8", "text": "이의 있습니다"},
                {"character": "판사", "text": "기각"},
            ],
        }

    def test_characters_remapped(self):
        alias = {"번 배심원8": "배심원8", "판사": "판사"}
        result = remap_result(self._base(), alias)
        assert "번 배심원8" not in result["characters"]
        assert "배심원8" in result["characters"]

    def test_descriptions_remapped(self):
        alias = {"번 배심원8": "배심원8", "판사": "판사"}
        result = remap_result(self._base(), alias)
        assert "번 배심원8" not in result["character_descriptions"]
        assert "배심원8" in result["character_descriptions"]

    def test_analysis_remapped(self):
        alias = {"번 배심원8": "배심원8", "판사": "판사"}
        result = remap_result(self._base(), alias)
        assert "번 배심원8" not in result["character_analysis"]
        assert "배심원8" in result["character_analysis"]

    def test_relationships_key_remapped(self):
        alias = {"번 배심원8": "배심원8", "판사": "판사"}
        result = remap_result(self._base(), alias)
        assert "번 배심원8 -> 판사" not in result["relationships"]
        assert "배심원8 -> 판사" in result["relationships"]

    def test_lines_character_remapped(self):
        alias = {"번 배심원8": "배심원8", "판사": "판사"}
        result = remap_result(self._base(), alias)
        chars_in_lines = {line["character"] for line in result["lines"]}
        assert "번 배심원8" not in chars_in_lines

    def test_no_duplicate_characters(self):
        alias = {"번 배심원8": "배심원8", "배심원8": "배심원8", "판사": "판사"}
        result = {
            "characters": ["번 배심원8", "배심원8", "판사"],
            "character_descriptions": {},
            "character_analysis": {},
            "relationships": {},
            "lines": [],
        }
        result = remap_result(result, alias)
        assert result["characters"].count("배심원8") == 1
