# Stage 4e student-state preparation

BasicModel `main` lands `63ece2e1e` after Claude's source and final reviews.
This is preparation, with no learning claim.
The corrected 16-presentation pilot passes: wait CE **5.775928 → 2.680222**,
fold CE **7.941597 → 3.586233**, with eight paired updates.

The full run uses the same order checkpoint and seed: **144 training / 40
held-out**, 72 updates. It fails: **0/32** main brackets, **8/48** matching NP
occurrences, **7/48** lowering certificates, **19** unexpected occurrences,
zero duplicates/collisions, and **3/8** clean controls. Source order is **40/40**.
No constituent or identity learning claim; no identity run.

The read-only stage-3 diagnostic finds that the saved checkpoint passes
two-word CE after the four-word lesson (**.000224–.000227**); four-word CE
remains **.016268–.016439**, above .01, with live gradients and no saturation.
The original training trace was still improving at its fixed budget's end.
No warm-up repeat, optimizer update or budget extension is added.

The one final default sweep completes **5,803 cases: 5,466 passed, 335 skipped,
one XFAIL, one carried c failure** (unresolved subject before `five`). Exact
NOT/OR and paired zero-cost pass; their broader findings remain open.

[BasicModel receipt](../../basicmodel/doc/benchmarks/2026-10-17-stage4e-student-states/README.md)
and [current hand-off](../../basicmodel/doc/plans/2026-10-17-handoff-5-5.md).
