"""Pure, fail-closed conversion of saved dollar-delimited math to export LaTeX.

The scan bounds executable syntax; it does not validate argument counts or
scientific meaning. Compatibility warnings do not establish compilability.
"""

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal

from deixis.documents.arxiv_source import katex_known
from deixis.domain.contracts import _is_escaped, _math_spans
from deixis.workflow.report.latex_preamble import PREAMBLE_SHA256
from deixis.workflow.report.latex_text import Unmapped, escape_text, is_unmapped, symbol_math, symbol_text

COMMAND_DENY = frozenset({
    # Definitions, expansion and grouping can change the closed vocabulary.
    "def", "gdef", "edef", "xdef", "let", "futurelet", "newcommand", "renewcommand",
    "providecommand", "global", "expandafter", "noexpand", "begingroup", "endgroup",
    "bgroup", "egroup",
    # Literal scanning, character synthesis and diagnostics bypass ordinary tokens.
    "verb", "char", "message", "errmessage", "show",
    # External resources and HTML attributes have no export trust grant.
    "url", "href", "includegraphics", "htmlClass", "htmlData", "htmlId", "htmlStyle",
    # Boxes and arbitrary color/text arguments are outside this math boundary.
    "hbox", "fbox", "raisebox", "color", "textcolor", "colorbox", "fcolorbox",
})
TEXT_COMMANDS = frozenset({"text", "textrm", "textbf", "textit", "textsf", "texttt"})
E_ENVIRONMENTS = frozenset({
    "align", "align*", "alignat", "alignat*", "gather", "gather*", "multline",
    "multline*", "flalign", "flalign*", "equation", "equation*",
})
ALLOWED_ENVIRONMENTS = E_ENVIRONMENTS | frozenset({
    "aligned", "alignedat", "gathered", "split", "cases", "array", "matrix",
    "pmatrix", "bmatrix", "Bmatrix", "vmatrix", "Vmatrix", "smallmatrix", "subarray",
})
AMP_ENVIRONMENTS = frozenset({
    "aligned", "alignedat", "array", "matrix", "pmatrix", "bmatrix", "Bmatrix",
    "vmatrix", "Vmatrix", "cases", "split", "smallmatrix", "subarray", "align",
    "align*", "alignat", "alignat*", "flalign", "flalign*",
})
CELL_COMMANDS = frozenset({
    "rule", "vphantom", "hphantom", "phantom", "smash", "raisebox", "substack",
    "genfrac", "hspace", "vspace", "kern", "mkern", "hskip", "mskip", "Huge",
    "huge", "LARGE", "Large", "large", "normalsize", "small", "footnotesize",
    "scriptsize", "tiny",
})
CELL_DIMENSION = re.compile(r"\d+(?:\.\d+)?\s*(?:pt|em|ex|cm|mm|in|bp|pc|mu|sp|dd|cc|px)\b")
_WORD = re.compile(r"[A-Za-z]+")
_ENV = re.compile(r"\{([A-Za-z*]+)\}")
_TEXT_SYMBOLS = frozenset("&%$#_{},;}")
_LABEL = re.compile(r"eq:EQ[0-9]{1,3}")


def command_status(name: str) -> Literal["denied", "allowed"]:
    """Partition KaTeX's commands; unknown names are denied as well."""
    return "allowed" if name in katex_known()["commands"] and name not in COMMAND_DENY else "denied"


def _span_positions(text: str) -> list[tuple[int, int]]:
    """Positional twin of contracts._math_spans; checked against it on every split."""
    spans: list[tuple[int, int]] = []
    start = 0
    while start < len(text):
        if text[start] != "$" or _is_escaped(text, start):
            start += 1
            continue
        width = 2 if text[start:start + 2] == "$$" else 1
        end = start + width
        while end < len(text):
            if width == 1 and text[end] == "\n":
                break
            if text[end:end + width] == "$" * width and not _is_escaped(text, end):
                spans.append((start, end + width))
                start = end + width
                break
            end += 1
        else:
            start += width
            continue
        if end < len(text) and width == 1 and text[end] == "\n":
            start += width
    return spans


