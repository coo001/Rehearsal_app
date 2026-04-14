"""Tests for tts_text pure functions.

_parse_hint_rules / format_text_for_elevenlabs
"""

import pytest

from app.services.tts_text import _parse_hint_rules, format_text_for_elevenlabs


# ── _parse_hint_rules ─────────────────────────────────────────────


class TestParseHintRules:
    def test_single_rule(self):
        rules = _parse_hint_rules("2014년 → '이천십사 년'")
        assert rules == [("2014년", "이천십사 년")]

    def test_multiple_rules_slash_separated(self):
        rules = _parse_hint_rules("2014년 → '이천십사 년' / 3% → '삼 퍼센트'")
        assert ("2014년", "이천십사 년") in rules
        assert ("3%", "삼 퍼센트") in rules
        assert len(rules) == 2

    def test_multiple_rules_newline_separated(self):
        rules = _parse_hint_rules("Dr. → '닥터'\nMr. → '미스터'")
        assert ("Dr.", "닥터") in rules
        assert ("Mr.", "미스터") in rules

    def test_strips_trailing_읽기(self):
        rules = _parse_hint_rules("100% → '백 퍼센트로 읽기'")
        assert rules[0][1] == "백 퍼센트"

    def test_strips_trailing_으로(self):
        rules = _parse_hint_rules("X → '엑스로'")
        assert rules[0][1] == "엑스"

    def test_strips_trailing_로(self):
        rules = _parse_hint_rules("km → '킬로미터로'")
        assert rules[0][1] == "킬로미터"

    def test_empty_string_returns_empty(self):
        assert _parse_hint_rules("") == []

    def test_no_arrow_ignored(self):
        assert _parse_hint_rules("그냥 설명") == []

    def test_same_src_dst_excluded(self):
        rules = _parse_hint_rules("abc → 'abc'")
        assert rules == []

    def test_strips_outer_quotes_from_src(self):
        rules = _parse_hint_rules("'2014년' → '이천십사 년'")
        assert rules[0][0] == "2014년"

    def test_handles_no_quotes(self):
        rules = _parse_hint_rules("km → 킬로미터")
        assert ("km", "킬로미터") in rules


# ── format_text_for_elevenlabs ────────────────────────────────────


class TestFormatTextForElevenLabs:
    def test_사이_replaced_with_comma(self):
        result = format_text_for_elevenlabs("잠깐(사이)있어요")
        assert "," in result
        assert "(사이)" not in result

    def test_pause_replaced_with_comma(self):
        result = format_text_for_elevenlabs("wait(pause)here")
        assert "," in result
        assert "(pause)" not in result

    def test_beat_replaced_with_comma(self):
        result = format_text_for_elevenlabs("yes(beat)no")
        assert "(beat)" not in result
        assert "," in result

    def test_잠시_replaced_with_ellipsis(self):
        result = format_text_for_elevenlabs("잠깐(잠시)생각해")
        assert "..." in result
        assert "(잠시)" not in result

    def test_뜸_replaced_with_ellipsis(self):
        result = format_text_for_elevenlabs("그건(뜸)말이야")
        assert "..." in result
        assert "(뜸)" not in result

    def test_멈춤_replaced_with_ellipsis(self):
        result = format_text_for_elevenlabs("아(멈춤)그렇군")
        assert "..." in result
        assert "(멈춤)" not in result

    def test_normalization_hints_applied(self):
        line = {"normalization_hints": "2014년 → '이천십사 년'"}
        result = format_text_for_elevenlabs("2014년 일이야", line)
        assert "이천십사 년" in result
        assert "2014년" not in result

    def test_pronunciation_hints_applied(self):
        line = {"pronunciation_hints": "Dr. → '닥터'"}
        result = format_text_for_elevenlabs("Dr. 스미스", line)
        assert "닥터" in result
        assert "Dr." not in result

    def test_no_line_no_crash(self):
        result = format_text_for_elevenlabs("그냥 평범한 대사")
        assert result == "그냥 평범한 대사"

    def test_double_space_collapsed(self):
        result = format_text_for_elevenlabs("hello   world")
        assert "  " not in result

    def test_empty_hints_no_crash(self):
        line = {"normalization_hints": "", "pronunciation_hints": None}
        result = format_text_for_elevenlabs("안녕", line)
        assert result == "안녕"

    def test_multiple_pause_markers(self):
        result = format_text_for_elevenlabs("가(사이)나(잠시)다")
        assert "(사이)" not in result
        assert "(잠시)" not in result
        assert "," in result
        assert "..." in result
