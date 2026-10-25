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


@pytest.mark.parametrize("latex", [r"\frac{a}{"])
def test_what_cannot_be_converted_is_refused(latex):
    assert to_omml(latex) is None


def test_a_docx_paragraph_writes_equations_and_keeps_refused_math_as_text():
    data = ooxml.docx([ooxml.paragraph(*ooxml.with_math(r"SYNTHETIC $p_{ij}=e^{-\alpha L}$ and $\badcommand{x}$ end"))])
    document = ET.fromstring(zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml"))
    paragraph = document.find("w:body/w:p", NS)
    assert len(paragraph.findall("m:oMath", NS)) == 1
    assert "".join(t.text for t in paragraph.iter(f"{{{NS['w']}}}t")) == r"SYNTHETIC  and $\badcommand{x}$ end"
