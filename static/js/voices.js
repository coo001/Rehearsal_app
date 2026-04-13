// ── 2단계: 목소리 배정 ────────────────────────────────────
async function goToVoices() {
  gotoStep(2);
  await loadVoices();

  const otherChars = appState.parsedScript.characters.filter(c => c !== appState.userCharacter);
  if (!otherChars.length) {
    // 1인극 — AI 음성 없음, 바로 4단계
    startGeneration();
    return;
  }

  await autoAssignVoices();
  // 배정 후 자동 진행 없음 — 사용자가 미리듣기/확인 후 직접 진행
}

async function loadVoices() {
  try {
    const res = await fetch('/api/voices');
    if (!res.ok) throw new Error('목소리 목록 불러오기 실패');
    const data = await res.json();
    appState.availableVoices = data.voices;
    renderVoiceTable();
  } catch (e) {
    showToast(`오류: ${e.message}`, 'error');
  }
}

function renderVoiceTable() {
  const loading = document.getElementById('voices-loading');
  const table = document.getElementById('voice-table');
  loading.classList.add('hidden');
  table.classList.remove('hidden');

  const tbody = document.getElementById('voice-table-body');
  tbody.innerHTML = '';

  const otherChars = appState.parsedScript.characters.filter(c => c !== appState.userCharacter);

  // 기본 목소리 자동 배정 (순환)
  const defaultVoices = appState.availableVoices.slice(0, 10);
  otherChars.forEach((char, i) => {
    if (!appState.voiceAssignments[char] && defaultVoices[i % defaultVoices.length]) {
      appState.voiceAssignments[char] = defaultVoices[i % defaultVoices.length].voice_id;
    }
  });

  otherChars.forEach(char => {
    const tr = document.createElement('tr');
    tr.id = `voice-row-${char.replace(/\s/g,'_')}`;

    const selectOpts = appState.availableVoices.map(v =>
      `<option value="${v.voice_id}" ${appState.voiceAssignments[char] === v.voice_id ? 'selected' : ''}>
        ${v.name} — ${v.gender} | ${v.description}
      </option>`
    ).join('');

    tr.innerHTML = `
      <td><strong>${char}</strong></td>
      <td style="color:var(--muted); font-size:0.82rem;">AI 음성</td>
      <td>
        <select id="voice-select-${char.replace(/\s/g,'_')}"
                onchange="appState.voiceAssignments['${char}'] = this.value; document.getElementById('voice-row-${char.replace(/\s/g,'_')}').classList.remove('voice-confirmed')"
                style="max-width:260px;">
          ${selectOpts}
        </select>
      </td>
      <td>
        <div class="voice-action-cell">
          <button id="preview-btn-${char.replace(/\s/g,'_')}" class="voice-preview-btn" onclick="previewVoice('${char}')">▶ 미리듣기</button>
          <button class="voice-preview-btn" onclick="confirmVoice('${char}')" style="color:var(--success);">✓ 확정</button>
          <button id="reassign-btn-${char.replace(/\s/g,'_')}" class="voice-preview-btn" onclick="reAssignVoice('${char}')">↻ 다시 추천</button>
        </div>
        <input
          id="pref-input-${char.replace(/\s/g,'_')}"
          type="text"
          placeholder="원하는 목소리 방향... (예: 더 차분하게, 젊은 느낌)"
          style="margin-top:6px; width:100%; font-size:0.76rem; padding:4px 8px;
                 border:1px solid var(--border); border-radius:6px; background:var(--bg);
                 color:var(--text); box-sizing:border-box;"
        />
      </td>
    `;
    tbody.appendChild(tr);
  });

  if (otherChars.length === 0) {
    tbody.innerHTML = `<tr><td colspan="4" style="color:var(--muted); text-align:center; padding:20px;">
      1인극이거나 다른 캐릭터가 없습니다.
    </td></tr>`;
  }
}

function getFirstDialogueLine(char) {
  return (appState.parsedScript?.lines || []).find(
    l => l.type === 'dialogue' && l.character === char
  ) || null;
}

