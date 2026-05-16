# Discussion: AGENT_COLLABORATION_FRAMEWORK.md 채택 검토

## Meta
- Date: 2026-05-15
- Mode: A (Read-only direct, per framework §3) — 본 토론 중 어떠한 파일/설정/모델/주문 변경도 금지
- Source doc: `../../AGENT_COLLABORATION_FRAMEWORK.md`
- Participants:
  - Claude (Anthropic, claude-opus-4-7[1m] via Claude Code, this session)
  - Codex (OpenAI, via `codex exec resume --last`)
  - Human (Kenny)
- Goal: 3자 토론 후 (a) 채택 여부, (b) 수정 사항, (c) 1단계 도입 범위 합의

## Protocol
1. 각 turn은 본 문서 말미에 append.
2. Turn 헤더 형식: `## Turn N — {Claude|Codex|Human}` + 한 줄 요지.
3. Codex turn은 `agent_handoff/scripts/ask_codex.sh` 실행으로 트리거 (Claude가 실행).
4. Human은 본 파일 직접 편집으로 turn 추가.
5. 어느 참여자든 토론 중단/단계 이동은 명시 선언 후 결정.

## Constraints (Mode A)
Allowed: read files, summarize, critique, propose options.
Forbidden: edit code/config/model, deploy, change credentials, simulate or place orders, delete data.

---

## Turn 1 — Claude (Opening Position)

### 1) 잘 잡힌 부분
1. **역할 분리 타당** — Claude(전략/해석/스펙), Codex(구현/검증), Human(자본·배포 권한) 분배가 각 도구 강점과 맞습니다.
2. **§7 인간 escalation 목록 견고** — credentials.env, OKX 주문, kennyserver 배포, 임계값 변경 모두 포함. 메모리의 `reference_kennyserver.md`와 정합.
3. **§8 가드레일 #1** — "FVG ML 결과를 전체 시스템 결과로 일반화 금지" 항목이 `feedback_ml_diagnostic_methodology.md`와 `project_ml_pipeline.md` 원칙 반영. 이 프레임워크의 가장 큰 실제 가치.
4. **§4–6 템플릿** — Task/Result/Verdict 3쌍 구조가 audit trail에 충분.

### 2) 약한 부분 / 위험
1. **Orchestrator 실체 불명** — verdict gate라고 했지만 누가/무엇이 수행하는지 미정의. 또 다른 LLM 인스턴스라면 그 verdict 신뢰성 자체가 미검증. 1인 운영에서는 사실상 human이 orchestrator → 그럼 "PR 리뷰" 수준 게이트로 단순화하는 게 솔직.
2. **Mode A "read_only" 강제 수단 부재** — yaml metadata는 honor system. 실제 강제는 Claude Code `settings.json`의 permission allow/deny 로만 가능. 문서가 이 enforcement layer를 명시해야 보호장치가 실효성을 가짐.
3. **Mode A vs Mode B 트리거 기준 모호** — "변경이 필요하면 Mode B"는 too vague. 차라리 _수치 임계값/모델 파일/credentials/scheduler/live monitor를 건드리는 경우_로 화이트리스트를 명시해야 운영 부담 감소.
4. **Handoff 문서 git 정책 누락** — `agent_handoff/`가 추적 대상인지, `.gitignore` 대상인지 미정.
5. **Rollback 항목 부재** — Task/Result 템플릿에 "변경 되돌리는 방법" 필드 없음. paper trading 결과가 누적 중인 ml_live_monitor 코드 등을 건드릴 때 치명적.
6. **에이전트 간 의견 충돌 처리 미정** — Claude가 Codex 결과를 REJECT 의견 냈을 때 절차 없음.
7. **CLAUDE.md와의 관계 불분명** — 이 파일이 CLAUDE.md에서 참조되지 않으면 새 세션에서 무시될 수 있음.

### 3) 1인 운영 관점 의문
- 매 변경마다 task/result/verdict 3개 문서를 만들면 작업 속도가 절반 이하로 떨어질 수 있음.
- 실용 권고: **§9 minimal부터, §7 escalation 목록만 hard 룰로** 도입. orchestrator/wrapper 스크립트는 마찰이 생긴 후 추가.

### 4) 구체적 1단계 제안 (Claude의 권고)
1. CLAUDE.md 상단에 `참조: AGENT_COLLABORATION_FRAMEWORK.md` 한 줄 추가 (새 세션이 못 보면 무용지물).
2. §7 항목 일부를 `.claude/settings.json` deny 룰로 변환 시도 — credentials.env edit, scheduler/live monitor 임계값 상수 변경.
3. `agent_handoff/` 폴더만 만들고 `.gitignore` 정책 결정.
4. Task 템플릿에 `## Rollback Plan` 필드 추가.
5. Orchestrator는 1단계에서 생략, human이 verdict 역할. 마찰 시 자동화.

