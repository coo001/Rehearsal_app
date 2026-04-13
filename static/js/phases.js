// step 번호 ↔ phase 이름의 단일 source-of-truth
const STEP_PHASES = {
  1: 'input',
  2: 'voices',
  3: 'scope',
  4: 'generating',
  5: 'characters',
  6: 'rehearsal',
};

function setStep(active) {
  const maxStep = Object.keys(STEP_PHASES).length;
  for (let i = 1; i <= maxStep; i++) {
    const el = document.getElementById(`step-${i}`);
    el.classList.remove('active', 'done');
    if (i < active) el.classList.add('done');
    else if (i === active) el.classList.add('active');
  }
}

function showPhase(phase) {
  Object.values(STEP_PHASES).forEach(p => {
    document.getElementById(`phase-${p}`).classList.add('hidden');
  });
  document.getElementById(`phase-${phase}`).classList.remove('hidden');
}

// step 번호와 phase를 STEP_PHASES 기반으로 동시에 전환 — 어긋남 방지
function gotoStep(n) {
  setStep(n);
  showPhase(STEP_PHASES[n]);
}

function goBack(toStep) {
  _stopPlayback();
  gotoStep(toStep);
}
