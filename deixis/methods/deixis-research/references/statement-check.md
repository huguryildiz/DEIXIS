# Statement check

`statement_check` reads one sentence a person gave and the passages of one work
a search found. `statement_check_target.sentence` is the sentence exactly as
the person wrote it; `statement_check_target.assessed_source_id` is the work.
The sentence does not cite this work, and the work was not chosen because it
agrees with the sentence. Say what the given passages state about the
sentence. You do not judge whether the sentence is true, whether the work is
good, or what the rest of the work says.

## Parts

Split the sentence into one to four claim parts, in sentence order. Copy each
part's `text` exactly from the sentence as one contiguous span; parts do not
overlap. Together they hold every word of the sentence, negations and numbers
included; only "and", "or", "but", "while", "whereas" and punctuation may lie
between two parts. The parts only tie quotes to what they support; they do not
change the sentence. Set `covers_whole_sentence` to true only when the parts
together cover everything the sentence claims. A sentence that makes one claim
is one part.

## Assessment

For each part give `assessment`:

- `stated`: a given passage states this part, in the sentence's words or in
  other words for the same thing.
- `partly`: a given passage states a narrower, broader or weaker version, or
  only some of the part.
- `not_stated`: no given passage states it.

A part is `stated` only when a passage states it. Text that is merely compatible
with the part, or from which the part could be inferred, is not `stated`. Judge
only from the given passages. Do not use the work's title, what you know of the
work, or what an abstract hints at to fill in what the passages do not say.
`not_stated` is a valid answer, and the expected one when the passages do not
say it. It means only that the given passages do not state the part; it does
not mean the work disagrees with the sentence. `passages_not_given` passages of
the work were not shown, and nothing can be said about them.

## Evidence

A `stated` or `partly` part has one to three quotes; a `not_stated` part has
none. No more than eight quotes in all. Each quote names the one given passage
it is copied from (`passage_id`) and copies a contiguous span of that passage
exactly, with its negations, numbers, units and comparison words as written.
Quote whole words, with the number, unit, sign, percent or comparison next to
them. When the passage's sentence holds a negation, quote the clause that
includes it; a quote of a negated passage cannot support a part that is not
negated, nor the other way round. Do not shorten a quote so that it drops a
"not", change a number, or join words from two places. The application locates
each quote only in the passage it names; a quote it cannot find there, or that
breaks one of these rules, is returned for repair.
