// ── 샘플 대본 ──────────────────────────────────────────────
const SAMPLES = {
  korean: `[장소: 카페. 테이블에 앉은 지수와 민준]

지수
(커피를 마시며) 어제 그 영화 봤어? 정말 최고였잖아.

민준
아, 나는 아직 못 봤어. 스포 하지 마!

지수
(웃으며) 알았어, 알았어. 그런데 진짜로 꼭 봐야 해.

민준
주말에 같이 볼래? 너 시간 돼?

지수
(잠시 생각하다) 토요일 오후는 괜찮아. 2시 어때?

민준
좋아! 그럼 같은 카페 앞에서 만나자.

[두 사람이 약속을 잡고 커피를 마신다]

지수
근데 요즘 어때? 회사는 좀 나아졌어?

민준
(한숨을 쉬며) 솔직히... 아직 힘들어. 상사가 너무 까다롭거든.

지수
힘내. 네가 할 수 있어.`,
  english: `[Scene: A coffee shop. ALEX and JAMIE are sitting across from each other.]

ALEX
(looking at phone) You're late. Again.

JAMIE
(rushing in) I know, I know! The traffic was insane.

ALEX
It's always something with you, isn't it?

JAMIE
(sitting down) Come on, don't be like that. I brought you your favorite muffin.

ALEX
(softening) ...A blueberry one?

JAMIE
(grinning) Obviously.

[ALEX takes the muffin and smiles despite themselves]

ALEX
Fine. You're forgiven. This time.

JAMIE
So, did you hear about the project? They picked our team!

ALEX
(shocked) Seriously? We actually got it?

JAMIE
I told you we would. You never believe me.

ALEX
(laughing) Okay, okay. You were right. Happy?

JAMIE
Extremely.`
};

function loadSample(lang) {
  document.getElementById('script-input').value = SAMPLES[lang];
  showToast('샘플 대본을 불러왔습니다.', 'success');
}

// ── 1단계: 대본 파싱 ──────────────────────────────────────
function handlePdfUpload(input) {
  const file = input.files[0];
  if (!file) return;
  input.value = '';

  appState.pendingPdfFile = file;
  console.log(`[PDF] 파일 준비됨: ${file.name} (${(file.size / 1024).toFixed(0)}KB)`);

  const status = document.getElementById('pdf-status');
  status.innerHTML = `📄 <strong>${file.name}</strong> — 아래 버튼으로 분석하세요`;
  status.classList.remove('hidden');

  document.getElementById('script-input').value = '';
}

// 상태만 적용 (UI 없음)
function _applyParsedScriptState(data) {
  resetSessionStateForNewScript();
  appState.parsedScript = data;
}

// 캐릭터 렌더 + 목소리 배정 단계로 이동 + toast (text/pdf 공통)
function _renderCharactersPhase(lineCount, source) {
  renderCharacters();
  goToVoices();
  if (lineCount < 10) {
    showToast(`경고: 대사가 ${lineCount}줄만 추출됐습니다. 파싱을 다시 시도해보세요.`, 'warning');
  } else if (appState.parsedScript.partial_failure) {
    const { failed_chunks, recovered_chunks = [], total_chunks } = appState.parsedScript.partial_failure;
    const nChars = appState.parsedScript.characters.length;
    const prefix = source === 'pdf' ? 'PDF 분석 완료 — ' : '';
    if (failed_chunks.length === 0) {
      showToast(`${prefix}${nChars}명 분석 완료 (${recovered_chunks.length}개 구간 자동 복구됨)`, 'success');
    } else if (recovered_chunks.length > 0) {
      showToast(`${prefix}${nChars}명 분석 완료 (복구 ${recovered_chunks.length}개, 실패 ${failed_chunks.length}/${total_chunks}구간)`, 'warning');
    } else {
      showToast(`${prefix}${nChars}명 분석 완료 (일부 구간 실패: ${failed_chunks.length}/${total_chunks} 청크)`, 'warning');
    }
  } else {
    const msg = source === 'pdf'
      ? `PDF 분석 완료! ${appState.parsedScript.characters.length}명의 캐릭터를 발견했습니다.`
      : `${appState.parsedScript.characters.length}명의 캐릭터를 분석했습니다!`;
    showToast(msg, 'success');
  }
}

