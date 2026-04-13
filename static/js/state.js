// ── 전역 상태 ──────────────────────────────────────────────
const appState = {
  parsedScript:        null,   // { title, characters, character_descriptions, lines }
  userCharacter:       null,
  voiceAssignments:    {},
  availableVoices:     [],
  sessionId:           null,
  audioMap:            {},
  currentLineIndex:    0,
  rehearsalStartIdx:   0,      // inclusive, 0-based index into parsedScript.lines
  rehearsalEndIdx:     null,   // inclusive, 0-based; null = last line
  scopeMode:           'full', // 'full' | 'range'
  autoAdvance:         false,
  currentAudio:        null,
  scriptVisibilityMode:'show_all', // 'show_all' | 'hide_my_lines' | 'hide_all_lines'
  pendingPdfFile:      null,   // PDF 업로드됐지만 아직 분석 안 된 파일
};
let countdownTimer = null;    // 자동 진행 타이머

// ── 마이크 음성 감지 상태 ──────────────────────────────────
let micStream = null;
let audioCtx = null;
let analyserNode = null;
let listeningActive = false;
let speechDetected = false;
let silenceTimer = null;
let speechStartTime = 0;

const SPEECH_THRESHOLD = 0.015;  // RMS 진폭 임계값 (0.0–1.0)
const SILENCE_DURATION = 1800;   // 발화 종료 후 침묵 대기 시간 (ms) — 연기 특성상 여유 있게
const MIN_SPEECH_MS    = 500;    // 최소 발화 지속 시간 (ms, 짧은 노이즈 무시)
const MAX_LISTEN_MS    = 30000;  // 최대 대기 시간 (30초 후 자동 진행)

// ── 오디오 재생 정규화 설정 ────────────────────────────────
const AUDIO_TARGET_PEAK = 0.85;  // 정규화 목표 peak (0.0–1.0)
const AUDIO_MAX_GAIN    = 3.5;   // 최대 gain 배율 — 너무 조용한 파일 과증폭 방지
let _playbackCtx = null;         // 재생 전용 AudioContext (마이크용 audioCtx와 분리)

// ── canonical / scoped subset helpers ──────────────────────
function getScopeEnd() {
  return appState.rehearsalEndIdx ?? (appState.parsedScript ? appState.parsedScript.lines.length - 1 : 0);
}

function getCanonicalLines() {
  return appState.parsedScript?.lines || [];
}

function getScopedBounds() {
  return { start: appState.rehearsalStartIdx, end: getScopeEnd() };
}

function getScopedLines() {
  const { start, end } = getScopedBounds();
  return getCanonicalLines().slice(start, end + 1);
}

function isInScope(index) {
  const { start, end } = getScopedBounds();
  return index >= start && index <= end;
}

function shouldMaskLine(line, mode, userChar) {
  if (line.type === 'direction') return false;
  if (mode === 'hide_all_lines') return true;
  if (mode === 'hide_my_lines') return userChar && line.character === userChar;
  return false;
}

// ── 상태 초기화 helpers ─────────────────────────────────────
// 재생 중인 오디오/타이머 정지 (인덱스 변경 없음)
function _stopPlayback() {
  clearCountdown();
  stopListening();
  if (appState.currentAudio) { appState.currentAudio.pause(); appState.currentAudio = null; setAudioStatus(false, ''); }
}

// 재생 전체 초기화: 정지 + 위치를 범위 시작점으로 리셋
function resetPlaybackState() {
  _stopPlayback();
  appState.currentLineIndex = appState.rehearsalStartIdx;
}

// 자동 진행 UI 리셋 (autoAdvance 끄기 + 버튼 원복)
function _resetAutoAdvanceUI() {
  appState.autoAdvance = false;
  const btn = document.getElementById('auto-advance-toggle');
  if (btn) { btn.textContent = '⏸ 수동 진행'; btn.style.borderColor = ''; btn.style.color = ''; }
}

// 새 대본 로드 시 전체 초기화 — script-level 제외 모두 무효화
// parsedScript는 호출 측이 직접 설정
function resetSessionStateForNewScript() {
  _stopPlayback();
  appState.userCharacter    = null;
  appState.voiceAssignments = {};
  appState.audioMap         = {};
  appState.sessionId        = null;
  appState.rehearsalStartIdx = 0;
  appState.rehearsalEndIdx   = null;
  appState.currentLineIndex  = 0;
}

// 세션 복원 데이터를 상태 변수에 일괄 적용
function _applySessionData(data) {
  appState.parsedScript      = data.parsed_script;
  appState.voiceAssignments  = data.voice_assignments || {};
  appState.sessionId         = data.session_id;
  appState.audioMap          = data.audio_map || {};
  appState.userCharacter     = data.user_character || null;
  appState.rehearsalStartIdx = data.rehearsal_start_idx ?? 0;
  appState.rehearsalEndIdx   = data.rehearsal_end_idx ?? null;
}
