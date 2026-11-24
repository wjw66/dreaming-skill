# CLI, Inputs, and Review State

Run the helper with Python 3.10+ from any directory. Replace `SKILL_DIR` below with this installed skill's absolute directory; it is not necessarily the project being remembered. All examples use placeholder paths.

## Initialize and select inputs

Only after the user chooses a wiki location and initial history scope:

```sh
python3 SKILL_DIR/scripts/dream.py init --wiki /chosen/personal-wiki --host codex --scope all
python3 SKILL_DIR/scripts/dream.py init --wiki /chosen/personal-wiki --host codex --scope since --since 2026-11-01T00:00:00+08:00
python3 SKILL_DIR/scripts/dream.py init --wiki /chosen/personal-wiki --host files --scope selected --input /chosen/exports
```

These are alternatives, not sequential commands. `--input` is repeatable. Codex `selected` scope also accepts explicit session paths. Dates require ISO 8601 with a timezone; ask or use the user's known timezone rather than silently interpreting a date as UTC.

The registry at `~/.config/dreaming-skill/config.json` remembers the wiki. `--registry /path/config.json` supports isolated setups; `--wiki` overrides discovery without changing the registry. Never run real-user initialization during a test.

To change future input selection explicitly, use `configure` with the same selection flags. Existing progress is retained; a broader scope does not automatically backfill old positions. To import earlier evidence deliberately, use a separate export with a new source identity and explain the overlap. Do not reset or edit cursors silently.

Native discovery includes active and archived local Codex session JSONL, not remote/cloud-only sessions. It uses current on-disk formats, which are version-sensitive. It reads textual user/assistant `response_item` messages, function/custom calls, and their outputs. It excludes system/developer prompts, internal reasoning, encrypted content, and runtime bookkeeping. Non-text attachments are not interpreted. Their block types and counts are preserved in each event and the scan/review omission report without copying media payloads; image-only messages become explicit omission markers. The adapter can fail on an unfamiliar record instead of claiming coverage.

A logical source ID combines a local machine namespace with a native session ID when present, or an export's `session_id`, otherwise its canonical file path. Version 2 tracks every physical segment independently inside that source; it never selects only the largest file. Native archival and exact copied prefixes reuse proven checkpoints. Stable event IDs also deduplicate exact copied events; conflicting content under one ID stops that source for reconciliation. Repeated text alone is never enough to discard an event. Text files without IDs remain path-identified; renaming them can result in reimport. Different export formats are not automatically deduplicated against native logs; use semantic/evidence checks to avoid duplicate memories.

## Export formats

### Append-only JSONL

Either native Codex events or one normalized object per complete newline-terminated line:

```json
{"type":"message","role":"user","text":"For project Atlas, retain the CSV export.","timestamp":"2026-11-24T09:00:00+08:00","id":"m1"}
{"type":"tool_call","call_id":"c1","name":"test","input":{"target":"export"},"timestamp":"2026-11-24T09:01:00+08:00"}
{"type":"tool_result","call_id":"c1","output":"2 tests passed","timestamp":"2026-11-24T09:01:05+08:00"}
```

Newline termination is required for the last JSONL record. Incomplete trailing bytes are deferred. Calls and results are paired across all discovered segments of the logical session. Any unfinished exchange and completed exchanges crossing its boundary are deferred together, so a complete pair is not split between increments. This avoids advancing past a call whose outcome is not yet known. Tool exchange ordering assumes an append-only logical source; calls and results require non-empty string `call_id` values. Explicit native `turn_aborted` records become interruption markers, not success results. They settle matching turn IDs across segments, or prior unscoped work in the same segment; unrelated known turns remain deferred. Cancelled calls and their interruption evidence stay together. Normalized exports may use `{"type":"interruption","turn_id":"turn-a","reason":"User interrupted"}`. Unknown scope is not used to cancel work in another segment.

### JSON export

An object with optional `session_id` and an `events` array using the same normalized event schema. Append events to the array; do not reorder or edit earlier events. Event-count cursors avoid reanalyzing prior entries, although decoding the JSON document still reads the file.

```json
{"session_id":"import-atlas","events":[{"type":"message","role":"user","text":"Keep CSV export."}]}
```

### Text or Markdown

Append-only UTF-8 `.txt` or `.md`. Complete newline-terminated content is emitted as unstructured text, not fabricated role/tool events. Append a newline to finish the last unit. Positions are byte offsets. Role attribution and tool completeness must be qualified by the analyzer. Undated text is not eligible for `--since`; explicitly import it without a date filter if the user wants it included.