async function parseScript() {
  if (appState.pendingPdfFile) {
    await _parsePdfFile(appState.pendingPdfFile);
    return;
  }

  const script = document.getElementById('script-input').value.trim();
  if (!script) { showToast('대본을 입력하거나 PDF를 업로드해주세요.', 'error'); return; }

  const btn = document.getElementById('parse-btn');
  const status = document.getElementById('parse-status');
  btn.disabled = true;
  status.classList.remove('hidden');

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 1_200_000);

  try {
    console.time('[parseScript] api');
    const data = await _apiParseText(script, controller.signal);
    console.timeEnd('[parseScript] api');
    clearTimeout(timeoutId);
    _applyParsedScriptState(data);
    const lineCount = appState.parsedScript.lines?.length || 0;
    console.log(`[Script] 텍스트 분석 완료 — lines=${lineCount}, chars=${appState.parsedScript.characters?.length || 0}`);
    if (lineCount < 10) console.warn('[Script] 경고: 분석된 라인이 너무 적습니다. 서버 로그를 확인하세요.');
    _renderCharactersPhase(lineCount, 'text');
  } catch (e) {
    clearTimeout(timeoutId);
    const msg = e.name === 'AbortError'
      ? '분석 시간이 초과됐습니다 (20분). 대본을 짧게 나눠 시도해보세요.'
      : `분석 오류: ${e.message}`;
    showToast(msg, 'error');
    console.error('[parseScript]', e);
  } finally {
    btn.disabled = false;
    status.classList.add('hidden');
  }
}

async function _parsePdfFile(file) {
  const btn = document.getElementById('parse-btn');
  const pdfStatus = document.getElementById('pdf-status');
  btn.disabled = true;
  pdfStatus.innerHTML = '<span class="spinner"></span> PDF 분석 중... (1~5분 소요)';
  pdfStatus.classList.remove('hidden');

  const formData = new FormData();
  formData.append('file', file);

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 1_200_000);

  try {
    console.time('[parsePdf] api');
    const pdfData = await _apiParsePdf(formData, controller.signal);
    console.timeEnd('[parsePdf] api');
    clearTimeout(timeoutId);
    appState.pendingPdfFile = null;
    _applyParsedScriptState(pdfData);
    const pdfLineCount = appState.parsedScript.lines?.length || 0;
    console.log(`[Script] PDF 분석 완료 — lines=${pdfLineCount}, chars=${appState.parsedScript.characters?.length || 0}`);
    if (pdfLineCount < 10) console.warn('[Script] 경고: 분석된 라인이 너무 적습니다. 서버 로그를 확인하세요.');
    _renderCharactersPhase(pdfLineCount, 'pdf');
  } catch (e) {
    clearTimeout(timeoutId);
    const msg = e.name === 'AbortError'
      ? 'PDF 분석 시간이 초과됐습니다 (20분). 대본을 짧게 나눠 시도해보세요.'
      : `PDF 오류: ${e.message}`;
    showToast(msg, 'error');
    console.error('[parsePdf]', e);
  } finally {
    btn.disabled = false;
    pdfStatus.classList.add('hidden');
  }
}

// ── 캐릭터 선택 ────────────────────────────────────────────
function renderCharacters() {
  const titleEl = document.getElementById('script-title');
  titleEl.textContent = appState.parsedScript.title ? `📖 ${appState.parsedScript.title}` : '';

  const grid = document.getElementById('character-grid');
  grid.innerHTML = '';

  appState.parsedScript.characters.forEach(char => {
    const desc = appState.parsedScript.character_descriptions?.[char] || '';
    const card = document.createElement('div');
    card.className = 'char-card';
    card.innerHTML = `
      <div class="char-name">${char}</div>
      <div class="char-desc">${desc}</div>
    `;
    card.onclick = () => selectCharacter(char, card);
    grid.appendChild(card);
  });
}

