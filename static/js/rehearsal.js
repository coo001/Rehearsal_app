// ── 5단계: 음성 생성 ──────────────────────────────────────
// 생성 결과 상태 반영 + 진행바 업데이트
// Remap: server returns 0-based subset indices → original appState.parsedScript indices via scopeStart
function _applyGenerationResult(data, scopeStart, total) {
  appState.sessionId = data.session_id;
  appState.audioMap = {};
  Object.entries(data.audio_map).forEach(([subIdx, url]) => {
    appState.audioMap[String(scopeStart + parseInt(subIdx))] = url;
  });
  const generatedCount = Object.keys(appState.audioMap).length;
  const pct = total > 0 ? Math.round(generatedCount / total * 100) : 100;
  document.getElementById('gen-progress').style.width = `${pct}%`;
  document.getElementById('gen-status').textContent = `${generatedCount}/${total}개 음성 생성 완료`;
}

async function startGeneration() {
  gotoStep(4);

  const { start: scopeStart, end: scopeEnd } = getScopedBounds();
  const scopedLines = getScopedLines();

  const canonical = getCanonicalLines();
  console.log(`[Gen] canonical=${canonical.length}줄, scope=[${scopeStart}..${scopeEnd}], scoped=${scopedLines.length}줄`);
  if (scopedLines.length === 0) {
    console.warn('[Gen] scoped line count is 0 — 범위를 확인하세요');
    showToast('연습 범위 안에 대사가 없습니다. 범위를 확인하세요.', 'error');
    gotoStep(3); return;
  }
  if (scopeStart > canonical.length - 1 || scopeEnd > canonical.length - 1) {
    console.warn(`[Gen] 범위 초과 — canonical length=${canonical.length}, scope=[${scopeStart}..${scopeEnd}]`);
  }

  const nonUserLines = scopedLines.filter(l => l.type === 'dialogue');
  const total = nonUserLines.length;

  if (total === 0) {
    gotoStep(5);
    return;
  }

  document.getElementById('gen-status').textContent = '서버에 요청 중...';

  try {
    const data = await _apiGenerateRehearsal({
      lines: scopedLines,
      voice_assignments: appState.voiceAssignments,
      user_character: '',
      character_descriptions: appState.parsedScript.character_descriptions || {},
    });
    _applyGenerationResult(data, scopeStart, total);

    await saveCurrentSession();

    setTimeout(() => gotoStep(5), 800);

  } catch (e) {
    showToast(`음성 생성 오류: ${e.message}`, 'error');
    gotoStep(3);
  }
}

// ── 6단계: 연습 ───────────────────────────────────────────
function startRehearsal() {
  gotoStep(6);

  document.getElementById('my-role-label').textContent = appState.userCharacter;

  buildScriptViewer();

  resetPlaybackState();
  updateDisplay();
  if (appState.autoAdvance) {
    setTimeout(() => playCurrentLine(), 600);
  }
}

