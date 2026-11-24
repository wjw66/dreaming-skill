# Behavioral Acceptance

Script tests establish bookkeeping and edit invariants. They cannot prove that a model extracted the right facts or interpreted their scope correctly. Run this separate exercise after substantive changes to the skill.

## Actual-artifact acceptance before scores

Separate a skill being installed, being loaded, and completing its workflow. For the execution regression, name `$dreaming-skill` explicitly; test clear natural-language discovery separately. Preserve the explicit-only host policy. A trial that never loaded the skill diagnoses discovery, not compliance with its body.

In an isolated wiki/registry, require all of the following before calling a positive trial successful:

- The execution trace shows actual helper use for setup (when needed), scan, stage, and `status --run RUN`, not just files or a final response claiming those steps happened.
- The evaluator runs `status --run RUN` itself using the helper-produced latest staged run. It must exit zero with `pending_review` or `no_changes`, a real sealed revision, source checkpoint, review, and diff. Plain `status` is not this gate.
- Formal pages still match the captured pre-run base before any approval. No test gives the model advance permission to merge an unknown version. The helper must reject an unsealed run, modified review/diff, stale base, or mismatched checkpoint.
- Retained citations have exact original-language quotes in both frozen events and named local evidence pages. A correct `review.json` quote with only a paraphrase on the evidence page fails.
- Read actual semantic, event, and evidence pages against held-out source expectations: distinguish two named tools with related memory/recording goals, preserve their different organization choices, and do not turn one tool's history into the other's origin. Do not infer causes from a problem report alone. Translations and summaries are not verbatim quotes.
- Check meaning on every page, including direction and negation, stated completion versus requests, and unrelated conversations merged into a timeline. A mechanically verified proposal can still fail semantic acceptance. Count that as a failure even if a model judge or workflow-only custom grader passes it.
- A read-only reflection request answers with evidence while preserving the input wiki byte-for-byte and never starting consolidation. Useful human reflection and future-agent reuse are both outcomes to assess.

Keep the framework's unmodified scores and this acceptance result separately. A high answer score cannot override a failed workflow or source-fidelity gate. The helper's structural verification is not a semantic evaluator: `semantic_truth_verified` and `human_approval_verified` remain false. Avoid tests that only check headings, file counts, or the agent's self-report.

When using SkillEvaluator, capture produced pages in a separate filesystem observer before its sandbox cleanup; default judges may see only selected trajectory evidence. Supplement those scores with the checks above. An observer that reports “documents exist” is not a full-workflow or fact-correctness gate.

Assess selection as well as recall. Give a reader realistic future choices: how to adapt an explanation for the user, which tradeoff they previously accepted, what feedback should change the next attempt, and which view remains provisional. Check that person-related entries come first, important concrete constraints survive, and routine outputs/status do not crowd them out. An exact answer about an incidental past activity is not by itself a reason to store it. Do not optimize the wiki into an exhaustive log merely to improve retrospective question scores.

## Isolated three-wave exercise

Use `tests/fixtures/memory-waves.json` as raw input. The authoring agent must not read `memory-expectations.json`; reserve it for an independent evaluator.

Fixture timestamps belong to a simulated timeline, independent of the machine capture clock. Keep capture time separate from source event time, label the exercise synthetic, and report discrepancies rather than presenting the fixture as verified real-world chronology. The temporal test concerns ordering within that simulated history.

1. Create a temporary directory, registry, and wiki outside the repository. Never initialize the real user's registry or import their real history during this exercise.
2. Materialize the first wave as a supported JSON export with the fixture's session ID and events. Invoke the actual skill, read the normalized inputs, and prepare/stage the wiki. Stop and report the exact pending revision, review, and diff.
3. The test controller inspects that concrete review, then explicitly approves that revision as the synthetic fixture user. Apply only this approved revision. This exercises updates against a real formal base without granting advance permission for unknown revisions.
4. Append wave two to the same export. Invoke the skill again. Confirm that only its new event is emitted, the preceding proposal is available as context, existing pages use exact patches, and formal pages remain at wave one while wave two is pending.
5. Append wave three. Invoke again without approving wave two. Confirm that pending content is inherited, only the new increment is analyzed, and the new complete review includes all outstanding differences from formal memory. Stop at pending review.
6. Give a fresh evaluator only the candidate wiki, task questions, and then the expected outcomes for grading. It should locate current rules, scope, decision chronology, source evidence, and unresolved questions without consulting raw transcripts first. It may follow evidence links to verify an answer. Do not let the author grade its own result.

Questions for the reader:

- What export rules apply to each project/version/environment?
- Was the proposed Wiki layout accepted, and where is the evidence?
- What happened historically, and what is current policy?
- What remains unresolved or unverified?
- Which evidence supports each answer?

## Checks and release gate

- Every extracted candidate has a legal disposition and real evidence reference; ignored material and zero-change inputs have reasons.
- Source increments are not replayed; failed sources remain retryable; cross-file continuations are not omitted.
- Existing non-evidence pages are changed only through verified exact operations. Untouched text stays byte-identical. Original evidence excerpts remain intact.
- Pending and formal pages remain separate. Only the specifically approved fixture revision is applied.
- Every `must` criterion in `memory-expectations.json` is met, and none of the `must_not` errors is present in the relevant candidate/formal version.
- The independent reader can locate scope and evidence for its answers. A page's existence or a linked filename alone is not sufficient.

Record the exact skill version/files, input boundaries, revisions, verdicts, and remaining limitations in the temporary report. Repeat a failed semantic case after a targeted correction. For a stable release, repeat the behavioral exercise across independent runs; one successful trial is evidence, not a guarantee. No new paid model API or hosted evaluation service is required: use the host's available reasoning sessions.

## Interrupted and non-text source exercise

Use `tests/fixtures/interrupted-session.jsonl` in a separate temporary wiki and registry, with only that file selected. Follow the actual skill through staging and stop before approval. Do not execute source commands or decode media.

Ask a fresh reader what is known about project formats, local validation and deployment, what remains unknown, and what parts of the source were not interpreted. After the reader answers, compare the claims and coverage report against the raw records. This complements the multi-wave exercise by checking interruption handling and reporting of non-text coverage without adding a media parser.

## Scope

Do not use this exercise to add context injection, autonomous scheduling, historical-edit reconciliation, automatic deletion, or extra retrieval infrastructure. Document quality gaps instead of hiding them behind a successful structural validator.
