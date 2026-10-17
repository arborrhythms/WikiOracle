# Item 6 closing mechanism — landing receipt

Finalized October 17, 2026. BasicModel main lands one commit,
[`52ea5ebfb05c250392eb984d890acefad77f566f`](https://github.com/arborrhythms/BasicModel/commit/52ea5ebfb05c250392eb984d890acefad77f566f),
from `51f069c30`, following [plan §16–17](../../basicmodel/doc/plans/2026-10-10-item-6-stored-idea-generativity.md#163-disposition-close-item-6-as-a-mechanism-landing).
This WikiOracle commit records the submodule bump and the result of sweeping
that exact BasicModel commit. **Mechanism accepted; no identity-learning claim.**

## Final gates

| Gate | Result |
|---|---|
| Full default sweep on `52ea5ebfb` | **5,788/5,788 completed; 5,454 passed, 332 skipped, 1 XFAIL, 1 failed**, 465.20 s. Unique case counts. |
| Unexpected failures on final commit | **0** |
| c: `test_forced_ordinary_answer_fills_committed_question_without_its_own_episode` | **FAIL, carried:** the filled answer is marker-headed and does not match `five`. Assertion unchanged. |
| Paired zero-cost: `test_both_training_trials_share_bootstrap_snapshot` | Passes this sweep; **counterexample remains open**. It failed the preceding sweep with `reconstruction.content = .0517327`; the same counterexample was previously reproduced on accepted main. No production change between these two sweeps repairs it. |
| Cleared-cache word overlap | **XFAIL**, carried; still adverse to 6.1's XPASS. |
| Reference-close controlled cases | **12/12 pass**, including **4/4 same-kind cases** after the fourth close. |
| Exact NOT/OR reconstruction | Pass, unchanged **`R == [0.]*4`**. |
| Noun sparse-code retirement | Pass: no A `encode`, `loss` or `observe`; B's sparse energy does not train A signatures. |
| Native close, optimizer ownership, checkpoint | Pass through a real clause index and kept mint. |
| Trained-artifact departure coverage | Pass on the accepted paired warm-up artifact; stated miss-probability bound **≤ 10⁻⁶** over its frozen learned menus. |
| Older XOR certificates restored to default | **7/7 pass**: two exact CLI, two grammar, three MM convergence/signal certificates. Assertions and budgets unchanged. |

[Final sweep diagnostics](2026-10-16-item6-landing/final-sweep.json).
The command used the default bounded runner with `RUN_SLOW` unset and
`BASICMODEL_EXPLORATION_ARTIFACT=output/item6-orders-paired-accepted-code-20261015`.
Artifact/exposure requirements remain skip conditions, not passes.

## Retirements and tiers

| Contract or path | Disposition |
|---|---|
| Nearest-left/context stash: four failing tests | Deleted; the bind marker's current value/gradient behavior is checked at its deferred interface. |
| Three old binding grammar fixtures | Deleted. |
| Selected-mint admission: three failing cases | Deleted with the retired gate; no replacement admission gate on A. |
| Synthetic owner without a native store: one failing test | Deleted; native allocation, bounded access and checkpoint behavior are covered through the close. |
| Old live binding slab: one failing test | Rewritten to preserve grouped/separate operand values and gradients; no slab gradient is expected from deferred reference. |
| Unused `bind_resolver`, `selected_individual_references`, noun sparse-code tests | Deleted with the retired mechanisms, including their previously passing tests. |
| A and prediction | A stores signatures and witnesses. Noun population energy, source re-encoding and noun-coordinate prediction loss are removed. |
| B | Legacy sparse innovation coding remains, using detached A signatures. The per-individual temporal-difference teacher is not implemented. |
| Historical 53 slow contracts | **52 live cases marked slow and skipped by default; one already retired** by the prior departure-coverage decision. All live tests remain in the harness for `RUN_SLOW=1`. |
| Historical 23 timed certificates | **22 live default cases; one already retired** and replaced by the default trained-artifact coverage certificate. Other learning certificates stay default regardless of time. |

The twelve reported retired-contract failures are removed or ported; none is
carried red. [Tier inventory](2026-10-16-item6-landing/tier-audit.json).

An initial sweep at archived candidate
[`318797103`](https://github.com/arborrhythms/BasicModel/commit/318797103648addc1279cae257680a0e604ec071)
completed 5,788 cases: **5,452 passed, 332 skipped, 1 XFAIL, 3 failed** in
466.56 s. Besides the two carried counterexamples, the packed-memory fixture
incorrectly required two observation-kind rows from an untrained free parse.
A diagnostic reproduction selects unresolved binds and stores both sentences
as questions. The replacement checks two distinct closing addresses, retained
at distinct source positions, with valid observation/question kinds and no
estimates. It preserves the storage requirement without requiring a particular
untrained reading. The unseeded focused check and the retained failing diagnostic
both pass after that fixture port. No production source or learning certificate
was changed for it. That unexpected failure required the second sweep on the
amended final commit; the first is retained, not replaced by a clean rerun.

[Initial failure diagnostics](2026-10-16-item6-landing/initial-sweep.json),
[before](2026-10-16-item6-landing/item6-packed-probe-2.log),
[after](2026-10-16-item6-landing/item6-packed-probe-2-fixed.log),
[focused regression](2026-10-16-item6-landing/item6-packed-closing-repair.log).
Commits are the archive; no source tarball or integrity manifest is published.

## Learning carried to 5.5 and item 0

| Question | Status |
|---|---|
| Native balanced identity | Not rerun. Accepted measurement remains **0/146 bindings, 0/20 row pairs, zero A columns/witnesses**; all 556 held-out closed meanings were zero with `equal`-only kept programs. |
| Stage 4e, constituents | **Not built; first carried pass.** Gate: held-out free brackets and one occurrence per singular NP at its order reduction. No native identity run until it passes. |
| VP vectors by temporal difference | **Not built.** Follows usable constituent/identity readings; legacy B is not this teacher. |
| Order-2 kinds | **Not built.** Neither proposed design for their intension is selected. |
| Remaining learning sequence | Stage 4e → identity matching and row pairs → VP temporal differences → direct-operand word classes; order-2 kinds later. |
| Other carried findings | Stored-idea recovery beyond two words; order CE gates; relation trace **2/4**; free readback **0/4**; MM grammar recovery; compiled retention; c and the paired counterexample above. |

[Todo](../../basicmodel/todo.md) marks item 6 Done with the shared bounded
inverse and type families, forward discard with the search exemption,
positional operands and orders from stamps, paired stages 1–2, and reference
at the close with fixed mint/bind operators and revision. The requested theory,
training, testing and specification documents are included, along with their
referenced review/toy documents. No rule is claimed retired by a passing native
identity lesson.