function updateDisplay() {
  const lines = getCanonicalLines();
  const { start: scopeStart, end: scopeEnd } = getScopedBounds();
  const scopeLen = scopeEnd - scopeStart + 1;
  const posInScope = appState.currentLineIndex - scopeStart + 1;

  document.getElementById('line-counter').textContent =
    `${Math.min(posInScope, scopeLen)} / ${scopeLen}`;

  lines.forEach((_, i) => {
    const el = document.getElementById(`script-line-${i}`);
    if (!el) return;
    el.classList.remove('current', 'past', 'upcoming');
    if (i < appState.currentLineIndex) el.classList.add('past');
    else if (i === appState.currentLineIndex) el.classList.add('current');
    else el.classList.add('upcoming');
  });

  if (appState.currentLineIndex > scopeEnd) {
    document.getElementById('current-box').className = 'current-line-box';
    document.getElementById('current-badge').textContent = '🎉 연습 완료';
    document.getElementById('current-badge').className = 'turn-badge dir';
    document.getElementById('current-text').textContent = '모든 대사 연습이 끝났습니다! 처음부터 다시 연습하거나 새 대본을 불러오세요.';
    document.getElementById('btn-play').disabled = true;
    document.getElementById('btn-next').disabled = true;
    return;
  }

  const line = lines[appState.currentLineIndex];
  const box = document.getElementById('current-box');
  const badge = document.getElementById('current-badge');
  const textEl = document.getElementById('current-text');
  const playBtn = document.getElementById('btn-play');
  const hintEl = document.getElementById('auto-advance-hint');

  if (line.type === 'direction') {
    box.className = 'current-line-box direction-turn';
    badge.className = 'turn-badge dir';
    badge.textContent = '📍 무대 지문';
    textEl.textContent = line.text;
    playBtn.textContent = '다음으로 ▶';
    playBtn.disabled = false;
    hintEl.textContent = '';
  } else if (line.character === appState.userCharacter) {
    box.className = 'current-line-box user-turn';
    badge.className = 'turn-badge user';
    badge.textContent = `🎤 내 대사 (${appState.userCharacter})`;
    const maskedUser = shouldMaskLine(line, appState.scriptVisibilityMode, appState.userCharacter);
    textEl.textContent = maskedUser ? '••••••' : line.text;
    playBtn.textContent = listeningActive ? '✋ 완료 (수동)' : '✓ 읽었어요 →';
    playBtn.disabled = false;
    hintEl.textContent = appState.autoAdvance
      ? '대사를 말하세요. 잠시 멈추면 자동으로 넘어갑니다.'
      : '위 대사를 읽은 후 버튼을 누르세요.';
  } else {
    box.className = 'current-line-box';
    badge.className = 'turn-badge ai';
    badge.textContent = `🤖 ${line.character}의 대사`;
    const maskedAI = shouldMaskLine(line, appState.scriptVisibilityMode, appState.userCharacter);
    textEl.textContent = maskedAI ? '••••••' : line.text;
    playBtn.textContent = '▶ 재생';
    playBtn.disabled = false;

    const hasAudio = appState.audioMap[appState.currentLineIndex] != null;
    hintEl.textContent = hasAudio ? '재생 버튼을 눌러 AI 음성을 들으세요.' : '(음성 없음) 재생 버튼으로 다음으로 넘어갑니다.';
  }

  document.getElementById('btn-prev').disabled = appState.currentLineIndex <= scopeStart;
  document.getElementById('btn-next').disabled = appState.currentLineIndex >= scopeEnd;
}

async function playCurrentLine() {
  const lines = getCanonicalLines();
  if (appState.currentLineIndex >= lines.length) return;

  const line = lines[appState.currentLineIndex];

  if (line.type === 'direction') {
    if (appState.autoAdvance) scheduleAutoAdvance(600, '지문');
    else navigate(1);
    return;
  }

  if (line.character === appState.userCharacter) {
    if (appState.autoAdvance) {
      if (listeningActive) {
        stopListening();
        navigate(1);
      } else {
        startListening();
      }
    } else {
      navigate(1);
    }
    return;
  }

  // AI 대사 재생
  const audioUrl = appState.audioMap[appState.currentLineIndex];
  if (!audioUrl) {
    if (appState.autoAdvance) {
      const { ms: delay, why } = _dialogueAdvanceDelay(line);
      console.log(`[Timing] idx=${appState.currentLineIndex} type=dialogue no-audio → ${delay}ms (${why})`);
      if (delay > 0) scheduleAutoAdvance(delay, '');
      else navigate(1);
    } else {
      navigate(1);
    }
    return;
  }

  if (appState.currentAudio) { appState.currentAudio.pause(); appState.currentAudio = null; }

  setAudioStatus(true, `${line.character} 재생 중...`);
  document.getElementById('btn-play').disabled = true;

  const ctrl = await playNormalizedAudio(audioUrl, {
    onEnded: () => {
      setAudioStatus(false, '');
      document.getElementById('btn-play').disabled = false;
      document.getElementById('btn-play').textContent = '▶ 다시 재생';
      if (appState.autoAdvance) {
        const { ms: pauseMs, why } = _dialogueAdvanceDelay(line);
        console.log(`[Timing] idx=${appState.currentLineIndex} type=dialogue after-audio → ${pauseMs}ms (${why})`);
        if (pauseMs > 0) scheduleAutoAdvance(pauseMs, '다음 대사까지');
        else navigate(1);
      }
    },
    onError: () => {
      setAudioStatus(false, '');
      showToast('음성 재생 실패', 'error');
      document.getElementById('btn-play').disabled = false;
    },
  });
  if (ctrl) appState.currentAudio = ctrl;
}

