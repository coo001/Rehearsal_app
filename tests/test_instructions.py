"""Tests for TTS instruction builder pure functions.

외부 의존 없음 — 순수 문자열 변환이므로 mock 불필요.
회귀 위험: intensity threshold, hesitation cue 경계, 빈 필드 처리.
"""

from app.utils.instructions import (
    _hesitation_cue,
    build_elevenlabs_prompt,
    build_tts_instructions,
)


class TestHesitationCue:
    def test_none_returns_empty(self):
        assert _hesitation_cue(None) == ""

    def test_below_500ms_returns_empty(self):
        assert _hesitation_cue(0) == ""
        assert _hesitation_cue(499) == ""

    def test_500ms_returns_short_cue(self):
        assert _hesitation_cue(500) != ""
        assert "짧게" in _hesitation_cue(500)

    def test_900ms_returns_long_cue(self):
        cue = _hesitation_cue(900)
        assert "한 박" in cue

    def test_boundary_899ms_is_short(self):
        assert _hesitation_cue(899) == _hesitation_cue(500)

    def test_boundary_900ms_is_long(self):
        assert _hesitation_cue(900) == _hesitation_cue(1500)


class TestBuildTtsInstructions:
    def test_always_contains_anchor(self):
        result = build_tts_instructions(char_desc=None)
        assert "상대를 보며" in result

    def test_beat_goal_included_when_provided(self):
        result = build_tts_instructions(char_desc=None, beat_goal="설득")
        assert "설득" in result

    def test_subtext_included_when_provided(self):
        result = build_tts_instructions(char_desc=None, subtext="두렵다")
        assert "두렵다" in result

    def test_emotion_suppressed_below_intensity_3(self):
        result = build_tts_instructions(
            char_desc=None, emotion_label="분노", intensity=2
        )
        assert "분노" not in result

    def test_emotion_included_at_intensity_3(self):
        result = build_tts_instructions(
            char_desc=None, emotion_label="분노", intensity=3
        )
        assert "분노" in result

    def test_emotion_included_at_intensity_5(self):
        result = build_tts_instructions(
            char_desc=None, emotion_label="슬픔", intensity=5
        )
        assert "폭발적인" in result
        assert "슬픔" in result

    def test_default_tempo_omitted(self):
        result = build_tts_instructions(char_desc=None, tempo="보통")
        assert "보통" not in result

    def test_non_default_tempo_included(self):
        result = build_tts_instructions(char_desc=None, tempo="느리게")
        assert "느리게" in result

    def test_char_desc_not_in_output(self):
        # char_desc는 analytical → TTS 기계적 읽기 유발로 제거됨
        result = build_tts_instructions(char_desc="매우 차분한 캐릭터")
        assert "매우 차분한 캐릭터" not in result

    def test_all_none_returns_single_line(self):
        result = build_tts_instructions(char_desc=None)
        assert "\n" not in result


class TestBuildElevenLabsPrompt:
    def test_always_contains_anchor(self):
        result = build_elevenlabs_prompt()
        assert "상대에게 직접" in result

    def test_hesitation_cue_injected_above_500ms(self):
        result = build_elevenlabs_prompt(next_cue_delay_ms=600)
        assert "짧게" in result

    def test_no_hesitation_cue_below_500ms(self):
        result = build_elevenlabs_prompt(next_cue_delay_ms=100)
        assert "짧게" not in result
        assert "한 박" not in result

    def test_char_desc_included_when_provided(self):
        result = build_elevenlabs_prompt(char_desc="냉정한 변호사")
        assert "냉정한 변호사" in result

    def test_emotion_suppressed_at_intensity_2(self):
        result = build_elevenlabs_prompt(emotion_label="공포", intensity=2)
        assert "공포" not in result

    def test_emotion_included_at_intensity_4(self):
        result = build_elevenlabs_prompt(emotion_label="공포", intensity=4)
        assert "강한" in result
        assert "공포" in result

    def test_speech_act_triggers_new_mode(self):
        result = build_elevenlabs_prompt(speech_act="명령하듯")
        assert "명령하듯" in result

    def test_tts_direction_fallback_when_no_new_fields(self):
        result = build_elevenlabs_prompt(tts_direction="천천히, 또렷하게")
        assert "천천히, 또렷하게" in result

    def test_tts_direction_skipped_when_new_fields_present(self):
        # speech_act 있으면 tts_direction은 무시된다
        result = build_elevenlabs_prompt(
            speech_act="명령하듯", tts_direction="천천히, 또렷하게"
        )
        assert "천천히, 또렷하게" not in result

    def test_listener_pressure_only_known_values_included(self):
        result_valid = build_elevenlabs_prompt(
            speech_act="요구", listener_pressure="강함"
        )
        assert "강함" in result_valid

        result_invalid = build_elevenlabs_prompt(
            speech_act="요구", listener_pressure="모름"
        )
        assert "모름" not in result_invalid

    def test_avoid_field_prefixed(self):
        result = build_elevenlabs_prompt(speech_act="설득", avoid="울먹임")
        assert "금지" in result
        assert "울먹임" in result

    def test_ending_shape_prefixed(self):
        result = build_elevenlabs_prompt(speech_act="설득", ending_shape="올림")
        assert "끝:" in result
        assert "올림" in result
