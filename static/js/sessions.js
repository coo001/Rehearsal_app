// ── 세션 저장/복원 ──────────────────────────────────────────
function _fmtDate(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch { return iso.slice(0, 16); }
}

async function loadSessions() {
  try {
    const res = await fetch('/api/sessions');
    if (!res.ok) return;
    const data = await res.json();
    const sessions = data.sessions || [];
    const panel = document.getElementById('session-panel');
    const list = document.getElementById('session-list');
    if (!sessions.length) { panel.classList.add('hidden'); return; }
    panel.classList.remove('hidden');
    list.innerHTML = sessions.slice(0, 6).map(s => `
      <div class="session-card">
        <div class="session-card-left" onclick="restoreSession('${s.session_id}')">
          <div class="session-card-title">${s.title}</div>
          <div class="session-card-meta">${s.user_character ? `내 역할: ${s.user_character} · ` : ''}${s.characters?.length || 0}명 · 음성 ${s.audio_count}개 · ${_fmtDate(s.updated_at)}</div>
        </div>
        <button class="session-card-del" onclick="deleteSession('${s.session_id}')" title="삭제">✕</button>
      </div>
    `).join('');
  } catch(e) { console.warn('[Session] 목록 로드 실패', e); }
}

// 세션 복원 — 캐릭터 렌더 + 2단계 이동 + toast
function _renderRestoredSessionPhase(data) {
  const lineCount = appState.parsedScript?.lines?.length || 0;
  const availableChars = appState.parsedScript?.characters || [];

  if (data.script_text) {
    document.getElementById('script-input').value = data.script_text;
  }

  renderCharacters();
  if (appState.userCharacter && availableChars.includes(appState.userCharacter)) {
    const card = [...document.querySelectorAll('.char-card')].find(
      c => c.querySelector('.char-name')?.textContent === appState.userCharacter
    );
    if (card) selectCharacter(appState.userCharacter, card);
  }

  const hasAudio = Object.keys(appState.audioMap).length > 0;
  if (hasAudio) {
    gotoStep(5);
    const roleHint = appState.userCharacter ? ` (이전 역할: ${appState.userCharacter})` : '';
    const msg = lineCount < 10
      ? `"${data.title || '세션'}" 복원 (경고: 대사 ${lineCount}줄만 있음)`
      : `"${data.title || '세션'}" 복원 완료${roleHint} — 역할을 확인하고 리허설을 시작하세요.`;
    showToast(msg, lineCount < 10 ? 'warning' : 'success');
  } else {
    goToVoices();
    const msg = lineCount < 10
      ? `"${data.title || '세션'}" 복원 (경고: 대사 ${lineCount}줄만 있음)`
      : `"${data.title || '세션'}" 복원 완료 — 목소리를 확인하고 계속하세요.`;
    showToast(msg, lineCount < 10 ? 'warning' : 'success');
  }
}

async function restoreSession(sid) {
  try {
    const res = await fetch(`/api/sessions/${sid}`);
    if (!res.ok) { showToast('세션을 불러올 수 없습니다.', 'error'); return; }
    const data = await res.json();

    _applySessionData(data);

    const restoredLineCount = appState.parsedScript?.lines?.length || 0;
    console.log(
      `[Session] 복원 완료 — session=${data.session_id?.slice(0,8)}, lines=${restoredLineCount},` +
      ` audio=${Object.keys(appState.audioMap).length}, characters=${appState.parsedScript?.characters?.length || 0},` +
      ` restored_role="${appState.userCharacter}", role_selector=enabled`
    );
    if (restoredLineCount < 10) console.warn('[Session] 복원된 대본이 너무 짧습니다. 대본을 다시 분석해 보세요.');

    _renderRestoredSessionPhase(data);
  } catch(e) {
    showToast('세션 복원 중 오류가 발생했습니다.', 'error');
    console.error('[Session] 복원 실패', e);
  }
}

async function deleteSession(sid) {
  try {
    await fetch(`/api/sessions/${sid}`, { method: 'DELETE' });
    loadSessions();
  } catch(e) { console.warn('[Session] 삭제 실패', e); }
}

async function saveCurrentSession() {
  if (!appState.parsedScript || !appState.sessionId) return;
  try {
    await fetch('/api/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: appState.sessionId,
        title: appState.parsedScript.title || '제목 없음',
        script_text: document.getElementById('script-input').value || '',
        parsed_script: appState.parsedScript,
        user_character: appState.userCharacter,
        voice_assignments: appState.voiceAssignments,
        audio_map: appState.audioMap,
        rehearsal_start_idx: appState.rehearsalStartIdx,
        rehearsal_end_idx: appState.rehearsalEndIdx,
      }),
    });
    console.log('[Session] 저장 완료:', appState.sessionId);
  } catch(e) { console.warn('[Session] 저장 실패', e); }
}
