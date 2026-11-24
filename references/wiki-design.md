# Personal Wiki Design

## Physical layout

```text
wiki/
  index.md
  current.md
  evidence/
  events/
  semantic/
    personal/
    projects/
    practices/
  .dreaming/
```

Create categories and pages when useful, not as empty scaffolding. The three content layers are options, not a mandatory pipeline for every fact. Use English instructions and field descriptions; preserve the user's language in quotations, proper names, and user-facing wiki content unless requested otherwise.

## What earns a place in memory?

The wiki should help a future agent understand this person and make better choices with them. It is not a session digest, activity log, project inventory, or copy of the user's document library.

Before retaining a candidate, ask:

1. **Future use:** What later judgment or action would change because this was remembered? If omitting it would make no meaningful difference, leave it in the source history.
2. **Durable signal:** Does it reveal a meaningful goal, choice, tradeoff, feedback, evolving view, or reusable lesson? A dated decision can matter for years; recency and repetition alone do not establish value.
3. **Fidelity:** What did the user actually say, in which role and situation? Keep tentative thinking tentative. Do not infer universal preferences or personality from a single task, or manufacture reasons the user did not give.

Favor the choice and its rationale over the implementation detail: goal and constraints, alternatives considered, what was accepted or rejected, why, and what later feedback changed. A concrete default or prohibition can deserve retention when it materially governs future work; do not discard it merely because it is specific. Conversely, a broad-sounding generalization is not valuable if it is unsupported.

Examples:

- Retain "In learning documents, preserve technical depth while explaining plainly; the user rejected both opaque jargon and over-short summaries," with its task scope and evidence. A generated document's filename, section count, and validation output normally stay in history.
- Retain a decision to restart a failed prototype when repeated iteration no longer improved the experience, including the stated feedback and reduced scope. Do not preserve every patch or turn that preceded it.
- Retain a provisional view together with the user's request to challenge it. Do not harden a question into a settled belief.

Write the future use in the retained candidate's existing `reason` field. Do not assign numeric importance scores or manufacture a fact/page quota. Process every selected source; retain only what earns a place. A useful session can yield no durable memory.

### Evidence: what supports this?

Store selected, credential-free excerpts supporting retained memories, with enough context to check important claims. Group excerpts by source conversation, using stable source IDs in filenames to avoid collisions. Do not make an evidence page for every processed session. Complete transcripts remain private source history; do not copy them or unused quotations into the published wiki.

For each excerpt record:

- Source ID, platform, source file, and session ID when available.
- Message/event ID or line/event position; a text export may use byte positions.
- Event time when known, and the time the excerpt was captured.
- Attribution: explicit user statement, observed tool result, or agent inference.
- Necessary verbatim text or precisely identified output, with credentials redacted.
- Limitations such as missing tool output, ambiguous context, or historical-only validation.

An assertion in a transcript is evidence that the assertion was made, not automatically evidence that it is true. A successful local command is not evidence of deployment. User confirmation permits storage; it does not upgrade the source's factual authority.

Do not rewrite an earlier excerpt to agree with a new conclusion. Add the correcting evidence and link both where the change matters. Direct source locations are provenance strings, not portable Markdown links; use code formatting for filesystem locations outside this wiki. Pages should link to local evidence pages using relative Markdown links.

### Events: what happened, and why?

Organize around consequential decisions or experiences that explain the person's later choices. A task can span many sessions; a session can contribute to many events. Create an event page only when the evolution, rationale, or feedback adds something beyond the semantic page. Routine activity and chronological completeness do not justify an event. Avoid one event page per topic, session, turn, or dream run.

A useful event page contains:

- Goal, project/context, and time range.
- Current status and unresolved work.
- A concise timeline of significant actions, decisions, feedback, and observed outcomes.
- Alternatives, reasons, and applicability where they matter.
- Links to supporting evidence and related semantic pages.

Preserve consequential decision changes without retaining every repetitive discussion. Mark the time of an event separately from the time it was learned or summarized. Do not turn a plan into a completed action or a local verification into a global result.

### Semantic memory: what do we currently understand?

Keep integrated, usable statements organized by subject:

- `personal/`: personal and work background, preferences, stated views, long-term goals.
- `projects/`: project background, constraints, current decisions, environment/version conditions.
- `practices/`: validated or explicitly qualified reusable procedures and failure lessons.

