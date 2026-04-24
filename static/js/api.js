// ── API fetch helpers (순수 fetch — UI/상태 없음) ─────────
async function _apiParseText(script, signal) {
  const res = await fetch('/api/parse-script', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ script }),
    signal,
  });
  if (!res.ok) {
    let detail = '파싱 실패';
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return res.json();
}

async function _apiParsePdf(formData, signal) {
  const res = await fetch('/api/parse-pdf', { method: 'POST', body: formData, signal });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || 'PDF 분석 실패');
  }
  return res.json();
}

async function _apiAutoAssignVoices(chars, descriptions) {
  const res = await fetch('/api/auto-assign-voices', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ characters: chars, character_descriptions: descriptions }),
  });
  if (!res.ok) {
    let detail = '자동 배정 실패';
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return res.json();
}

async function* _apiGenerateRehearsalSSE(payload) {
  const res = await fetch('/api/generate-rehearsal', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('음성 생성 요청 실패');

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop();
    for (const part of parts) {
      const line = part.trim();
      if (line.startsWith('data: ')) {
        try { yield JSON.parse(line.slice(6)); } catch {}
      }
    }
  }
}
