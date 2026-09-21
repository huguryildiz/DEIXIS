# Abstract screening

Goal: say, for each given record, whether its abstract is worth reading in full.
You never decide inclusion. The application decides, from two independent runs of
this step, and only a full text can include anything.

1. Read `question.text` and the `candidates` list. Each candidate carries its
   title, year, venue and abstract. Judge each record on its own abstract alone:
   the other records in the list are not evidence about it.
2. Give each record exactly one `label`:

| `label` | The abstract shows |
|---|---|
| `candidate` | the work is on the topic of the research question: it works in the setting the question names and on the task, problem or phenomenon it asks about. |
| `out_of_scope` | the work is about something else: another setting, another problem, or a work that only mentions the topic in passing. |
| `unresolved` | the abstract does not let you tell. |

3. Whether the work contains the **specific thing** the question looks for — a
   particular method, model, result or comparison — is not judged here. Only the
   full text can show that, so a work in the right setting and on the right task
   is a `candidate` even when the abstract does not name that specific thing.
4. Give exactly one `quote`, copied verbatim from that record's own abstract,
   supporting the label. Copy it, do not shorten, join, translate or tidy it. The
   quote may be empty only under `unresolved`. The application looks the span up
   in the abstract it showed you; a span it cannot find does not drop the record,
   but it does mean your label carries no evidence.
5. Give one sentence of `rationale`.
6. Return one `records` entry per given record, in the order the records were
   given, naming each by the `candidate_id` it was given under.
7. Echo `step_input_id`, `scope_revision` and `skill_package_hash` exactly as they
   were given, and set `schema_version` to `deixis.abstract_screening.v1`.

Do not search, do not use anything you know about these papers from outside the
given abstracts, and do not rank, score or compare the records.