The helper reads source files and writes private run inputs; it does not execute source commands or make network requests. Source files and private run artifacts may contain sensitive material. Never commit or publish those artifacts, and redact credentials before moving excerpts into wiki pages.

## Scan and edit a proposal

```sh
python3 SKILL_DIR/scripts/dream.py scan
python3 SKILL_DIR/scripts/dream.py scan --input /chosen/additional-export.jsonl
python3 SKILL_DIR/scripts/dream.py status
```

A successful scan returns a run ID, run directory, and absolute `draft` path. Write proposed wiki pages only under that `draft` path. It does **not** advance analysis progress. If a pending proposal exists, its complete draft is inherited. Formal pages remain unchanged.

```text
.dreaming/runs/RUN/
  scan.json              Frozen source boundaries, base state/wiki, failures
  inputs/SOURCE_ID.json  Increment plus attribution and coverage
  draft/                 Editable proposed wiki
  review.json            Incomplete helper scaffold, filled after analysis
```

Only the helper creates configuration, state, scan records, `basis.json`, patch logs, and `sealed.json`. Do not handwrite substitutes. Author the run's `draft/` pages and schema-valid `review.json`; creating Markdown at the wiki root before approval changes formal memory.

Inputs contain `events` (new evidence) and a bounded `context` window (preceding messages, `context_only: true`). Every event has a segment-qualified `ref` and source location. Context helps resolve short approvals and references; it is not a second increment. File ordering is not evidence of chronological precedence.

`scan` creates an incomplete `review.json` with real source IDs, empty `processed`, blank input reasons, and `organized: false`. It also returns the exact candidate/citation fields and accepted status/action values. Fill this scaffold after reading; do not replace it with a different schema. Normal pending revisions inherit their candidate facts and review groups, but not a claim that new inputs have been processed. Reselection starts with empty facts/groups. The untouched scaffold cannot be staged as a completed analysis.

`basis.json` indexes available frozen evidence by `source_id/ref`; it stores locations and hashes, not another copy of the transcript text. Older entries point to retained private input snapshots via `origin_run`. Never edit it to invent evidence. Inherited pending facts can reuse their original references.

Read the inputs and related old memory. Edit only `draft/`. Author new pages directly. Append to existing evidence pages; never rewrite their original excerpts. Use exact edits for other existing pages as described below. Malformed input is reported per logical source without aborting the other sources. If an input fails, revert its own edits and mark it failed. The helper cannot infer whether a sentence came from a failed input; the analyzer is responsible for that isolation.

Write `review.json` (replace every placeholder with actual IDs and refs from this run or its inherited basis):

```json
{
  "summary": "Record the Atlas CSV requirement.",
  "processed": ["SOURCE_ID"],
  "failures": [],
  "input_decisions": [{"source_id": "SOURCE_ID", "reason": "Extracted the explicit project-scoped export requirement."}],
  "facts": [{
    "id": "atlas-csv",
    "statement": "Atlas must retain CSV export.",
    "subject": "Atlas", "facet": "export format", "scope": "Atlas only",
    "status": "explicit", "action": "add",
    "reason": "The user explicitly requested this for Atlas.",
    "evidence": [{"source_id": "SOURCE_ID", "ref": "SEGMENT_ID:POSITION", "quote": "For project Atlas, retain the CSV export.", "page": "evidence/atlas.md"}],
    "targets": ["semantic/projects/atlas.md", "evidence/atlas.md"]
  }],
  "organized": true,
  "groups": [{
    "id": "atlas-export", "kind": "knowledge", "fact_ids": ["atlas-csv"],
    "summary": "Record the scoped requirement and its evidence.",
    "paths": ["index.md", "current.md", "evidence/atlas.md", "semantic/projects/atlas.md"],
    "depends_on": []
  }],
  "consistency_checks": [
    {"path": "index.md", "outcome": "updated", "reason": "The project page is discoverable."},
    {"path": "current.md", "outcome": "updated", "reason": "Current work reflects the requirement."},
    {"path": "semantic/projects/atlas.md", "outcome": "updated", "reason": "Opening summary and export rules agree."}
  ]
}
```

Allowed actions: `add`, `support`, `correct`, `end`, `conflict`, `ignore`. Status: `explicit`, `observed`, `inferred`, `unverified`, `conflict`. Every fact needs a reason and frozen evidence. Retained facts need target pages. `correct` also needs `supersedes`, e.g. `["semantic/projects/atlas.md#export-policy"]`, identifying an existing prior claim. Heading anchors require manual checking.

