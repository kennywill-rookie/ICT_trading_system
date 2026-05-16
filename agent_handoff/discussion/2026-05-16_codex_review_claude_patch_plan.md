# Codex Review Request: Claude Patch Plan Evaluation

## Context

Claude proposed the following modification plan for the ML FVG live monitor and BTC inverse-filter decision process.

User wants Codex to review whether this plan is technically sound and operationally safe.

## Claude Proposal

1. Apply P0 patch first:
   - Set `LOOKBACK_15M = 800`
   - Use OKX `history-candles` paging
   - Goal: unfreeze `higher_tf_trend`

2. Recollect live data for 1-2 weeks, then remeasure Spearman correlation.

3. If BTC negative rho remains:
   - ETH/SOL: operate with the normal model, because they are expected to recover after HTF restoration.
   - BTC: adopt option A, inverse filter `proba <= p20`.
   - BTC inverse position size should be reduced to 20-30%.
   - Continue only while permutation test remains `p < 0.05`.
   - In parallel, retrain a BTC-specific model including the 2024 trend regime.

## Codex Evaluation

The overall direction is correct. The plan first fixes the measurement layer, then separates BTC from ETH/SOL, then treats BTC inverse as a conditional candidate rather than a permanent rule. That is the right sequencing.

However, based on the current codebase, item 1 is likely no longer a source-code patch task. The current local code already appears to include:

```text
LOOKBACK_15M = 800
history-candles paging in fetch_recent_15m()
```

Therefore P0 should be defined as a deployment and verification task, not only a code patch.

## Recommended P0 Completion Criteria

P0 should be considered complete only when live or paper monitor logs confirm:

```text
new FVG events >= 5
higher_tf_trend unique values are not only [0.5]
higher_tf_trend moves across a non-trivial 0-1 range
proba standard deviation recovers versus the frozen period
```

If the local code is patched but the server process still runs the old version, the bug remains operationally active.

## Forward Sample Requirements

The 1-2 week window is acceptable as a calendar target, but decision quality should be based on sample count.

Recommended minimum:

```text
all new FVG events >= 50
BTC new FVG events >= 20
prefer BTC new FVG events >= 30 before making a trading decision
```

If BTC has fewer than 20 new events, Spearman should be treated as diagnostic only, not as a decision gate.

## Metrics To Remeasure

Do not rely on Spearman alone. Recompute all of the following after P0:

```text
Spearman(proba, actualR)
bottom-20 / bottom-30 / top-30 bucket WR
bottom-20 / bottom-30 / top-30 avgR
bottom-20 / bottom-30 / top-30 PF
MDD by bucket
asset split: BTC / ETH / SOL
direction split: Long / Short
higher_tf_trend distribution
proba distribution and std
```

## BTC Inverse Filter Review

Claude's suggestion to use BTC inverse `proba <= p20` is directionally reasonable, but `p20` alone may be too narrow because sample count will be small.

Recommended structure:

```text
BTC inverse p20:
  high-conviction bucket
  very small size
  track separately

BTC inverse p30:
  broader candidate bucket
  better for statistical accumulation
  paper-only or smaller live size until confirmed
```

Suggested sizing:

```text
p20: 20-30% of normal size
p30: 10-20% of normal size, or paper-only until enough sample accumulates
```

## BTC Inverse Maintain / Reject Criteria

Permutation `p < 0.05` is useful, but should not be the only gate. With small samples, p-values can be unstable.

Recommended maintain criteria:

```text
n >= 30
WR >= 58%
PF >= 1.5
avgR > +0.15R
MDD materially better than high-proba BTC bucket
Spearman rho remains < 0
permutation p < 0.05, or rolling bucket performance remains consistent
```

If these criteria fail after P0 live recollection, BTC inverse should remain paper-only or be disabled.

## ETH/SOL Normal Model

Separating ETH/SOL from BTC is appropriate. The live analysis suggests BTC has a distinct regime-mismatch problem, while ETH/SOL may recover after the HTF feature is restored.

However, ETH/SOL should still be revalidated after P0. Do not assume recovery without fresh post-patch evidence.

Recommended gate for ETH/SOL normal model:

```text
post-P0 top-30 bucket PF > 1.3
post-P0 top-30 avgR > 0
no major calibration inversion
proba distribution no longer collapsed
```

## BTC-Specific Retraining

Strongly agree with parallel BTC-specific retraining.

BTC model should include:

```text
2024 trend regime
2025 range / weak regime
2026 live bullish regime if available
regime features
asset-specific calibration
walk-forward validation
separate evaluation for Long FVG and Short FVG
```

The observed BTC issue is probably not "FVG is bad." It is more likely that the model score direction changes by regime. A BTC-specific or regime-gated model is the cleaner long-term solution.

## Final Recommendation

Adopt Claude's proposal with the following modifications:

```text
1. Treat P0 as deploy + live verification, not just code patch.
2. Use sample-count gates, not only 1-2 calendar weeks.
3. Remeasure Spearman plus WR, avgR, PF, MDD, bucket calibration, and distributions.
4. Track BTC inverse p20 and p30 separately.
5. Keep BTC inverse small-size or paper-only until post-P0 data confirms it.
6. Validate ETH/SOL after P0 before normal operation.
7. Continue BTC-specific retraining in parallel.
```

Bottom line:

```text
Claude's plan is directionally correct.
BTC inverse is a high-priority candidate, not an immediately permanent trading rule.
The next real decision must be made on post-P0, non-frozen live data.
```