function selectCharacter(char, card) {
  document.querySelectorAll('.char-card').forEach(c => c.classList.remove('selected'));
  card.classList.add('selected');
  if (appState.userCharacter !== null && appState.userCharacter !== char) {
    console.log(`[Session] 역할 변경: "${appState.userCharacter}" → "${char}" — audioMap 유지`);
    _stopPlayback();
  }
  appState.userCharacter = char;

  const info = document.getElementById('selected-char-info');
  info.classList.remove('hidden');
  info.innerHTML = `✅ <strong>${char}</strong> 역할로 연습합니다. 이 캐릭터의 대사는 직접 읽고, 나머지는 AI 음성으로 재생됩니다.`;

  document.getElementById('next-to-rehearsal').disabled = false;
}

// ── 3단계: 연습 범위 선택 ─────────────────────────────────
function showScopeSelector() {
  appState.scopeMode = 'full';
  const lines = appState.parsedScript.lines;
  const total = lines.length;
  const aiLines = lines.filter(l => l.type === 'dialogue' && l.character !== appState.userCharacter).length;
  document.getElementById('scope-info').textContent =
    `총 ${total}개 항목 (AI 대사 ${aiLines}줄, 전체 구간 기준)`;
  document.getElementById('scope-start').value = 1;
  document.getElementById('scope-start').max = total;
  document.getElementById('scope-end').value = total;
  document.getElementById('scope-end').max = total;
  setScopeMode('full');
  gotoStep(3);
}

function setScopeMode(mode) {
  appState.scopeMode = mode;
  const inputs = document.getElementById('scope-range-inputs');
  if (mode === 'full') {
    document.getElementById('scope-full-btn').className = 'btn btn-primary';
    document.getElementById('scope-range-btn').className = 'btn btn-outline';
    inputs.classList.add('hidden');
  } else {
    document.getElementById('scope-full-btn').className = 'btn btn-outline';
    document.getElementById('scope-range-btn').className = 'btn btn-primary';
    inputs.classList.remove('hidden');
    updateScopePreview();
  }
}

function updateScopePreview() {
  if (!appState.parsedScript) return;
  const lines = appState.parsedScript.lines;
  const startVal = parseInt(document.getElementById('scope-start').value) || 1;
  const endVal = parseInt(document.getElementById('scope-end').value) || lines.length;
  const startIdx = Math.max(0, startVal - 1);
  const endIdx = Math.min(lines.length - 1, endVal - 1);
  const scoped = lines.slice(startIdx, endIdx + 1);
  const aiCount = scoped.filter(l => l.type === 'dialogue' && l.character !== appState.userCharacter).length;
  const myCount = scoped.filter(l => l.type === 'dialogue' && l.character === appState.userCharacter).length;
  document.getElementById('scope-preview').textContent =
    `선택 범위: ${startIdx + 1}~${endIdx + 1}번 항목 — AI 대사 ${aiCount}줄, 내 대사 ${myCount}줄`;
}

function confirmScope() {
  const lines = appState.parsedScript.lines;
  if (appState.scopeMode === 'full') {
    appState.rehearsalStartIdx = 0;
    appState.rehearsalEndIdx = null;
  } else {
    const startVal = parseInt(document.getElementById('scope-start').value) || 1;
    const endVal = parseInt(document.getElementById('scope-end').value) || lines.length;
    appState.rehearsalStartIdx = Math.max(0, Math.min(startVal - 1, lines.length - 1));
    appState.rehearsalEndIdx = Math.max(appState.rehearsalStartIdx, Math.min(endVal - 1, lines.length - 1));
  }
  startGeneration();
}

// ── 초기화 ─────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadSessions();
  applyTheme(localStorage.getItem('theme') || 'dark');
});

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeEndRehearsalDialog();
});