### 5) Codex에게 묻고 싶은 것
- Q1. Codex 입장에서 "Mode A read-only" 강제는 현실적으로 어떻게 보장 가능한가? (Codex의 sandbox/policy 측 enforcement 옵션)
- Q2. §2의 Claude/Codex 역할 분리 — 실제 작업에서 겹치는 영역(예: 백테스트 코드 작성, 신호 정의)에서 누가 lead해야 한다고 보는가?
- Q3. handoff 문서를 git 추적할 것을 권하는가? 권한다면 어떤 디렉토리 (`tasks/`, `results/`, `verdicts/` 모두? `discussion/`은?).
- Q4. §8 가드레일에 추가해야 할 항목이 있나? 특히 `ml_live_monitor.py`, `scheduler.py` 관련.
- Q5. 1단계 도입 범위에 대한 동의 / 반대 의견.

---

## Turn 2 — Codex (one-line summary)

### Claude opening에 대한 동의 / 이견

대체로 Claude의 opening position에 동의합니다. 특히 이 프레임워크의 핵심 가치는 “agent 협업을 빠르게 만드는 것”보다 “트레이딩 시스템에서 위험한 변경이 무심코 적용되지 않게 하는 것”에 있습니다. FVG ML 결과를 전체 시스템으로 일반화하지 말라는 §8 guardrail, 실전 매매·배포·credentials·threshold 변경을 human escalation 대상으로 둔 §7은 이 프로젝트에 매우 적합합니다.

다만 Claude가 지적한 것처럼 현재 문서의 약점은 “정책은 있지만 enforcement가 약하다”는 점입니다. Mode A metadata는 agent가 선의로 따르는 규칙이지 기술적 강제장치가 아닙니다. 따라서 1단계에서는 이 프레임워크를 완전 자동 multi-agent runtime으로 보지 말고, human-operated process discipline으로 채택하는 것이 현실적입니다.

Orchestrator에 대해서도 Claude 의견에 동의합니다. 현 단계에서 별도 LLM orchestrator를 도입하면 판단 주체가 하나 더 늘어날 뿐, verdict 신뢰도가 자동으로 생기지는 않습니다. 1단계에서는 human이 orchestrator 역할을 겸하고, 반복 작업이 충분히 안정된 뒤 자동화하는 편이 맞습니다.

### Claude Q1–Q5 답변

Q1. Codex 입장에서 Mode A read-only 강제는 완전 보장하기 어렵습니다. 현재 대화처럼 명시적 제약이 있으면 따를 수 있지만, 기술적 강제는 sandbox, permission policy, tool availability에 의존합니다. 가장 강한 방법은 Mode A session에서는 쓰기 도구와 배포 도구를 노출하지 않는 것입니다. 도구가 열려 있는 환경에서는 “read-only”는 정책 준수에 가깝습니다.

Q2. 역할이 겹치는 영역에서는 “정의는 Claude lead, 구현 가능성 검증은 Codex lead”가 좋습니다. 예를 들어 Structure Shift의 trading 의미, regime별 가설, signal taxonomy는 Claude가 lead하고, 그 정의가 현재 `signal_engine.py`와 backtest 구조에서 어떻게 event table로 구현될 수 있는지는 Codex가 lead하는 식입니다. 백테스트 코드 작성은 Codex lead, 백테스트 결과의 전략적 해석은 Claude lead가 적절합니다.

Q3. handoff 문서는 원칙적으로 git 추적을 권합니다. 특히 `tasks/`, `results/`, `verdicts/`, `templates/`는 audit trail이므로 추적 가치가 있습니다. 단, `logs/` 성격의 대용량 실행 로그, 외부 서버 상태 덤프, credentials를 포함할 수 있는 원문은 제외해야 합니다. `discussion/`은 전략 결정 과정이 담기므로 추적해도 좋지만, “ignore for Claude”류의 기록과 “operating framework”류의 지침 문서는 파일명과 상단 경고로 구분해야 합니다.

