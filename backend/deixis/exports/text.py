"""Words and formats the browser exports use, so the server-written files read the same.

The answer report's Markdown and the evidence table's CSV are built in the browser (AnswerBlock.tsx `markdown`,
EvidenceTable.tsx `tableCsv`). Their DOCX and XLSX twins are written here from the same view models, with the same
labels in the same language and citation style. The Turkish strings are copies of the `tr` map in apps/web/src/i18n.ts;
tests/report/test_ooxml_exports.py fails when one of them drifts. `{name} — source` exists only in these files.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any, Callable, Literal

Language = Literal["en", "tr"]
CitationStyle = Literal["apa", "ieee", "mla", "chicago"]

TR: dict[str, str] = {
    "Report": "Rapor",
    "This answer was produced for revision {n} of the question and is not applied to the current revision.":
        "Bu yanıt sorunun {n}. revizyonu için üretildi ve güncel revizyona uygulanmıyor.",
    "Your source selection changed after this answer was generated. It is kept, but it may cite sources you have since excluded or miss ones you added.":
        "Bu yanıt üretildikten sonra kaynak seçiminiz değişti. Yanıt saklanır, ancak sonradan hariç tuttuğunuz kaynaklara atıf yapıyor veya eklediklerinizi içermiyor olabilir.",
    "interpretation": "yorum",
    "Reviewer: {reason}": "İnceleyici: {reason}",
    "supported": "destekleniyor",
    "partly supported": "kısmen destekleniyor",
    "not supported": "desteklenmiyor",
    "cannot assess": "değerlendirilemiyor",
    "No claim could be linked to the passages given to the model.": "Hiçbir iddia modele verilen pasajlara bağlanamadı.",
    "Not answered by the inspected passages": "İncelenen pasajların yanıtlamadıkları",
    "Limits": "Sınırlılıklar",
    "access": "erişim",
    "scope": "kapsam",
    "uncertainty": "belirsizlik",
    "conflicting evidence": "çelişen kanıt",
    "unsupported request": "desteklenmeyen istek",
    "Cited passages": "Atıf yapılan pasajlar",
    "OCR text · check against the page": "OCR metni · sayfayla karşılaştırın",
    "arXiv source": "arXiv kaynağı",
    "Structural check passed: each citation resolves to a stored passage that was given to this step. Semantic support is not checked.":
        "Yapısal denetim geçti: her atıf, bu adıma verilen kayıtlı bir pasaja karşılık gelir. Anlamsal destek denetlenmez.",
    "abstract": "özet",
    "section": "bölüm",
    "PDF p. {page}": "PDF s. {page}",
    "PDF p. {page} (printed {label})": "PDF s. {page} (basılı {label})",
    "Europe PMC text, rendered p. {page}": "Europe PMC metni, çizilmiş s. {page}",
    "Key": "Anahtar",
    "Reference": "Künye",
    "Title": "Başlık",
    "Authors": "Yazarlar",
    "Year": "Yıl",
    "Version": "Sürüm",
    "Access": "Erişim",
    "{name} — evidence": "{name} — kanıt",
    "published version": "yayımlanmış sürüm",
    "accepted manuscript": "kabul edilmiş makale",
    "submitted manuscript": "gönderilmiş makale",
    "version not stated": "sürüm belirtilmemiş",
    "PDF text": "PDF metni",
    "Abstract only": "Yalnızca özet",
    "Metadata only": "Yalnızca üst veri",
    "Value": "Değer",
    "Value without linked evidence": "Bağlı kanıtı olmayan değer",
    "Unclear in the source": "Kaynakta belirsiz",
    "Not reported": "Bildirilmemiş",
    "Not applicable": "Uygulanamaz",
    "No text": "Metin yok",
    "Not found in the text read": "Okunan kısımda bulunamadı",
    "Yes": "Evet",
    "No": "Hayır",
    "Model": "Model",
    "You": "Siz",
    "System": "Sistem",
    "Metadata": "Üst veri",
    "Abstract": "Özet",
    "Selected pages": "Seçili sayfalar",
    "Full text": "Tam metin",
}
# Written only into the DOCX and XLSX table exports; not a UI string.
SERVER_ONLY = {"{name} — source": "{name} — kaynak"}

Translate = Callable[..., str]


def translator(language: Language) -> Translate:
    """i18n.ts `t`: the Turkish rendering when there is one, then `{name}` placeholders filled from keyword values."""
    def t(text: str, **values: Any) -> str:
        template = (TR.get(text) or SERVER_ONLY.get(text) or text) if language == "tr" else text
        return re.sub(r"\{(\w+)\}", lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), template) \
            if values else template
    return t


def file_base(title: str, fallback: str) -> str:
    """The browser's download name stem: accents dropped, other characters to '-', lower case, 80 characters."""
    base = re.sub(r"[̀-ͯ]", "", unicodedata.normalize("NFKD", title))
    base = re.sub(r"[^a-zA-Z0-9]+", "-", base).strip("-").lower()[:80]
    return base or fallback


