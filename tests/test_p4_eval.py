"""Regression checks for the P4 measurement tool's identity comparison."""

from scripts.p4_eval.measure import similar


def test_crossref_encoded_inline_formula_does_not_create_a_title_mismatch():
    source = "$k$ -Connectivity in Random Key Graphs With Unreliable Links"
    crossref = ('&lt;inline-formula&gt; &lt;tex-math notation="LaTeX"&gt;$k$ '
                '&lt;/tex-math&gt;&lt;/inline-formula&gt;-Connectivity in Random Key Graphs With Unreliable Links')
    assert similar(source, crossref) == 1.0