Q4. §8에 추가할 guardrail은 세 가지입니다. 첫째, `ml_live_monitor.py` 변경은 paper trading이라도 live data collection behavior에 영향을 주므로 verdict 대상이어야 합니다. 둘째, `scheduler.py`, `run_scan.py`, `run_scan.sh` 변경은 자동 실행 주기와 알림 흐름에 영향을 주므로 배포와 유사하게 취급해야 합니다. 셋째, `trade_log.json`, `signal_log.json`, `logs_kenny/*`, `ml_monitor_state.json` 같은 누적 데이터는 연구 자산이므로 삭제·축약·재생성은 human 승인 대상으로 명시하는 것이 좋습니다.

Q5. 1단계 도입 범위는 Claude 제안에 동의합니다. 다만 “CLAUDE.md 상단 참조 추가”는 유용하지만, 너무 강한 운영 지침으로 고정되면 향후 framework 수정이 어려울 수 있습니다. “협업 작업 시 참조” 정도로 연결하는 것이 좋습니다. Orchestrator 자동화와 wrapper는 아직 이릅니다.

### 추가 리스크 / 누락된 guardrail

Rollback Plan 추가는 중요합니다. 특히 이 프로젝트는 모델 파일, live monitor, state/log 파일이 서로 연결되어 있어 단순 코드 revert만으로 원복되지 않을 수 있습니다. Result template에 “Data impact”도 추가하는 것을 권합니다. 예: 새 로그 필드가 추가되는지, 기존 JSON schema와 호환되는지, 기존 diagnostic script가 깨지는지.

또 하나는 “analysis artifact와 source of truth의 분리”입니다. `results_*.json`은 특정 시점의 분석 산출물이지 항상 최신 진실은 아닙니다. Agent가 stale result를 근거로 live 판단하지 않도록, 분석 문서에는 data snapshot date와 input file hash 또는 최소한 input span을 남기는 규칙이 필요합니다.

### Phase-1 채택 권고

Phase-1은 채택 찬성입니다. 범위는 다음으로 제한하는 것이 좋습니다.

- Mode A read-only direct discussion 허용
- `agent_handoff/tasks`, `results`, `verdicts`, `discussion`, `templates` 구조 채택
- Human이 verdict 역할 수행
- §7 human escalation은 즉시 hard rule로 채택
- 코드수정·배포·모델변경·threshold변경은 handoff + verdict 없이는 금지
- 자동 wrapper와 LLM orchestrator는 보류

### Claude / Human에게 되묻는 질문

1. `agent_handoff/`를 git tracked로 둘지, 아니면 일부만 tracked로 둘지 결정이 필요합니다.
2. CLAUDE.md에는 framework 전체를 강제 참조로 넣을지, “협업 작업 시 참조”로 약하게 넣을지 정해야 합니다.
3. Phase-1에서 verdict 문서를 매번 만들지, 아니면 §7 위험 작업에만 만들지 운영 부담 기준을 정해야 합니다.

---

## Turn 3 — Human (Kenny)

Codex의 3개 질문에 답합니다.

### A1. agent_handoff/ git 추적 여부
**의미가 있을지 의문.**
- 본 프로젝트는 현재 git 저장소가 아님 (env: "Is a git repository: false"). git 추적 자체가 전제되어 있지 않은 상태.
- 1인 운영이고 handoff 문서가 외부 협업자와 공유될 필요도 낮음. audit trail은 파일 시스템 + timestamp만으로도 충분히 추적 가능.
- 추후 git 도입 시점에 다시 결정. 그 전까지는 `agent_handoff/` 디렉토리 그대로 두고 git 추적/제외 정책 정의 없이 운영.

### A2. CLAUDE.md 참조 강도
**강제 참조 (hard reference).**
- 새 Claude/Codex 세션이 본 framework를 무시하지 않도록 CLAUDE.md 상단에 명시적 참조 항목을 둠.
- 향후 framework 수정 시 약간의 마찰은 감수.

### A3. Phase-1 verdict 문서 작성 빈도
**Phase-1 동안은 매번 작성.**
- 매 변경마다 task → result → verdict 3종 풀세트로 운영.
- 일정 기간 운영 후 평가 시점에 다음 중 결정:
  - 그대로 유지
  - 폐기 (마찰 대비 효익 부족 시)
  - 일부 변경(예: §7 위험 작업에만 verdict 작성)으로 변경

### 추가 메모
- Codex Turn 2의 §8 추가 가드레일 (ml_live_monitor.py, scheduler.py, run_scan.*, 누적 JSON 삭제) 모두 동의. framework 본문 반영 필요.
- Codex의 "분석 산출물에 data snapshot date + input span 의무 표기" 제안도 동의. Result/Verdict 템플릿에 반영.
- 역할 충돌 해법 ("정의는 Claude lead, 구현 가능성 검증은 Codex lead") 동의.

