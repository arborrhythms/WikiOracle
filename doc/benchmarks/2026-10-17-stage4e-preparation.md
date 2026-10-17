# Stage 4e preparation landing

BasicModel main lands `d080b632d`: the reviewed constituent corpus, grader,
driver and failed first-run receipt, including the subsequent review.
This is preparation, with **no learning claim**.

The [first-run receipt](../../basicmodel/doc/benchmarks/2026-10-17-stage4e/README.md)
reports 8/32 exact brackets, 0/48 NP occurrences, 0/48 reductions under the
original gate, zero duplicate writes, and 8/8 unlowered controls (vacuous).
Its source sweep had 5,460 passes, 333 skips, one XFAIL and the carried c
failure; every pre-existing outcome matched the accepted item-6 baseline.
No additional sweep was run to land this unchanged reviewed preparation.

The [next pass](../../basicmodel/doc/plans/2026-10-17-item5-5-start.md#review-of-the-first-stage-4e-run-claude-2026-10-17--gate-failed-for-a-structural-reason-fix-before-any-rerun)
sets determiner output orders by construction, diagnoses native cases and
chooser credit, then reruns the same fixed stage-4e budget once. Identity
and the clock/chain/surface changes remain gated.