// ── 오디오 peak 정규화 재생 ────────────────────────────────
async function playNormalizedAudio(url, { onEnded, onError } = {}) {
  if (!_playbackCtx || _playbackCtx.state === 'closed') {
    _playbackCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  if (_playbackCtx.state === 'suspended') await _playbackCtx.resume();
  const ctx = _playbackCtx;

  let audioBuffer;
  try {
    const res = await fetch(url);
    const raw = await res.arrayBuffer();
    audioBuffer = await ctx.decodeAudioData(raw);
  } catch (e) {
    onError && onError(e);
    return null;
  }

  let peak = 0;
  for (let ch = 0; ch < audioBuffer.numberOfChannels; ch++) {
    const data = audioBuffer.getChannelData(ch);
    for (let i = 0; i < data.length; i++) {
      const abs = Math.abs(data[i]);
      if (abs > peak) peak = abs;
    }
  }

  const gain = peak > 0.01 ? Math.min(AUDIO_TARGET_PEAK / peak, AUDIO_MAX_GAIN) : 1.0;

  const source   = ctx.createBufferSource();
  source.buffer  = audioBuffer;
  const gainNode = ctx.createGain();
  gainNode.gain.value = gain;
  source.connect(gainNode);
  gainNode.connect(ctx.destination);
  source.onended = onEnded || null;
  source.start();

  return {
    pause() { try { source.stop(); } catch (_) {} },
  };
}

function navigate(dir) {
  _stopPlayback();

  const { start: scopeStart, end: scopeEnd } = getScopedBounds();
  const newIdx = appState.currentLineIndex + dir;
  if (newIdx < scopeStart || newIdx > scopeEnd + 1) return;
  appState.currentLineIndex = newIdx;
  updateDisplay();

  if (appState.autoAdvance && newIdx <= scopeEnd) {
    const next = getCanonicalLines()[newIdx];
    if (next.type === 'direction') {
      scheduleAutoAdvance(700, '지문');
    } else if (next.character === appState.userCharacter) {
      setTimeout(() => startListening(), 400);
    } else {
      const { ms: delay, why } = _dialogueAdvanceDelay(next);
      console.log(`[Timing] idx=${newIdx} type=dialogue char='${next.character}' → ${delay}ms (${why})`);
      if (delay > 0) setTimeout(() => playCurrentLine(), delay);
      else playCurrentLine();
    }
  }
}

function restartRehearsal() {
  resetPlaybackState();
  updateDisplay();
  showToast('처음부터 다시 시작합니다.', 'success');
  if (appState.autoAdvance) {
    setTimeout(() => playCurrentLine(), 500);
  }
}

// ── 연습 끝내기 ───────────────────────────────────────────
function endRehearsal() {
  openEndRehearsalDialog();
}

function openEndRehearsalDialog() {
  document.getElementById('end-rehearsal-overlay').classList.remove('hidden');
  document.getElementById('end-dlg-cancel').focus();
}

function closeEndRehearsalDialog() {
  document.getElementById('end-rehearsal-overlay').classList.add('hidden');
}

function _doEndRehearsal() {
  closeEndRehearsalDialog();
  _stopPlayback();
  _resetAutoAdvanceUI();
  goBack(5);
}

// ── 자동 진행 토글 ─────────────────────────────────────────
function toggleAutoAdvance() {
  appState.autoAdvance = !appState.autoAdvance;
  const btn = document.getElementById('auto-advance-toggle');
  if (appState.autoAdvance) {
    btn.textContent = '🎤 음성 감지 ON';
    btn.style.borderColor = 'var(--success)';
    btn.style.color = 'var(--success)';
    showToast('음성 감지 모드 켜짐 — 대사를 말하면 자동으로 넘어갑니다.', 'success');
    autoAdvanceCurrentIfNeeded();
  } else {
    btn.textContent = '⏸ 수동 진행';
    btn.style.borderColor = 'var(--muted)';
    btn.style.color = '';
    stopListening();
    clearCountdown();
    showToast('수동 진행 모드로 전환되었습니다.', '');
  }
}

function autoAdvanceCurrentIfNeeded() {
  if (!appState.autoAdvance) return;
  const line = getCanonicalLines()[appState.currentLineIndex];
  if (!line) return;
  if (line.type === 'direction') {
    scheduleAutoAdvance(600, '지문');
  } else if (line.character === appState.userCharacter) {
    setTimeout(() => startListening(), 400);
  }
}

// 텍스트 읽기 예상 시간 (ms) - 한국어 기준 약 3.5자/초 + 여유 시간
function getReadingTimeMs(text) {
  const ms = (text.length / 3.5) * 1000 + 1500;
  return Math.max(2500, Math.min(ms, 10000));
}

// 대화 대사 자동 진행 delay 결정
function _dialogueAdvanceDelay(line) {
  const text = line.text || '';
  if (/\(사이\)|\(pause\)|\(beat\)|\(멈춤\)/i.test(text)) {
    return { ms: 300, why: 'explicit-side' };
  }
  if ((line.next_cue_delay_ms ?? 0) > 500 || (line.pause_after ?? 0) > 500) {
    return { ms: 150, why: 'analysis-pause' };
  }
  return { ms: 0, why: 'immediate' };
}

// 카운트다운 바 표시 + 타이머
function scheduleAutoAdvance(ms, label) {
  clearCountdown();
  const wrap = document.getElementById('countdown-bar-wrap');
  const bar  = document.getElementById('countdown-bar');
  const lbl  = document.getElementById('countdown-label');

  wrap.classList.remove('hidden');
  lbl.textContent = `${label} 후 자동 진행... (${(ms/1000).toFixed(1)}초)`;
  bar.style.transition = 'none';
  bar.style.width = '100%';

  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      bar.style.transition = `width ${ms}ms linear`;
      bar.style.width = '0%';
    });
  });

  countdownTimer = setTimeout(() => {
    clearCountdown();
    navigate(1);
  }, ms);
}

