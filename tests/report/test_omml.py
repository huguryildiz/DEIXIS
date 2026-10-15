"""Word equations (OMML) from `$...$` LaTeX in DOCX exports; SYNTHETIC formulas only."""

import io
import zipfile
from xml.etree import ElementTree as ET

import pytest

from deixis.exports import ooxml
from deixis.exports.omml import M, to_omml

NS = {"m": M, "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _tree(latex: str, display: bool = False) -> ET.Element:
    xml = to_omml(latex, display)
    assert xml is not None
    return ET.fromstring(f'<w:p xmlns:w="{NS["w"]}" xmlns:m="{M}">{xml}</w:p>')


@pytest.mark.parametrize("latex,element", [
    (r"p_{ij}", "m:sSub"), (r"q^{l-1}", "m:sSup"), (r"x_i^2", "m:sSubSup"), (r"\frac{Q_A}{2}", "m:f"),
    (r"\sqrt{n}", "m:rad"), (r"\sqrt[3]{y}", "m:rad/m:deg/m:r"), (r"\hat{x}", "m:acc"),
    (r"\max_{x \in F} f(x)", "m:limLow"), (r"\begin{cases} 1 & x>0 \\ 0 & \text{else}\end{cases}", "m:m/m:mr"),
])
def test_latex_maps_onto_its_word_structure(latex, element):
    assert _tree(latex).find(f".//{element}", NS) is not None


def test_an_n_ary_operator_takes_the_following_term_as_its_body():
    nary = _tree(r"\sum_{i=0}^{l} L_{i,i+1} + c").find(".//m:nary", NS)
    assert nary.find("m:naryPr/m:chr", NS).get(f"{{{M}}}val") == "∑"
    assert "".join(nary.find("m:sub", NS).itertext()) == "i=0" and "".join(nary.find("m:sup", NS).itertext()) == "l"
    assert "".join(nary.find("m:e", NS).itertext()) == "Li,i+1"


def test_display_math_is_an_equation_paragraph():
    assert _tree(r"E = mc^2", display=True).find("m:oMathPara/m:oMath", NS) is not None


@pytest.mark.parametrize("latex", [r"\badcommand{x}", r"\frac{a}{", r"\text{a\b}"])
def test_what_cannot_be_converted_is_refused(latex):
    assert to_omml(latex) is None


def test_a_docx_paragraph_writes_equations_and_keeps_refused_math_as_text():
    data = ooxml.docx([ooxml.paragraph(*ooxml.with_math(r"SYNTHETIC $p_{ij}=e^{-\alpha L}$ and $\badcommand{x}$ end"))])
    document = ET.fromstring(zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml"))
    paragraph = document.find("w:body/w:p", NS)
    assert len(paragraph.findall("m:oMath", NS)) == 1
    assert "".join(t.text for t in paragraph.iter(f"{{{NS['w']}}}t")) == r"SYNTHETIC  and $\badcommand{x}$ end"