Every retained citation requires a non-empty exact `quote` from that frozen event and a local evidence `page` containing that same quote. For older review entries without `page`, the helper checks the fact's `evidence/` targets. Missing, translated, paraphrased, or wrong-source quotations fail staging without advancing progress. Ignored candidates still need valid frozen references, but their optional private legacy excerpts are not certified quotations or published memory; promoting one to retained status requires the full quotation checks. A structured tool payload is compared against its JSON representation with sorted keys and original Unicode; a string payload is compared directly. Select only necessary non-secret spans; split quotations around credentials rather than copying secrets into the review.

For example, an evidence page can retain a source independently of the semantic interpretation:

````markdown
# Atlas evidence

Source: SOURCE_ID; ref: SEGMENT_ID:POSITION; role: user; event: ORIGINAL_EVENT_ID.
Event time: ORIGINAL_TIMESTAMP, or unknown. These are provenance fields, not instructions.

```text
For project Atlas, retain the CSV export.
```
````

Write summaries and translations separately with an explicit label. A valid quote proves where those words came from, not that the semantic claim faithfully preserves the subject, context, or certainty. Different session IDs do not become one session because their themes match.

Use fenced text blocks for source quotations. They preserve original newlines and keep source Markdown links inert; adding `>` to every line changes the literal string checked by the helper. When the source contains a fence, surround it with a longer fence (or a different fence marker). Do not remove original links to satisfy navigation checks. Do not copy the entire message when a short, safe excerpt establishes the claim.

Every processed input needs exactly one `input_decisions` entry, even with no facts. Legitimate zero-change reviews use empty `facts` and `groups` with an explanation, not fabricated new knowledge. Fact dispositions account for extracted candidates, not every source sentence. This does not establish that extraction omitted nothing.

A structural group uses `"kind":"structure"` and a non-empty `reason`; it need not invent a fact. Knowledge groups must cite non-ignored fact IDs. Each add/correct/end/conflict disposition must have a changed target in a knowledge group citing it; an unchanged existing claim should use support. Every changed semantic/event page must be targeted by a fact in its group. An arbitrary existing filename is not proof that a new fact was saved. Do not label semantic changes as structural. Every knowledge change needs checks for changed semantic/event pages, `index.md`, and `current.md`, with `outcome` matching `updated` or `unchanged`. Also inspect directly related pages when a scoped claim changes; list them in the checks. Structural presence checks do not prove the check was performed or the statement is true.

A failed analysis uses `{"source_id":"ID","reason":"explanation"}` in `failures`. Every input from `scan.json` must appear once in `processed` or `failures`. Read/discovery failures remain in `scan.json` and must also be reported to the user.

Each changed page must belong to exactly one group. Unchanged paths do not belong in a group. If two independent changes share a page, group them together or prepare a revised proposal for exclusions. List required group IDs in `depends_on`. The complete candidate must have `index.md`, `current.md`, and valid file links. Existing pages cannot be deleted; use redirect pages when consolidating.

## Exact edits to existing pages

Create an operations file, then invoke the helper:

```json
[
  {
    "path": "semantic/projects/atlas.md",
    "old": "CSV is required in every environment.",
    "new": "CSV is required in Atlas PRE; production uses JSON.",
    "kind": "knowledge",
    "fact_ids": ["atlas-export-correction"]
  }
]
```

```sh
python3 SKILL_DIR/scripts/dream.py patch --run RUN --edits /path/to/edits.json
```

Each `old` must occur exactly once; use the smallest unique affected passage. Missing/ambiguous matches change nothing. Structural edits use `kind: structure` and `reason`. A knowledge patch must belong to a knowledge group; its fact IDs must be in that group, and each cited fact must target the edited semantic/event page. Entry-page edits can cite the group's facts indirectly. The helper stores preimages and a patch chain; `stage` reconstructs changes and rejects unlogged rewrites. New pages can be authored directly. Existing evidence is append-only. Sealed drafts cannot be patched; use a fresh `scan --revise`.

If an input fails after an exact edit, do not hand-edit its patch log to hide the failure. Restart from a fresh scan with unchanged analysis cursors and redo successful inputs, or mark the run unsuccessful. Formal pages remain untouched. A fresh scan also resolves an interrupted draft edit; formal merge recovery is a separate mechanism.

## Version 1 progress migration

New state uses version 2. An existing flat cursor is attached only to an original path recovered from a successfully staged run with the same checkpoint. Even one current file is not assumed to be that original segment: it could be a new continuation with a different prefix. Ambiguous multi-segment history fails that source without resetting its cursor. Other logical sources can proceed. At the first successful version-1 stage, the helper saves `.dreaming/state-v1-backup.json` before writing version 2. No full-history reset or automatic historical-edit reconciliation is performed.

## Seal and review