def split_text(text: str) -> list[tuple[str, str]]:
    positions = _span_positions(text)
    if [text[start:end] for start, end in positions] != _math_spans(text):
        return [("text", text)]
    pieces: list[tuple[str, str]] = []
    cursor = 0
    for start, end in positions:
        if start > cursor:
            pieces.append(("text", text[cursor:start]))
        pieces.append(("math", text[start:end]))
        cursor = end
    if cursor < len(text) or not pieces:
        pieces.append(("text", text[cursor:]))
    return pieces if "".join(value for _, value in pieces) == text else [("text", text)]


@dataclass(frozen=True)
class _Token:
    start: int
    end: int
    kind: str
    name: str
    text: bool


@dataclass(frozen=True)
class ScanResult:
    ok: bool
    reason: str | None = None
    top_amp: bool = False
    top_row: bool = False
    top_tag: bool = False
    # Positions are relative to the delimiter-free body, including begin/end.
    top_e: tuple[tuple[str, int, int], ...] = ()
    e_count: int = 0
    tokens: tuple[_Token, ...] = ()


@dataclass(frozen=True)
class _Frame:
    kind: str
    name: str = ""
    start: int = 0
    text: bool = False
    text_root: bool = False
    substack: bool = False


def _body(span: str) -> tuple[str, bool]:
    display = span.startswith("$$")
    width = 2 if display else 1
    if len(span) < 2 * width or not span.startswith("$" * width) or not span.endswith("$" * width):
        raise ValueError("missing math delimiters")
    return span[width:-width], display


def closed_scan(span: str) -> ScanResult:
    """Iterative unified-stack scan of the entire original span, including arguments."""
    try:
        body, display = _body(span)
    except ValueError:
        return ScanResult(False, "delimiters")
    if not body.strip():
        return ScanResult(False, "empty")
    if "^^" in body:
        return ScanResult(False, "superscript_escape")
    if re.search(r"\n[^\S\n]*\n", body):
        return ScanResult(False, "blank_line")
    for ch in body:
        category = unicodedata.category(ch)
        if (category == "Cc" and ch not in "\t\n" or category in {"Cf", "Zl", "Zp", "Cs", "Co", "Cn"}
                or category == "Zs" and ch != " "):
            return ScanResult(False, "nonprintable")
    stack: list[_Frame] = []
    tokens: list[_Token] = []
    top_e: list[tuple[str, int, int]] = []
    top_amp = top_row = top_tag = False
    e_count = 0
    pending: str | None = None
    symbols = katex_known()["symbols"] - {"(", ")", "]"}
    i = 0
    while i < len(body):
        start = i
        ch = body[i]
        in_text = bool(stack and stack[-1].text)
        if pending is not None and not ch.isspace() and ch != "{":
            return ScanResult(False, "missing_argument")
        if ch == "\\":
            if i + 1 == len(body):
                return ScanResult(False, "trailing_backslash")
            word = _WORD.match(body, i + 1)
            if word is None:
                name = body[i + 1]
                i += 2
                if name not in symbols or in_text and name not in _TEXT_SYMBOLS:
                    return ScanResult(False, "control_symbol")
                if name == "\\":
                    if not stack:
                        top_row = True
                    elif not (stack[-1].kind == "env" and stack[-1].name not in {"equation", "equation*"}
                              or stack[-1].kind == "brace" and stack[-1].substack):
                        return ScanResult(False, "row_context")
                tokens.append(_Token(start, i, "symbol", name, in_text))
                continue
            name = word.group()
            i = word.end()
            if i < len(body) and unicodedata.category(body[i])[0] in "LM":
                return ScanResult(False, "command_boundary")
            if command_status(name) == "denied":
                return ScanResult(False, "command")
            if in_text and name not in TEXT_COMMANDS | {"quad", "qquad"}:
                return ScanResult(False, "text_command")
            if name in {"begin", "end"}:
                while i < len(body) and body[i].isspace():
                    i += 1
                env = _ENV.match(body, i)
                if env is None or env.group(1) not in ALLOWED_ENVIRONMENTS:
                    return ScanResult(False, "environment")
                env_name = env.group(1)
                i = env.end()
                if name == "begin":
                    if env_name in E_ENVIRONMENTS:
                        e_count += 1
                    stack.append(_Frame("env", env_name, start))
                else:
                    if not stack or stack[-1].kind != "env" or stack[-1].name != env_name:
                        return ScanResult(False, "environment_balance")
                    frame = stack.pop()
                    if not stack and env_name in E_ENVIRONMENTS:
                        top_e.append((env_name, frame.start, i))
                tokens.append(_Token(start, i, "environment", env_name, in_text))
            else:
                if name == "left":
                    stack.append(_Frame("left"))
                elif name in {"right", "middle"}:
                    if not stack or stack[-1].kind != "left":
                        return ScanResult(False, "left_balance")
                    if name == "right":
                        stack.pop()
                elif name in {"tag", "nonumber", "notag"}:
                    if not display or stack:
                        return ScanResult(False, "tag_context")
                    top_tag = True
                    if name == "tag":
                        if i < len(body) and body[i] == "*":
                            i += 1
                        pending = "tag"
                elif name in TEXT_COMMANDS or name == "substack":
                    pending = name
                tokens.append(_Token(start, i, "command", name, in_text))
        else:
            if ch == "$":
                return ScanResult(False, "dollar")
            if ch in "%#":
                return ScanResult(False, "literal_special")
            if ch == "{":
                text_root = pending in TEXT_COMMANDS
                if text_root and sum(frame.text_root for frame in stack) >= 3:
                    return ScanResult(False, "text_depth")
                stack.append(_Frame("brace", text=in_text or text_root,
                                    text_root=text_root, substack=pending == "substack"))
                pending = None
            elif ch == "}":
                if not stack or stack[-1].kind != "brace":
                    return ScanResult(False, "brace_balance")
                stack.pop()
            elif ch == "&":
                if not stack:
                    top_amp = True
                elif stack[-1].kind != "env" or stack[-1].name not in AMP_ENVIRONMENTS:
                    return ScanResult(False, "amp_context")
            i += 1
            tokens.append(_Token(start, i, "char", ch, in_text))
        if len(stack) > 64:
            return ScanResult(False, "depth")
    if stack or pending is not None:
        return ScanResult(False, "unclosed")
    return ScanResult(True, top_amp=top_amp, top_row=top_row, top_tag=top_tag,
                      top_e=tuple(top_e), e_count=e_count, tokens=tuple(tokens))


