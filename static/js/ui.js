// ── 테마 ───────────────────────────────────────────────────
function applyTheme(theme) {
  document.body.classList.remove('theme-light', 'theme-dark');
  document.body.classList.add('theme-' + theme);
  const btn = document.getElementById('theme-toggle');
  if (btn) btn.textContent = theme === 'light' ? '◑ 다크' : '☀ 라이트';
}

function toggleTheme() {
  const next = (localStorage.getItem('theme') || 'dark') === 'dark' ? 'light' : 'dark';
  localStorage.setItem('theme', next);
  applyTheme(next);
}

// ── 토스트 알림 ────────────────────────────────────────────
function showToast(msg, type = '') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = `toast show ${type}`;
  setTimeout(() => t.className = 'toast', 3000);
}

// ── 오디오 상태 표시 ──────────────────────────────────────
function setAudioStatus(active, text) {
  const wave = document.getElementById('audio-wave');
  const statusText = document.getElementById('audio-status-text');
  if (active) wave.classList.remove('hidden');
  else wave.classList.add('hidden');
  statusText.textContent = text;
}

// ── 대사 보기 모드 ─────────────────────────────────────────
function setVisibilityMode(mode) {
  appState.scriptVisibilityMode = mode;
  document.querySelectorAll('.mode-btn').forEach(btn => btn.classList.remove('active'));
  document.querySelectorAll(`[data-mode="${mode}"]`).forEach(btn => btn.classList.add('active'));
  const saved = appState.currentLineIndex;
  buildScriptViewer();
  appState.currentLineIndex = saved;
  updateDisplay();
}

// ── 전체 대본 스크롤 뷰 빌드 ──────────────────────────────
function buildScriptViewer() {
  const viewer = document.getElementById('script-viewer');
  if (!viewer || !appState.parsedScript) return;
  viewer.innerHTML = '';
  getCanonicalLines().forEach((line, i) => {
    if (!isInScope(i)) return;
    const div = document.createElement('div');
    div.id = `script-line-${i}`;
    if (line.type === 'direction') {
      div.className = 'script-line direction';
      div.textContent = line.text;
    } else {
      const isUser = line.character === appState.userCharacter;
      const masked = shouldMaskLine(line, appState.scriptVisibilityMode, appState.userCharacter);
      div.className = 'script-line upcoming';
      div.innerHTML = `
        <div class="line-char-label ${isUser ? 'user-char' : 'other-char'}">
          ${line.character}${isUser ? ' (나)' : ''}
        </div>
        <div class="line-text${masked ? ' masked' : ''}">${masked ? '••••••' : line.text}</div>
      `;
    }
    viewer.appendChild(div);
  });
}
