"""The word lists code reads a question with (SW2.2). Lists only; no logic lives here.

Every entry is an English function word, a question frame, a preposition or a word that is frequent in general
language and in research prose whatever the field. No field's own term belongs here: a list that needs a topic word
to make a question parse is the wrong rule for that question, and the user's `key_terms` field corrects it instead.
The lists are hand-written and short; nothing measured their coverage.
"""

from __future__ import annotations

# Read for language detection and as phrase boundaries. A cue word that is also a function word is read as a cue first.
ENGLISH_FUNCTION_WORDS = frozenset("""
a an the and or but nor if then than that this these those there here it its they them their theirs he him his she
her hers we our ours us you your yours i my me who whom whose which what when where why how
is are was were be been being am do does did done have has had having can could will would shall should may might
must ought need
of in on at to for from by with within without about into onto over under between among across through during
before after above below against per via up down out off along around behind beside beyond inside outside toward
towards upon
so such no not none nor both each any all some more most less least few many much other others another same own
very also just only still yet again once ever never always often sometimes either neither every
as like versus vs whether while because since until unless although though however therefore thus hence
""".split())

# Asking scaffolding stripped from the start of a sentence before anything is extracted.
QUESTION_FRAMES = (
    "what is the effect of", "what is the impact of", "what are the effects of", "what is known about",
    "is there evidence that", "is there any evidence that", "which papers", "which studies", "which articles",
    "what is the effect", "how does", "how do", "how is", "how are", "how can", "how much", "how many",
    "what is", "what are", "why does", "why do", "when does", "when do", "where does", "where do",
)

# The word immediately before a phrase names the block the phrase is provisionally put in. The assignment is a rule,
# it is unreliable, and the user confirms it in slice 08 (SW2 Limits). Multi-word cues are matched before single ones.
CUE_WORDS: dict[tuple[str, ...], str] = {
    ("in",): "setting", ("on",): "setting", ("for",): "setting", ("within",): "setting", ("across",): "setting",
    ("among",): "setting", ("over",): "setting", ("under",): "setting",
    ("using",): "method", ("via",): "method", ("with",): "method", ("by",): "method", ("through",): "method",
    ("based", "on"): "method", ("formulated", "as"): "method", ("modeled", "as"): "method",
    ("modelled", "as"): "method", ("as", "a"): "method", ("as", "an"): "method",
    ("to", "minimize"): "outcome", ("to", "maximize"): "outcome", ("to", "reduce"): "outcome",
    ("to", "improve"): "outcome", ("to", "increase"): "outcome", ("effect", "on"): "outcome",
    ("impact", "on"): "outcome", ("in", "terms", "of"): "outcome",
    ("not",): "excluded", ("without",): "excluded", ("excluding",): "excluded", ("except",): "excluded",
    ("other", "than"): "excluded", ("rather", "than"): "excluded",
    ("of",): "task",
}
MAX_CUE_WORDS = max(len(cue) for cue in CUE_WORDS)

# Words frequent in general language and in research prose in every field. A phrase made only of these is dropped and
# one at either end of a phrase is trimmed, so "optimization approaches" is searched as "optimization". Words that
# name a study design (survey, review, trial) are deliberately absent: a question uses them to exclude, not to fill.
GENERAL_WORDS = frozenset("""
paper papers article articles publication publications work works study studies studied research literature
author authors evidence result results finding findings
approach approaches method methods methodology methodologies technique techniques framework frameworks
analysis analyses comparison comparisons example examples aspect aspects issue issues problem problems
question questions topic topics part parts way ways number amount
use used uses application applications
proposed reported published describe described presented discussed compare compared comparing
cite cited citing show shows shown give gives given make makes made take takes taken
different various several recent new current existing common general main major important possible available
better best good known typical overall
abstract
""".split())