@cache
def _names() -> dict:
    """Missing/stale compatibility evidence is an error, never an empty allowlist."""
    script = "scripts/latex_export_names.py"
    path = Path(__file__).with_name("latex_names.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Missing {path.name}; run {script}") from exc
    commands_path = Path(__file__).resolve().parents[2] / "documents" / "katex_commands.json"
    if (data["preamble_sha256"] != PREAMBLE_SHA256
            or data["katex_commands_sha256"] != hashlib.sha256(commands_path.read_bytes()).hexdigest()
            or not isinstance(data["katex_version"], str)
            or {data["katex_version"]} != katex_known()["version"]):
        raise ValueError(f"Stale latex_names.json; run {script}")
    return data


def _rewrite(body: str, scan: ScanResult) -> str:
    out: list[str] = []
    for token in scan.tokens:
        original = body[token.start:token.end]
        if token.kind == "command" and token.name in {"lt", "gt"}:
            out.append("<" if token.name == "lt" else ">")
        elif token.kind == "char":
            converted = symbol_text(original) if token.text else symbol_math(original)
            # XeTeX treats Unicode letters and marks as control-word letters too.
            if (not token.text and converted != original and re.search(r"\\[A-Za-z]+$", converted)
                    and token.end < len(body) and unicodedata.category(body[token.end])[0] in "LM"):
                converted += " "
            out.append(converted)
        else:
            out.append(original)
    return "".join(out)


MathKind = Literal["inline", "display_env", "display_tag", "display_aligned",
                   "display_gathered", "display_plain", "plain"]


@dataclass(frozen=True)
class MathSpan:
    source: str
    kind: MathKind
    labelable: bool
    body: str
    class_b: tuple[str, ...]
    notes: tuple[str, ...]


def _plain(span: str, reason: str) -> MathSpan:
    return MathSpan(span, "plain", False, span, (),
                    (f"Math written as plain text: {reason}.",))