async function previewVoice(char) {
  const vid = appState.voiceAssignments[char];
  if (!vid) return;

  const btn = document.getElementById(`preview-btn-${char.replace(/\s/g,'_')}`);
  if (btn) { btn.disabled = true; btn.textContent = '...'; }

  const firstLine = getFirstDialogueLine(char);
  const previewText = firstLine?.text || `안녕하세요, 저는 ${char}입니다.`;
  const desc = appState.parsedScript?.character_descriptions?.[char] || '';
  const tempSession = 'preview_' + Date.now();

  const body = {
    text: previewText, voice_id: vid,
    session_id: tempSession, line_index: 0,
    character: char, character_description: desc,
  };
  if (firstLine) {
    body.emotion_label  = firstLine.emotion_label  || null;
    body.intensity      = firstLine.intensity      || null;
    body.tempo          = firstLine.tempo          || null;
    body.beat_goal      = firstLine.beat_goal      || null;
    body.tactics        = firstLine.tactics        || null;
    body.subtext        = firstLine.subtext        || null;
    body.tts_direction  = firstLine.tts_direction  || null;
  } else {
    body.emotion = '차분하고 자연스럽게';
  }

  try {
    const res = await fetch('/api/generate-line', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    if (res.ok) {
      const data = await res.json();
      playNormalizedAudio(data.audio_url);
    } else {
      showToast('미리듣기 생성 실패', 'error');
    }
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '▶ 미리듣기'; }
  }
}

function confirmVoice(char) {
  const row = document.getElementById(`voice-row-${char.replace(/\s/g,'_')}`);
  if (row) row.classList.toggle('voice-confirmed');
}

async function reAssignVoice(char) {
  const btn = document.getElementById(`reassign-btn-${char.replace(/\s/g,'_')}`);
  if (btn) { btn.disabled = true; btn.textContent = '...'; }

  const prefInput = document.getElementById(`pref-input-${char.replace(/\s/g,'_')}`);
  const preference = prefInput?.value?.trim() || '';

  try {
    const body = {
      characters: [char],
      character_descriptions: appState.parsedScript.character_descriptions || {},
    };
    if (preference) body.user_preferences = { [char]: preference };

    const res = await fetch('/api/auto-assign-voices', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      let detail = '재배정 실패';
      try { detail = (await res.json()).detail || detail; } catch {}
      console.error('[VoiceAssign] 재배정 서버 오류:', res.status, detail);
      throw new Error(detail);
    }
    const data = await res.json();
    const newVoiceId = data.assignments?.[char];
    if (newVoiceId) {
      appState.voiceAssignments[char] = newVoiceId;
      const sel = document.getElementById(`voice-select-${char.replace(/\s/g,'_')}`);
      if (sel) sel.value = newVoiceId;
      const row = document.getElementById(`voice-row-${char.replace(/\s/g,'_')}`);
      if (row) row.classList.remove('voice-confirmed');
      showToast(`${char} 목소리 재배정 완료`, 'success');
    } else {
      showToast(`${char} 재배정: 유효한 음성을 찾지 못했습니다. 직접 선택해 주세요.`, 'warning');
    }
  } catch (e) {
    console.error('[VoiceAssign] 재배정 오류:', e);
    showToast(`재배정 실패: ${e.message}`, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '↻ 다시 추천'; }
  }
}

// 음성 배정 상태 반영 + dropdown DOM 업데이트 + toast
function _applyVoiceAssignmentResult(assignments, otherChars) {
  Object.entries(assignments).forEach(([char, voiceId]) => {
    appState.voiceAssignments[char] = voiceId;
    const sel = document.getElementById(`voice-select-${char.replace(/\s/g,'_')}`);
    if (sel) sel.value = voiceId;
  });
  const assigned = Object.keys(assignments).length;
  if (assigned === 0) {
    showToast('자동 배정: 유효한 음성을 찾지 못했습니다. 직접 선택해 주세요.', 'warning');
  } else if (assigned < otherChars.length) {
    showToast(`자동 배정 완료 (${assigned}/${otherChars.length}명). 나머지는 직접 선택해 주세요.`, 'warning');
  } else {
    showToast('AI가 캐릭터에 맞는 목소리를 배정했습니다!', 'success');
  }
}

async function autoAssignVoices() {
  const otherChars = (appState.parsedScript?.characters || []).filter(c => c !== appState.userCharacter);
  if (!otherChars.length) return true;

  console.log(`[VoiceAssign] 시작 — ${otherChars.length}명:`, otherChars);

  const btn = document.getElementById('auto-assign-btn');
  const txt = document.getElementById('auto-assign-text');
  btn.disabled = true;
  txt.innerHTML = '<span class="spinner"></span> AI 배정 중...';

  try {
    const data = await _apiAutoAssignVoices(otherChars, appState.parsedScript.character_descriptions || {});
    console.log(`[VoiceAssign] 완료 — ${Object.keys(data.assignments || {}).length}/${otherChars.length}명 배정`, data.assignments);
    _applyVoiceAssignmentResult(data.assignments || {}, otherChars);
    return true;
  } catch (e) {
    console.error('[VoiceAssign] 오류:', e);
    showToast(`자동 배정 실패: ${e.message}`, 'error');
    return false;
  } finally {
    btn.disabled = false;
    txt.textContent = '🤖 AI 자동 배정';
  }
}