A page may hold several individually revisable claims; do not create a file per fact. Use stable descriptive headings or anchors when useful. Write each substantive claim about one subject and facet, then organize the page to answer a useful recurring question. For example: "What is the project's current release policy, where does it apply, and why did it change?"

Every important conclusion needs scope, evidence, and epistemic status: explicit statement, observed fact, inference, unverified hypothesis, superseded claim, or unresolved conflict. Use ordinary prose; a database or rigid per-sentence schema is unnecessary.

Retain applicable conditions. Do not promote a project-specific decision into a universal preference. Repeated behavior can support an inference but is not an explicit statement. A directly stated preference may link straight to evidence without an artificial event page. An unresolved incident need not produce a general rule.

When a conclusion is superseded, state the current understanding and briefly identify what changed and why. Link to event history and the correcting evidence. Do not retain two contradictory unqualified recommendations.

### Navigation: what matters now, and where is it?

`index.md` starts with what is strongly related to the person: supported background and goals, ways of weighing choices, views, and collaboration feedback. Describe what each entry helps a future agent decide. Follow with useful practices and project context, then the few events worth revisiting and evidence. Do not lead with a project inventory, file counts, or a chronology. Every retained page should be discoverable through the link structure; do not make the index a second copy of the wiki.

`current.md` is a small view of personally meaningful current focus, decisions still being weighed, and unresolved questions that could affect future action. Ordinary project status and old requests are not today's priorities. Link to canonical pages rather than reproducing an activity log. Remove completed tasks from this view; retain an event only when it passes the long-term value test. A rejected dream is not a completed task.

Neither file is automatically loaded into future agent sessions. Reading and context injection are outside MVP scope.

## Linking and consolidation

Use relative Markdown links such as `[Design event](../../events/dreaming-design.md)`; do not use `[[wiki-links]]`. The helper validates target files and wiki boundaries, not heading anchors or factual claims. Prefer file-level links for durable provenance; if using anchors, check them yourself.

Evidence excerpts belong in evidence pages. Events link to that evidence and describe evolution. Semantic pages link to evidence/events and state the current understanding. Short scoped reminders in navigation are acceptable; avoid separately maintained full copies.

When merging duplicates, preserve useful content in the canonical page, replace the old page with a concise redirect link, repair incoming links, and verify facts and navigation. MVP does not delete pages or automatically archive history. Do not prune a fact merely because it is old or absent from the latest increment.

## Review example

For a new project rule requiring approval before a release:

1. Add the exact user requirement to an evidence page.
2. If part of a meaningful decision process, update that event's timeline.
3. Update the project's current release rule, retaining scope and evidence.
4. Update navigation only where discovery or ongoing status changed.
5. Group the dependent page changes for review. Do not infer that all unrelated user actions now require approval.

## Task-oriented quality check

Before sealing, try representative questions against the draft: “What is the current rule?”, “When does it apply?”, “Why did it change?”, and “Where is the evidence?” A good wiki should answer these without forcing a full transcript reread.

Ask also: "What would I do differently with this person because I read this?" Check that the page preserves actual tradeoffs and useful conditions, rather than a generic compliment or a list of things done. Keep uncertainty visible. Page counts, link counts, and recall of incidental historical details do not establish long-term usefulness. A later decision or collaboration task is the stronger test.

## Candidate accounting and minimal edits

Candidate facts live in the private review, not in a fourth public wiki layer. Each needs a statement, subject, facet, scope, epistemic status, evidence references, disposition, reason, and targets when retained. Explicit corrections also identify an existing prior claim. An ignored candidate still needs a reason; an input with no candidates needs its own processing reason.

This accounts for extracted facts, not every sentence, and cannot prove that extraction found every important fact. Do not force new pages or knowledge changes from repetition. Structural navigation/merge work can be justified by existing content instead of fictitious new evidence. Never hide a substantive knowledge change inside a structural group.

Use `patch` for existing non-evidence pages. Match only the exact affected passage; preserve other passages byte-for-byte. Existing evidence pages are append-only. New evidence can refute an earlier assertion without erasing the original assertion's wording.

After a factual change, check page summaries, current lists, tables, and directly related pages for the same scoped claim. A claim missing from the increment is not false. A related entity's change does not automatically end every associated fact. Do not use an intermediate generated summary as independent evidence for an overwrite.

Cancelled work is not a successful observation: preserve the explicit interruption and missing-result boundary. An omitted image or other non-text block establishes that unread content existed, not what it said. Keep such coverage limitations visible and do not fabricate knowledge from omission markers.