def classify(span: str, *, cell: bool = False) -> MathSpan:
    # Compatibility evidence must raise if absent, even though scan/classify
    # failures themselves are fail-closed. Load outside the unexpected-error guard.
    names = _names()
    try:
        scan = closed_scan(span)
        if not scan.ok:
            return _plain(span, scan.reason or "scan")
        original, display = _body(span)
        # This subset limits known height constructors, not safety or all heights.
        if cell and (CELL_DIMENSION.search(original) or any(
                t.kind == "environment" or t.kind == "symbol" and t.name == "\\"
                or t.kind == "command" and t.name in CELL_COMMANDS for t in scan.tokens)):
            return _plain(span, "outside table-cell math subset")
        if scan.e_count:
            if (not display or scan.e_count != 1 or len(scan.top_e) != 1
                    or original[:scan.top_e[0][1]].strip() or original[scan.top_e[0][2]:].strip()):
                return _plain(span, "display environment placement")
            kind: MathKind = "display_env"
        elif not display:
            if scan.top_amp or scan.top_row:
                return _plain(span, "inline alignment")
            kind = "inline"
        elif scan.top_tag:
            if scan.top_amp or scan.top_row:
                return _plain(span, "tag with alignment")
            kind = "display_tag"
        elif scan.top_amp:
            kind = "display_aligned"
        elif scan.top_row:
            kind = "display_gathered"
        else:
            kind = "display_plain"
        if cell and display and kind != "display_plain":
            return _plain(span, "display outside table-cell math subset")
        rewritten = _rewrite(original, scan)
        # Adjacent saved input and generated symbols must not synthesize TeX syntax.
        if "^^" in rewritten:
            return _plain(span, "superscript_escape")
        if any(ch in "%#" and not _is_escaped(rewritten, i) for i, ch in enumerate(rewritten)):
            return _plain(span, "literal_special")
        class_b = tuple(sorted(
            {"\\" + t.name for t in scan.tokens if t.kind == "command" and t.name not in {"lt", "gt"}
             and t.name in names["undefined_commands"]}
            | {"{" + t.name + "}" for t in scan.tokens if t.kind == "environment"
               and t.name in names["undefined_environments"]}))
        notes = []
        if class_b:
            notes.append(f"{', '.join(class_b)} is not defined by the export preamble; the document may not compile")
        if cell and display:
            notes.append("Display math written inline in a table cell.")
            kind = "inline"
            body = "$" + rewritten.strip() + "$"
        else:
            body = rewritten.strip() if display else "$" + rewritten + "$"
        return MathSpan(span, kind, kind in {"display_aligned", "display_gathered", "display_plain"},
                        body, class_b, tuple(notes))
    except Exception:
        return _plain(span, "unexpected conversion error")


def render(m: MathSpan, label: str | None = None, unmapped: Unmapped | None = None) -> str:
    if label is not None and (not isinstance(label, str) or _LABEL.fullmatch(label) is None):
        raise ValueError("Equation label must match eq:EQ[0-9]{1,3}")
    if m.kind == "plain":
        return escape_text(m.source, unmapped)
    if unmapped is not None:
        for ch in m.body:
            if is_unmapped(ch):
                unmapped.add(ch)
    if m.kind == "inline":
        return m.body
    if m.kind == "display_env":
        return "\n" + m.body + "\n"
    body = m.body
    if m.kind in {"display_aligned", "display_gathered"}:
        env = "aligned" if m.kind == "display_aligned" else "gathered"
        body = f"\\begin{{{env}}}\n{body}\n\\end{{{env}}}"
    numbered = m.labelable and label is not None
    env = "equation" if numbered else "equation*"
    label_line = f"\\label{{{label}}}\n" if numbered else ""
    return f"\n\\begin{{{env}}}\n{label_line}{body}\n\\end{{{env}}}\n"


def convert_text(text: str, *, cell: bool = False,
                 label_for: Callable[[int, MathSpan], str | None] | None = None,
                 unmapped: Unmapped | None = None) -> tuple[str, list[str]]:
    parts: list[str] = []
    notes: list[str] = []
    math_index = 0
    after_display = False
    for kind, piece in split_text(text):
        if kind == "text":
            output = escape_text(piece, unmapped)
            display = False
        else:
            m = classify(piece, cell=cell)
            label = label_for(math_index, m) if label_for is not None else None
            output = render(m, label=label, unmapped=unmapped)
            notes.extend(m.notes)
            math_index += 1
            display = m.kind.startswith("display_")
        # Only render's outside LF boundaries are merged; internal math is intact.
        if display:
            while parts and not parts[-1].rstrip(" \t\n"):
                parts.pop()
            if parts:
                parts[-1] = parts[-1].rstrip(" \t\n")
        elif after_display:
            output = output.lstrip(" \t")
        if output:
            parts.append(output)
            after_display = display
    return "".join(parts), notes