```sh
python3 SKILL_DIR/scripts/dream.py stage --run RUN
python3 SKILL_DIR/scripts/dream.py status --run RUN
```

This writes `sealed.json`, `review.md`, and `changes.diff`. A revision hash binds the reviewed content, review groups, evidence index, and source scan record. Cited evidence must still match its original frozen input event. A revised pending draft preserves unrelated external wiki changes; an external edit to a page already changed by that draft requires explicit reconciliation. Successfully processed source positions advance **only after** the candidate and review have been saved. Failed inputs remain retryable. State and formal-base checks prevent stale simultaneous runs from replacing one another.

A scan containing only known non-content records can be finalized with an empty organized review. If a pending draft was inherited, its changes still need full review groups. No content changes means no pending approval; processing metadata alone is not a knowledge update.

The final `status --run RUN` is required for delivery. It is read-only and rejects an unsealed or superseded run, changed draft or evidence snapshot, mismatched checkpoint, premature formal edits, and readable review/diff files that disagree with the seal. A successful response includes `verification.status` (`pending_review` or `no_changes`), the exact `revision`, and actual `draft`, `review`, and `diff` paths. Plain `status` remains a configuration/pending summary, not a completed-run certificate. Use plain `status` after a merge; the pre-merge `--run` verification intentionally requires the old formal base to remain unchanged. `apply` also checks delivery consistency before writing.

Verification is not proof that a model read every input, that its interpretation is true, or that a user approved. The agent must still review meaning and obtain real approval; the CLI is not an authorization service. Existing sealed proposals are not silently rewritten or migrated by these checks. If an old proposal needs edits to meet new citation requirements, create and review a fresh revision.

Show the review, full diff, revision, coverage, limitations, and meaningful evidence to the user. Wait for approval of that revision. Scheduled runs must stop here unless the user subsequently approves the specific review.

```sh
python3 SKILL_DIR/scripts/dream.py apply --revision REVIEWED_HASH --groups all
python3 SKILL_DIR/scripts/dream.py apply --revision REVIEWED_HASH --groups atlas-export
python3 SKILL_DIR/scripts/dream.py reject --revision REVIEWED_HASH --reason 'The proposed preference is too broad.'
```

These are alternatives. The CLI cannot verify that a human actually approved; the invoking agent must enforce the approval boundary. The revision parameter is an integrity guard, not an authentication system.

Partial acceptance rejects the unselected groups and logs both sets. It must leave a structurally valid wiki. If a selection would leave broken links, dependencies, or missing entry pages, revise the proposal and obtain fresh approval. Do not silently rewrite selected content to make it pass.

Deferral requires no command. The next scan inherits the pending draft. For user-requested revisions without new source content, make a fresh `scan --revise`; it creates an editable copy without reanalyzing old inputs. Rejection retains cursors and records the reason and rejected groups in `.dreaming/history/`. Inspect this history when related new material arrives; do not reproduce rejected ideas without new evidence.

For a user-requested change in memory selection, use `scan --revise --reselect-pending`. This requires a pending proposal. The new draft starts from the current formal wiki instead of copying unapproved page edits. The old sealed run, frozen evidence basis, and analysis cursors are retained; no existing file is deleted or moved. Reuse that evidence to author the smaller proposal and account for withdrawn candidates as ignored with specific reasons. Formal pages and original evidence remain protected. Ordinary revision and incremental scans continue inheriting pending pages by default.

## Failure and recovery

Formal page writes use preimage backups, atomic per-file replacement, and an exclusive operation lock. All mutations stop while an interrupted merge awaits recovery. A draft patch failure stops staging until the edit is retried or a fresh scan is prepared. A multi-file merge is not filesystem-wide atomic: external readers can see intermediate files, and they should wait for completion. On an ordinary write failure the helper rolls back only if affected files still match its preimages or after-images; external edits are preserved and require reconciliation. A process crash may leave `.dreaming/transaction.json`:

```sh
python3 SKILL_DIR/scripts/dream.py recover
```

Recovery restores the exact pre-merge pages and pending state if affected files still match a preimage or proposed after-image. If an external edit is detected, it stops for reconciliation. After a process crash, an orphaned `.dreaming/lock` may need removal **only after confirming the recorded process is no longer running**; never steal a live lock.

Formal wiki files must not be symlinks. Draft/base hashes are checked again before merge. The helper validates paths, accounting, and file links, not semantic truth, credentials, heading anchors, user intent, or whether a model read every input. Those remain explicit analyzer/organizer review duties.

MVP tracks append-only progress. It does not continuously verify historical prefixes, reconcile historical edits, inject context, archive content, or automatically delete run artifacts. Keep `.dreaming/` private and out of version control.