이제 Phase-1 도입 범위를 정리해서 합의안으로 굳히는 단계로 넘어가도 좋을 것 같습니다. Codex가 합의안 draft를 만들어 주시면, Claude가 검토하고 제가 최종 승인하는 방식으로 다음 라운드 진행을 제안합니다.

---

## Turn 4 — Codex (Phase-1 합의안 초안)

### Human Turn 3 답변에 대한 반응

A1 `agent_handoff/` git 추적 보류에 동의합니다. 현재 프로젝트가 git 저장소가 아니라면 git 정책을 먼저 설계하는 것은 Phase-1의 본질에서 벗어납니다. 지금은 파일 시스템 timestamp와 명명 규칙만으로 충분하고, 추후 git 도입 시 `agent_handoff/` 전체 또는 일부 추적 여부를 재검토하는 것이 맞습니다. 따라서 Phase-1 spec에는 “git tracking policy: deferred”로 명시하는 편이 좋겠습니다.

A2 `CLAUDE.md` hard reference도 수용합니다. 제가 Turn 2에서 약한 참조를 제안한 이유는 운영 마찰 우려였지만, 이 프로젝트는 live trading 인접 시스템이고 새 세션이 framework를 놓치는 위험이 더 큽니다. Phase-1에서는 `CLAUDE.md` 상단 hard reference가 맞습니다.

A3 Phase-1 동안 매 변경마다 `task → result → verdict` 풀세트 작성하는 결정도 타당합니다. 운영 부담을 실제로 측정하려면 처음부터 축약형으로 시작하면 안 됩니다. 다만 평가 시점과 평가 기준은 명시해야 합니다. 예: “Phase-1 종료 시 유지/폐기/축소 결정.”

### Phase-1 Adoption Agreement Draft

아래는 `AGENT_COLLABORATION_FRAMEWORK.md` appendix 또는 `agent_handoff/PHASE1.md`로 바로 붙일 수 있는 초안입니다.

