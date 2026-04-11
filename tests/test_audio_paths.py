"""Tests for audio_paths cache key correctness.

핵심 회귀 위험: content_hash()가 text만 해싱하면
동일 텍스트지만 다른 instructions/voice_id가 같은 파일을 반환한다.
"""
import hashlib

from app.utils.audio_paths import content_hash, rehearsal_audio_path, slugify


class TestContentHash:
    def test_same_inputs_produce_same_hash(self):
        h1 = content_hash("안녕하세요", "지시문A", "voice1")
        h2 = content_hash("안녕하세요", "지시문A", "voice1")
        assert h1 == h2

    def test_different_instructions_produce_different_hash(self):
        h1 = content_hash("안녕하세요", "instructions_A", "voice1")
        h2 = content_hash("안녕하세요", "instructions_B", "voice1")
        assert h1 != h2

    def test_different_voice_id_produces_different_hash(self):
        h1 = content_hash("안녕하세요", "same_instructions", "voice1")
        h2 = content_hash("안녕하세요", "same_instructions", "voice2")
        assert h1 != h2

    def test_different_text_produces_different_hash(self):
        h1 = content_hash("안녕하세요", "instr", "v1")
        h2 = content_hash("잘 가세요", "instr", "v1")
        assert h1 != h2

    def test_empty_optional_fields_are_stable(self):
        # 기본값 호출은 항상 동일한 결과를 내야 한다
        h1 = content_hash("text")
        h2 = content_hash("text", "", "")
        assert h1 == h2

    def test_hash_length_is_six(self):
        h = content_hash("text", "instr", "voice")
        assert len(h) == 6

    def test_field_boundary_collision(self):
        # "ab"|"cd" vs "a"|"bcd" — | 구분자 덕분에 달라야 한다
        h1 = content_hash("ab", "cd", "")
        h2 = content_hash("a", "bcd", "")
        assert h1 != h2


class TestRehearsalAudioPath:
    def test_path_includes_session_and_idx(self, tmp_path, monkeypatch):
        import app.utils.audio_paths as ap
        monkeypatch.setattr(ap, "AUDIO_DIR", tmp_path)
        path = rehearsal_audio_path("ses123", 7, "민수", "대사", "instr", "v1")
        assert "ses123" in str(path)
        assert "007_" in path.name

    def test_same_text_different_instructions_different_path(self, tmp_path, monkeypatch):
        import app.utils.audio_paths as ap
        monkeypatch.setattr(ap, "AUDIO_DIR", tmp_path)
        p1 = rehearsal_audio_path("ses", 0, "민수", "대사", "instrA", "v1")
        p2 = rehearsal_audio_path("ses", 0, "민수", "대사", "instrB", "v1")
        assert p1 != p2

    def test_same_inputs_same_path(self, tmp_path, monkeypatch):
        import app.utils.audio_paths as ap
        monkeypatch.setattr(ap, "AUDIO_DIR", tmp_path)
        p1 = rehearsal_audio_path("ses", 0, "민수", "대사", "instr", "v1")
        p2 = rehearsal_audio_path("ses", 0, "민수", "대사", "instr", "v1")
        assert p1 == p2


class TestSlugify:
    def test_removes_path_separators(self):
        assert "/" not in slugify("a/b")
        assert "\\" not in slugify("a\\b")

    def test_spaces_become_underscores(self):
        assert slugify("Kim Jun") == "Kim_Jun"

    def test_truncates_to_max_len(self):
        assert len(slugify("A" * 100)) <= 16

    def test_empty_name_falls_back(self):
        assert slugify("") == "char"
        assert slugify("   ") == "char"