def number_text(value: int | float, language: Language) -> str:
    """`Number.toLocaleString('en-US' | 'tr-TR', {maximumFractionDigits: 12})`."""
    with localcontext() as context:
        context.prec = 80
        number = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
        if number.as_tuple().exponent < -12:
            number = number.quantize(Decimal(1).scaleb(-12), rounding=ROUND_HALF_UP)
        whole, _, fraction = format(abs(number), "f").partition(".")
    fraction = fraction.rstrip("0")
    group, point = (",", ".") if language == "en" else (".", ",")
    grouped = f"{int(whole):,}".replace(",", group)
    return ("-" if number < 0 else "") + grouped + (point + fraction if fraction else "")


# ---- labels.ts ---------------------------------------------------------------------------------------------------

VERDICTS = {"supported": "supported", "partially_supported": "partly supported", "not_supported": "not supported",
            "cannot_assess": "cannot assess"}
VERSIONS = {"publishedVersion": "published version", "acceptedVersion": "accepted manuscript",
            "submittedVersion": "submitted manuscript"}
OCR_LABEL = "OCR text · check against the page"


def page_locator(t: Translate, page: Any, rendition: Any = None, printed: Any = None) -> str:
    if rendition:
        return t("Europe PMC text, rendered p. {page}", page=page)
    return t("PDF p. {page} (printed {label})", page=page, label=printed) if printed else t("PDF p. {page}", page=page)


def locator_text(t: Translate, evidence: dict[str, Any]) -> str:
    if evidence.get("kind") == "abstract":
        return t("abstract")
    if evidence.get("physical_page"):
        return page_locator(t, evidence["physical_page"], evidence.get("rendition"), evidence.get("printed_label"))
    return t("section")


def version_text(t: Translate, label: str | None) -> str:
    return t(VERSIONS.get(label, label)) if label else t("version not stated")


# ---- citations.tsx formatReferenceText -----------------------------------------------------------------------------

def _name(full: str) -> tuple[str, list[str]]:
    words = full.strip().split()
    return (words.pop() if words else ""), words


def _initials(given: list[str]) -> str:
    return " ".join("-".join(f"{part[:1].upper()}." for part in word.split("-")) for word in given)


def _inverted(family: str, given: list[str]) -> str:
    return f"{family}, {' '.join(given)}" if given else family


def _natural(family: str, given: list[str]) -> str:
    return " ".join([*given, family])


def _end(text: str, mark: str) -> str:
    return text if re.search(r"[.?!]\Z", text) else text + mark


def _series(items: list[str], conjunction: str) -> str:
    return "".join(items) if len(items) < 2 else f"{', '.join(items[:-1])}, {conjunction} {items[-1]}"


def _year(value: Any) -> str:
    return "" if value is None else str(value)


def reference_text(style: CitationStyle, source: dict[str, Any]) -> str:
    """The plain-text reference the browser writes into the report download, in the chosen style."""
    names = [_name(full) for full in source.get("authors") or []]
    book = source.get("publication_type") == "book"
    doi, venue, title = source.get("doi"), source.get("venue"), source.get("title") or ""
    year = source.get("year")
    link = f"https://doi.org/{doi}" if doi else source.get("landing_url")
    if style == "ieee":
        people = [" ".join(part for part in (_initials(given), family) if part) for family, given in names]
        authors = f"{people[0]} et al." if len(people) > 6 else " and ".join(people) if len(people) == 2 else _series(people, "and")
        quoted = _end(title, "," if venue or year or doi else ".")
        head = _end(title, ".") if book else f"“{quoted}”"
        tail = ", ".join(part for part in (venue, _year(year), f"doi: {doi}" if doi else "") if part)
        return (f"{authors}, " if authors else "") + head + (" " + _end(tail, ".") if tail else "")
    if style == "mla":
        authors = ("" if not names else _inverted(*names[0]) if len(names) == 1
                   else f"{_inverted(*names[0])}, and {_natural(*names[1])}" if len(names) == 2
                   else f"{_inverted(*names[0])}, et al.")
        head = _end(title, ".") if book else f"“{_end(title, '.')}”"
        parts = [_end(authors, ".") if authors else "", head, _end(venue, ",") if venue else "", _year(year), link or ""]
        return " ".join(part for part in parts if part)
    if style == "chicago":
        people = [_inverted(family, given) if i == 0 else _natural(family, given) for i, (family, given) in enumerate(names)]
        authors = f"{', '.join(people[:7])}, et al." if len(people) > 10 else _series(people, "and")
        head = _end(title, ".") if book else f"“{_end(title, '.')}”"
        parts = [_end(authors, ".") if authors else "", f"{year if year is not None else 'n.d.'}.", head,
                 _end(venue, ".") if venue else "", _end(link, ".") if link else ""]
        return " ".join(part for part in parts if part)
    people = [f"{family}, {_initials(given)}" if given else family for family, given in names]
    authors = f"{', '.join(people[:19])}, . . . {people[-1]}" if len(people) > 20 else _series(people, "&")
    date = f"({year if year is not None else 'n.d.'})."
    head = _end(title, ".")
    parts = [f"{authors} {date} {head}" if authors else f"{head} {date}", _end(venue, ".") if venue else "", link or ""]
    return " ".join(part for part in parts if part)