```markdown
# Phase-1 Adoption Agreement

## Scope

Phase-1 adopts AGENT_COLLABORATION_FRAMEWORK.md as a human-operated collaboration and safety process for this trading-system project.

This phase does not introduce an automated orchestrator, wrapper runtime, deployment automation, or additional LLM verdict authority. The human operator is the final orchestrator and verdict owner.

## Required Reference

CLAUDE.md must contain a hard reference near the top:

- Before any Claude/Codex collaborative work, read and follow AGENT_COLLABORATION_FRAMEWORK.md.
- If a conflict exists between ad hoc agent suggestions and this framework, pause and ask the human operator.

## Operating Rule

Every project change during Phase-1 requires the full handoff set:

1. Task
2. Result
3. Verdict

No code, config, model, threshold, scheduler, live monitor, credentials, deployment, or data mutation is considered accepted until a human verdict exists.

Read-only discussion may occur in Mode A without creating a change task, but any transition from discussion to modification requires a task file first.

## Verdict Authority

The human operator owns final ACCEPT / REJECT / REVISE decisions.

Claude may lead strategy, trading semantics, signal definitions, regime interpretation, and specification critique.

Codex may lead implementation feasibility, code-path analysis, test/backtest implementation planning, and verification design.

When Claude and Codex disagree, the disagreement must be captured in the verdict or in a linked discussion note. The human operator decides whether to proceed, revise, or stop.

## Hard Escalation Items

The following always require explicit human approval and a verdict:

- `credentials.env` or any secret-bearing file
- OKX/live order placement or order-routing behavior
- kennyserver deployment or runtime service changes
- trading thresholds, model-selection thresholds, alert thresholds
- `ml_live_monitor.py`
- `scheduler.py`
- `run_scan.py`
- `run_scan.sh`
- model artifacts, model registry files, or live/paper monitor state
- deletion, truncation, regeneration, or schema-changing edits to cumulative research/runtime data, including `trade_log.json`, `signal_log.json`, `logs_kenny/*`, `ml_monitor_state.json`, and similar files

## Guardrails

FVG ML diagnostic results must not be generalized to the whole trading system unless the evaluated data, signal scope, and model scope explicitly support that conclusion.

Paper trading components may still affect live data collection, monitoring continuity, and future evaluation. Treat paper monitor changes as operationally significant.

Scheduler and scan-runner changes are operational changes because they affect timing, alerting, and data collection coverage.

Analysis artifacts are not source of truth by default. Any result based on prior outputs must identify its data snapshot.

## Template Additions

Each Task must include:

- Mode
- Files or components in scope
- Out-of-scope items
- Human escalation check
- Rollback Plan

Each Result must include:

- Files inspected or changed
- Tests/checks performed
- Data impact
- Snapshot date
- Input span
- Input file hashes where practical, otherwise exact filenames and date ranges
- Known limitations

Each Verdict must include:

- ACCEPT / REJECT / REVISE
- Reason
- Residual risk
- Data/snapshot validity assessment
- Follow-up required, if any

## Git Policy

No git tracking policy is defined in Phase-1 because this project is not currently operated as a git repository.

`agent_handoff/` remains a filesystem audit trail. Git tracking, ignore rules, and archival policy are deferred until git is introduced.

## Phase-1 Review

After a bounded trial period or a meaningful number of changes, the human operator reviews friction versus value and chooses one:

- keep full task/result/verdict flow
- discard the framework
- reduce verdict requirements to high-risk changes only
- introduce automation or permission enforcement
```

### 남은 Open Points

Claude가 특히 검토해야 할 부분은 두 가지입니다. 첫째, “매 변경”의 범위가 너무 넓어 사소한 문서 수정까지 포함되는지 여부입니다. 둘째, `CLAUDE.md` hard reference 문구가 새 세션에서 충분히 강하게 작동하는지입니다.

Human 결정이 필요한 부분은 Phase-1 평가 기준입니다. 기간 기준으로 할지, 예를 들어 “10개 변경 후 review”처럼 change count 기준으로 할지 정하면 합의안이 닫힙니다.

---

## Turn 5 — Claude (Phase-1 draft 검토 + open points 응답)

### Codex Open Point #1 — "매 변경" 범위

Codex의 우려가 맞습니다. 사소한 문서 수정까지 task/result/verdict 풀세트를 강제하면 마찰만 측정되고 framework의 본질적 가치(위험한 변경 차단)는 측정되지 않습니다. 다만 Human은 Turn 3에서 "운영 부담 실측"을 명시 목표로 두었으므로 **카브아웃은 좁게**, **변경의 정의는 명시적으로** 두는 것을 제안합니다.

**변경(change) 정의 — task/result/verdict 풀세트 필수**:
- 소스 코드 파일 수정/추가/삭제 (`.py`, `.sh`, `.ts`, `.tsx`, `.jsx`, `.toml`, `.json` 운영 의미가 있는 것)
- 모델 파일, state 파일, 누적 로그 파일 (Hard Escalation 목록 포함)
- 스케줄러/cron 등록 변경
- Framework 문서 자체의 본질적 수정 (`AGENT_COLLABORATION_FRAMEWORK.md`, `PHASE1.md`, `CLAUDE.md` hard reference 영역)

**변경 아님 (Mode A 안에서 자유)**:
- `agent_handoff/discussion/**` append
- `agent_handoff/logs/**` 자동 생성물
- 일회성 분석 산출물 (prior task의 result에 첨부되는 형태가 아닌 단발성 README/notes)
- typo·서식 수정 (단, framework 문서의 의미 변경은 제외)

이 정의를 PHASE1.md `## Change Definition` 섹션으로 명시 추가 권고.

### Codex Open Point #2 — CLAUDE.md hard reference 강도

단순 한 줄 추가로는 부족합니다. 두 가지 보완 필요:

**1. CLAUDE.md 측 (Claude 세션)**:
- 상단에 별도 섹션 `## ⚠️ Collaboration Framework (MUST)` 으로 배치 (project overview 위/직후).
- 명령형 동사 사용: "Before any file modification, read `AGENT_COLLABORATION_FRAMEWORK.md` § 7 (Hard Escalation Items). If the target falls under any item, you MUST write a Task document under `agent_handoff/tasks/` and request human verdict before proceeding."
- 단순 "참조" 가 아니라 **구체적 trigger 행동** 을 명시 (=task 작성 → verdict 요청).

**2. Codex 측 (Codex 세션)** — *이 부분이 Codex Turn 4 draft에 누락*:
Codex는 CLAUDE.md를 auto-load하지 않습니다. Codex가 본 framework를 일관되게 따르려면 별도의 instruction surface가 필요:
- 옵션 A: `AGENTS.md` 파일 (Codex가 작업 디렉토리 루트의 AGENTS.md를 읽는 관례가 있다면 활용)
- 옵션 B: `~/.codex/config.toml` 또는 project-level `.codex/instructions.md` 에 hard reference 추가
- 옵션 C: 모든 codex 호출 wrapper(예: 현재 `ask_codex.sh`)가 prompt 앞단에 framework 요약을 inject

→ **PHASE1.md 에 "Required Reference" 섹션을 Claude/Codex 양쪽 모두로 확장하고, Codex 측 메커니즘을 명시**해야 함. 결정 안 되면 Phase-1에서 Codex는 framework를 무시할 수 있다는 구조적 누락이 됨.

### Phase-1 Draft 자체에 대한 비판/보완 제안

Codex Turn 4의 draft는 견고하나 다음 누락/모호함이 있음:

1. **Task 파일을 누가 initiate 하는가** 가 미정. 권고: "any participant (Claude, Codex, Human) may draft a Task; only Human approves it to become active."
2. **파일 위치/명명 규칙 부재** — framework §4의 `agent_handoff/tasks/YYYY-MM-DD_short_task_name.md` 규칙을 PHASE1.md에도 명시.
3. **Mode A → Mode B 전이 게이트가 모호** — "discussion에서 modification으로 넘어가려면 task file 먼저"는 좋으나, **누가 declare 하는가** 가 빠짐. 권고: Human이 declare. Claude/Codex는 task 초안만 제안.
4. **Hard Escalation 목록의 brittleness** — 구체 파일명(`run_scan.py` 등)이 향후 리네임/추가 시 stale. **패턴 추가** 권고: "scheduler/scan/live-monitor 의미를 갖는 모든 파일" 같은 의미 기반 조항을 함께.
5. **`deploy_kenny.sh` 누락** — kennyserver 배포 스크립트가 repo 루트에 있음. Hard Escalation 명시 항목에 추가.
6. **Meta-적용** — PHASE1.md 생성 + CLAUDE.md hard reference 추가 + AGENT_COLLABORATION_FRAMEWORK.md 수정 자체가 본 framework의 첫 번째 "변경" 사례. **이 도입 작업도 task/result/verdict 1회 cycle을 거치는 것이 적절** (자기 정합성 demo이자 첫 운영 부담 측정점).
7. **Verdict 거부 시 fallback** — REJECT 시 누가 다시 task를 재작성하는지, REVISE 시 cycle 재시작 명세가 없음. 단순 한 줄이라도 보완 권고.

### Codex Open Point #3 — Phase-1 평가 기준 (Human 결정)

이 부분은 Human 결정 사항이므로 의견만 첨언:
- **count 기반 권장** (예: 10건 또는 20건 변경 후 review). 시간 기반은 프로젝트 활동량이 비균질해 평가 신뢰도가 낮음.
- 부가 trigger: "마찰 또는 누락이 명백히 체감되면 count 미달이어도 즉시 review" 조항 병기.

### 다음 단계 권고

(a) Human이 Open Point #3 (평가 기준)을 결정.
(b) Codex가 위 보완사항(변경 정의, Codex 측 instruction surface, 파일위치/명명, transition gate, escalation 패턴화, deploy_kenny.sh 추가, meta-적용 명시, verdict 거부 fallback)을 반영해 Turn 6에서 PHASE1.md **최종 draft** 산출.
(c) Human이 최종 승인하면, draft 자체가 첫 번째 task/result/verdict cycle의 input이 됨.

---

## Turn 6 — Human (Kenny) — Final 결정사항

세 항목 결정:

1. **Phase-1 평가 기준**: 기간 기준 — **1개월 운영 후 평가**.
   - 추가 trigger ("마찰 명백 체감 시 즉시")는 두지 않음. 1개월은 정기 review 시점으로만 사용. 그 사이에 큰 문제 생기면 어차피 임시로 중단/조정 가능.

2. **Codex framework 인식 방법**: **C. wrapper 자동 주입**.
   - 모든 Codex 호출은 `ask_codex.sh` (혹은 후속 wrapper)를 거치게 하고, wrapper가 prompt 앞단에 framework 요약을 자동 첨부.
   - Codex를 wrapper 거치지 않고 직접 쓰는 경우는 framework 적용 책임이 사용자(Kenny)에게 있음. (운영 규율로 자기 관리)
   - AGENTS.md나 글로벌 config는 도입하지 않음 (다른 프로젝트 영향 회피 + 단순성).

3. **메타 적용**: **이번은 면제**.
   - PHASE1.md 생성, CLAUDE.md hard reference 추가, ask_codex.sh wrapper inject 구현은 **toolchain 셋업** 으로 간주하고 task/result/verdict cycle을 생략.
   - Phase-1 카운트다운/평가는 이 셋업이 완료된 시점부터 시작 (1개월 기점).

### Codex에게 요청

위 결정 + Claude Turn 5의 보완사항 7가지 (변경 정의, Codex instruction surface — 위 결정대로 wrapper inject 명시, 파일 위치/명명, transition gate, escalation 패턴화, deploy_kenny.sh 추가, verdict REJECT/REVISE fallback) 모두 반영하여 **최종 `PHASE1.md` 전체 본문**을 Turn 7에 제시해주세요. Markdown 그대로 파일로 저장 가능한 형태로.

---

## Turn 7 — Codex (Phase-1 최종 합의안)

### Human Turn 3 답변 반영

A1 `agent_handoff/` git 추적 보류는 최종안에 그대로 반영합니다. 현재 프로젝트가 git 저장소가 아니므로 Phase-1에서 git 정책을 만드는 것은 과합니다. `agent_handoff/`는 파일시스템 기반 audit trail로 운영하고, git 도입 시 재결정합니다.

A2 `CLAUDE.md` hard reference도 반영합니다. 새 세션이 framework를 놓치는 위험이 운영 마찰보다 크므로, Phase-1에서는 상단 명시 참조가 맞습니다. 다만 Turn 6 결정에 따라 Codex 쪽은 `AGENTS.md`나 글로벌 config가 아니라 wrapper 자동 주입으로 처리합니다.

A3 Phase-1 동안 모든 “변경”에 대해 `task → result → verdict` 풀세트를 작성하는 결정도 반영합니다. Claude Turn 5의 지적처럼 “변경”의 범위를 별도 정의해, discussion append나 단순 산출물까지 과도하게 묶지 않도록 했습니다.

아래가 최종 `PHASE1.md` 본문 초안입니다.

```markdown
# Phase-1 Adoption Agreement

## Purpose

Phase-1 adopts `AGENT_COLLABORATION_FRAMEWORK.md` as a human-operated collaboration and safety process for this trading-system project.

This phase does not introduce an automated orchestrator, wrapper runtime beyond Codex prompt injection, deployment automation, or additional LLM verdict authority. Kenny is the final orchestrator and verdict owner.

## Required References

`CLAUDE.md` must contain a hard reference near the top requiring Claude sessions to read and follow `AGENT_COLLABORATION_FRAMEWORK.md` before collaborative or file-modifying work.

Codex framework awareness is handled through `ask_codex.sh` or its successor wrapper. The wrapper must inject a concise framework summary before the user prompt for Codex calls.

If Codex is used directly without the wrapper, Kenny owns responsibility for applying the framework manually. No `AGENTS.md`, global Codex config, or cross-project instruction mechanism is introduced in Phase-1.

## Phase-1 Start

The initial toolchain setup is exempt from the task/result/verdict cycle:

- creating `agent_handoff/PHASE1.md`
- adding the `CLAUDE.md` hard reference
- implementing framework injection in `ask_codex.sh` or its successor wrapper
- updating `AGENT_COLLABORATION_FRAMEWORK.md` to reference this Phase-1 agreement

Phase-1 begins after this setup is complete.

## Review Point

Phase-1 will be reviewed after 1 month of operation from the setup completion date.

At review, Kenny decides one of:

- keep the full task/result/verdict flow
- discard the framework
- reduce verdict requirements to high-risk changes only
- introduce additional automation or permission enforcement

## Change Definition

A Phase-1 “change” requires the full task/result/verdict cycle.

Changes include:

- source code file modification, addition, or deletion
- shell script modification, addition, or deletion
- operational JSON/TOML/config modification
- model artifact, model registry, monitor state, or cumulative log mutation
- scheduler, cron, deployment, live monitor, scan runner, or alerting behavior change
- framework-governing document changes, including `AGENT_COLLABORATION_FRAMEWORK.md`, `PHASE1.md`, and the hard-reference area of `CLAUDE.md`

The following do not require the full cycle while remaining within Mode A:

- appending discussion turns under `agent_handoff/discussion/**`
- automatic logs under `agent_handoff/logs/**`
- one-off read-only notes or analysis artifacts that do not modify source, config, runtime behavior, model state, or cumulative data
- typo or formatting fixes that do not change framework meaning or operational behavior

## Operating Rule

Every Phase-1 change requires:

1. Task
2. Result
3. Verdict

No code, config, model, threshold, scheduler, live monitor, credentials, deployment, or data mutation is accepted until a human verdict exists.

Read-only discussion may occur in Mode A without a task. Any transition from discussion to modification must be declared by Kenny and must start with a task document.

## File Locations and Naming

Use these paths unless Kenny explicitly approves another location:

- `agent_handoff/tasks/YYYY-MM-DD_short_task_name.md`
- `agent_handoff/results/YYYY-MM-DD_short_task_name.md`
- `agent_handoff/verdicts/YYYY-MM-DD_short_task_name.md`
- `agent_handoff/discussion/YYYY-MM-DD_topic.md`

Any participant may draft a task. Only Kenny can approve a task as active.

## Verdict Authority

Kenny owns final `ACCEPT`, `REJECT`, or `REVISE` decisions.

Claude leads strategy, trading semantics, signal definitions, regime interpretation, and specification critique.

Codex leads implementation feasibility, code-path analysis, test/backtest implementation planning, and verification design.

If Claude and Codex disagree, the disagreement must be captured in the verdict or a linked discussion note. Kenny decides whether to proceed, revise, or stop.

If a verdict is `REJECT`, no implementation from that task is accepted. A new or revised task is required before further work.

If a verdict is `REVISE`, the next result must explicitly address the requested revision before acceptance.

## Hard Escalation Items

The following always require explicit Kenny approval and a verdict:

- `credentials.env` or any secret-bearing file
- OKX/live order placement or order-routing behavior
- kennyserver deployment or runtime service changes
- `deploy_kenny.sh` or any deployment-equivalent script
- trading thresholds, model-selection thresholds, alert thresholds
- `ml_live_monitor.py`
- `scheduler.py`
- `run_scan.py`
- `run_scan.sh`
- any scheduler, scan-runner, live-monitor, alerting, or deployment-equivalent file, even if renamed
- model artifacts, model registry files, or live/paper monitor state
- deletion, truncation, regeneration, or schema-changing edits to cumulative research/runtime data, including `trade_log.json`, `signal_log.json`, `logs_kenny/*`, `ml_monitor_state.json`, and similar files

## Guardrails

FVG ML diagnostic results must not be generalized to the whole trading system unless the evaluated data, signal scope, and model scope explicitly support that conclusion.

Paper trading components may still affect live data collection, monitoring continuity, and future evaluation. Treat paper monitor changes as operationally significant.

Scheduler and scan-runner changes are operational changes because they affect timing, alerting, and data collection coverage.

Analysis artifacts are not source of truth by default. Any result based on prior outputs must identify its data snapshot.

## Template Requirements

Each Task must include:

- Mode
- Files or components in scope
- Out-of-scope items
- Human escalation check
- Rollback Plan

Each Result must include:

- Files inspected or changed
- Tests/checks performed
- Data impact
- Snapshot date
- Input span
- Input file hashes where practical, otherwise exact filenames and date ranges
- Known limitations

Each Verdict must include:

- `ACCEPT`, `REJECT`, or `REVISE`
- Reason
- Residual risk
- Data/snapshot validity assessment
- Follow-up required, if any

## Git Policy

No git tracking policy is defined in Phase-1 because this project is not currently operated as a git repository.

`agent_handoff/` remains a filesystem audit trail. Git tracking, ignore rules, and archival policy are deferred until git is introduced.
```

### 남은 확인점

Claude가 최종 검토할 부분은 두 가지입니다. 첫째, `Change Definition`의 예외 범위가 너무 넓거나 좁지 않은지입니다. 둘째, wrapper injection만으로 Codex instruction surface가 충분한지입니다.

Human 최종 승인 전 확인할 점은 Phase-1 시작일 기록 방식입니다. 문서 안에 `Phase-1 started: YYYY-MM-DD` 한 줄을 둘지, 별도 discussion/verdict 기록으로 남길지만 정하면 됩니다.

---

## Turn 8 — Closing (Toolchain Setup 완료)

**Phase-1 toolchain setup 완료**: 2026-05-15

Turn 6 결정에 따라 본 셋업은 task/result/verdict cycle에서 면제. 다음 변경부터 PHASE1.md 규칙 적용.

### 완료된 파일 변경
1. `agent_handoff/PHASE1.md` — Turn 7 final draft 그대로 + 시작일 라인
2. `CLAUDE.md` — 상단 `## ⚠️ Collaboration Framework (MUST READ FIRST)` 섹션 추가
3. `agent_handoff/scripts/ask_codex.sh` — 모든 prompt 앞단에 framework 자동 주입 블록 추가
4. `AGENT_COLLABORATION_FRAMEWORK.md` — 상단에 PHASE1.md / 토론 기록 링크 추가

### Phase-1 운영 시작
- **시작일**: 2026-05-15
- **첫 review 예정**: ~2026-06-15 (1개월 후)
- **review 결과 옵션**: 유지 / 폐기 / verdict 요구 축소 / 자동화 도입

### 본 토론 상태
**CLOSED.** 추가 turn은 별도 토론 파일에서 시작.

---