function clearCountdown() {
  if (countdownTimer) { clearTimeout(countdownTimer); countdownTimer = null; }
  const wrap = document.getElementById('countdown-bar-wrap');
  if (wrap) wrap.classList.add('hidden');
}

// ── 마이크 음성 감지 ───────────────────────────────────────
async function startListening() {
  if (listeningActive) return;
  try {
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const source = audioCtx.createMediaStreamSource(micStream);
    analyserNode = audioCtx.createAnalyser();
    analyserNode.fftSize = 256;
    source.connect(analyserNode);

    listeningActive = true;
    speechDetected = false;
    silenceTimer = null;
    speechStartTime = 0;

    setListeningStatus(true);
    analyzeMic();

    setTimeout(() => {
      if (listeningActive) { stopListening(); navigate(1); }
    }, MAX_LISTEN_MS);

  } catch (e) {
    showToast('마이크 접근 실패. 타이머로 대체합니다.', 'error');
    const line = appState.parsedScript?.lines[appState.currentLineIndex];
    if (line && appState.autoAdvance) scheduleAutoAdvance(getReadingTimeMs(line.text), '내 대사 읽기');
  }
}

function stopListening() {
  if (!listeningActive && !micStream) return;
  listeningActive = false;
  if (silenceTimer) { clearTimeout(silenceTimer); silenceTimer = null; }
  if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
  if (audioCtx) { audioCtx.close().catch(() => {}); audioCtx = null; }
  analyserNode = null;
  setListeningStatus(false);
}

function analyzeMic() {
  if (!listeningActive || !analyserNode) return;
  const buf = new Float32Array(analyserNode.fftSize);
  analyserNode.getFloatTimeDomainData(buf);

  let sum = 0;
  for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
  const rms = Math.sqrt(sum / buf.length);
  const isSpeaking = rms > SPEECH_THRESHOLD;

  if (isSpeaking) {
    if (!speechDetected) {
      speechDetected = true;
      speechStartTime = Date.now();
    }
    if (silenceTimer) { clearTimeout(silenceTimer); silenceTimer = null; }
  } else if (speechDetected && !silenceTimer) {
    const spokenMs = Date.now() - speechStartTime;
    if (spokenMs >= MIN_SPEECH_MS) {
      silenceTimer = setTimeout(() => {
        stopListening();
        navigate(1);
      }, SILENCE_DURATION);
    }
  }

  requestAnimationFrame(analyzeMic);
}

function setListeningStatus(active) {
  const wave = document.getElementById('audio-wave');
  const statusText = document.getElementById('audio-status-text');
  const playBtn = document.getElementById('btn-play');
  const box = document.getElementById('current-box');

  if (active) {
    wave.classList.remove('hidden');
    wave.classList.add('listening');
    box.classList.add('listening-turn');
    statusText.textContent = '🎤 듣는 중... (대사를 말하고 잠시 멈추면 자동으로 넘어갑니다)';
    const line = appState.parsedScript?.lines[appState.currentLineIndex];
    if (line?.character === appState.userCharacter) playBtn.textContent = '✋ 완료 (수동)';
  } else {
    wave.classList.remove('listening');
    box.classList.remove('listening-turn');
    if (!appState.currentAudio) { wave.classList.add('hidden'); statusText.textContent = ''; }
    const line = appState.parsedScript?.lines[appState.currentLineIndex];
    if (line?.character === appState.userCharacter) playBtn.textContent = '✓ 읽었어요 →';
  }
}
