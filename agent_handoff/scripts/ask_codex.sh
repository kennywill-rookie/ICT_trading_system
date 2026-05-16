#!/usr/bin/env bash
# ask_codex.sh — Append a Codex turn to a discussion document.
#
# Usage:
#   ask_codex.sh                                # default doc, resume --last
#   ask_codex.sh <discussion.md>                # explicit doc, resume --last
#   ask_codex.sh <discussion.md> <session_id>   # resume specific session uuid
#   ask_codex.sh <discussion.md> --fresh        # NEW codex thread (read-only sandbox)
#
# Behavior:
#   - Auto-detects the next turn number from existing "## Turn N — ..." headers.
#   - Embeds the FULL current discussion document into the prompt (so codex sees
#     the most recent Human turn even if its session memory is stale).
#   - Captures `--output-last-message`, appends as the new turn.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

DOC="${1:-agent_handoff/discussion/2026-05-15_framework_review.md}"
SESSION_ARG="${2:---last}"

if [[ ! -f "$DOC" ]]; then
  echo "ERROR: discussion doc not found: $DOC" >&2
  exit 1
fi

# Determine next turn number
NEXT_TURN=$(grep -cE "^## Turn [0-9]+ —" "$DOC")
NEXT_TURN=$((NEXT_TURN + 1))

# Determine which agent posted the LAST turn (for "respond to" framing)
LAST_TURN_HEADER=$(grep -E "^## Turn [0-9]+ —" "$DOC" | tail -1)
LAST_TURN_AGENT=$(echo "$LAST_TURN_HEADER" | sed -nE 's/.*— ([A-Za-z]+).*/\1/p')

TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="agent_handoff/logs/codex_${TS}.log"
LAST_MSG_FILE="agent_handoff/logs/codex_${TS}_last.md"
PROMPT_FILE="agent_handoff/logs/codex_${TS}_prompt.txt"
mkdir -p agent_handoff/logs

