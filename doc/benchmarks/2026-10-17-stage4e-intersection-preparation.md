# Intersection/pressure preparation landing

BasicModel main lands the reviewed intersection/pressure candidate and its
review. This is preparation, with **no learning claim**.

The [receipt](../../basicmodel/doc/benchmarks/2026-10-17-stage4e-intersection/README.md)
records the moving-CE pilot and completed fixed-budget rerun: 0/32 exact
main brackets, 10/48 matching NP occurrences, 0/48 complete lowering
certificates, 22 unexpected occurrences, zero duplicates/collisions and
8/8 clean unlowered controls. The default sweep completed 5,800 cases:
5,466 passed, 333 skipped, one XFAIL, zero failures. No additional sweep
was run to land the unchanged reviewed preparation.

The next pass runs stage 3 before 4e, reports its order gate, teaches brackets
on the student's actual compose states, and accounts for the optimizer-call
budget. A 16-presentation pilot gates the one full rerun. Identity and the
5.5 clock/chain/surface changes remain gated.