# --- Compose the prompt (framework injection + full discussion embedded) ---
{
  # === Framework auto-injection (PHASE1 requirement) ===
  cat <<'FRAMEWORK_INJECTION_EOF'
===== AGENT FRAMEWORK CONTEXT (auto-injected by ask_codex.sh) =====
Your activity in this project is governed by:
  - AGENT_COLLABORATION_FRAMEWORK.md   (full framework)
  - agent_handoff/PHASE1.md            (active phase agreement; read at start)

Hard rules (Phase-1, active since 2026-05-15):
  1. HARD ESCALATION — These files/behaviors REQUIRE Kenny's explicit verdict
     before any modification: credentials.env, deploy_kenny.sh, ml_live_monitor.py,
     scheduler.py, run_scan.py, run_scan.sh, model files, monitor state,
     trade_log.json, signal_log.json, logs_kenny/*, OKX/live order code,
     kennyserver deployment, trading/model/alert thresholds, cumulative log
     deletion or schema change.
  2. CHANGE CYCLE — Any source/script/config/model/log mutation requires the
     full task → result → verdict document set under agent_handoff/{tasks,
     results, verdicts}/. Discussion appends and logs are exempt.
  3. ROLES — Codex leads implementation feasibility, code-path analysis, test/
     backtest implementation, verification design. Strategy/trading semantics
     are Claude-lead.
  4. MODE — Mode A = read-only thinking (no task needed). Mode B = modification
     (task file required, started/declared by Kenny).
  5. If unsure whether something falls under hard escalation, ASK rather than act.
===== END FRAMEWORK CONTEXT =====

PROMPT FOR THIS CALL FOLLOWS:

FRAMEWORK_INJECTION_EOF

  cat <<PROMPT_HEADER_EOF
You are participating in a structured 3-way Mode A (read-only direct) discussion with Claude
and the human operator (Kenny). The topic is whether to adopt
AGENT_COLLABORATION_FRAMEWORK.md for this trading-system project.

The discussion has already had several turns. The LAST turn was posted by ${LAST_TURN_AGENT}.
Your job now is to produce TURN ${NEXT_TURN} as Codex, directly responding to the most
recent turn(s). DO NOT repeat your previous turn(s). DO NOT regenerate Turn 2.

MODE A CONSTRAINTS (strict):
- Do NOT edit ANY files. Do NOT touch credentials.env. Do NOT run/deploy/trade.
- Do NOT use apply_patch / write tools / install commands. Read-only thinking only.
- You may use the shell tool to read files (e.g., \`cat AGENT_COLLABORATION_FRAMEWORK.md\`)
  but you don't strictly need to — the discussion content is embedded below.

OUTPUT FORMAT (very important):
- Output ONLY the markdown content of YOUR ONE turn. No preamble outside markdown.
- Start with EXACTLY this header line (replace the summary with your own ≤ 10-word summary):

    ## Turn ${NEXT_TURN} — Codex (one-line summary)

- Then your sections. Korean is the working language; use Korean.
- Target 400–700 words.
- End the turn with a line containing exactly:

    ---

WHAT THIS PARTICULAR TURN SHOULD DO:
- Acknowledge / react to the Human's answers in Turn 3 (A1, A2, A3) point-by-point.
- Draft a concrete Phase-1 adoption agreement that incorporates:
    * Claude Turn 1 critique + 1-step proposal
    * Your own Turn 2 additions (§8 guardrails, Data impact, snapshot rules)
    * Human Turn 3 decisions (no git tracking for now; CLAUDE.md hard reference;
      verdict produced for every change in Phase-1)
- The draft should be a short, copy-pasteable spec section that could become an
  appendix to AGENT_COLLABORATION_FRAMEWORK.md or its own \`agent_handoff/PHASE1.md\`.
- Identify any remaining open points that need Claude review or Human decision
  before this can be finalized.

===== BEGIN DISCUSSION DOCUMENT (${DOC}) =====
PROMPT_HEADER_EOF
  cat "$DOC"
  cat <<'PROMPT_FOOTER_EOF'
===== END DISCUSSION DOCUMENT =====

Now produce Turn N as instructed above. Output only the turn markdown.
PROMPT_FOOTER_EOF
} > "$PROMPT_FILE"

echo "→ Invoking codex"
echo "  session arg:  $SESSION_ARG"
echo "  doc:          $DOC"
echo "  next turn:    $NEXT_TURN (last turn was by: $LAST_TURN_AGENT)"
echo "  prompt size:  $(wc -c < "$PROMPT_FILE") bytes"
echo "  last-msg:     $LAST_MSG_FILE"
echo "  full-log:     $LOG_FILE"
echo ""

if [[ "$SESSION_ARG" == "--fresh" ]]; then
  codex exec \
    --sandbox read-only \
    --skip-git-repo-check \
    --output-last-message "$LAST_MSG_FILE" \
    - < "$PROMPT_FILE" 2>&1 | tee "$LOG_FILE"
elif [[ "$SESSION_ARG" == "--last" ]]; then
  codex exec resume \
    --last \
    --skip-git-repo-check \
    --output-last-message "$LAST_MSG_FILE" \
    - < "$PROMPT_FILE" 2>&1 | tee "$LOG_FILE"
else
  codex exec resume \
    "$SESSION_ARG" \
    --skip-git-repo-check \
    --output-last-message "$LAST_MSG_FILE" \
    - < "$PROMPT_FILE" 2>&1 | tee "$LOG_FILE"
fi

CODEX_STATUS=${PIPESTATUS[0]}

if [[ ! -s "$LAST_MSG_FILE" ]]; then
  echo ""
  echo "WARN: codex produced no last-message (exit $CODEX_STATUS). See $LOG_FILE" >&2
  exit 2
fi

# Sanity check: did codex echo the right turn number in its header?
FIRST_HEADER=$(grep -m1 -E "^## Turn [0-9]+" "$LAST_MSG_FILE" || true)
echo ""
echo "Detected response header: $FIRST_HEADER"
if [[ "$FIRST_HEADER" != *"Turn ${NEXT_TURN}"* ]]; then
  echo "WARN: response header does not match expected 'Turn ${NEXT_TURN}'." >&2
  echo "      Output NOT auto-appended. Review $LAST_MSG_FILE and append manually." >&2
  exit 3
fi

{
  echo ""
  cat "$LAST_MSG_FILE"
  echo ""
} >> "$DOC"

echo ""
echo "✓ Appended Codex Turn ${NEXT_TURN} to: $DOC"
