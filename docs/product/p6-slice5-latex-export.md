# P6 dilim 5 — IEEEtran LaTeX dışa aktarma: uygulama planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dilim 1'in rapor çalışmasına (`report` run kind, henüz kodda yok, yalnız `docs/product/p6-slice1-report-run.md`'de plan olarak var) ikinci bir dışa aktarma biçimi eklemek: `IEEEtran` (journal modu) için tek bir `.tex` dosyası ve ayrı bir `.bib` dosyası, `format=latex` parametresiyle dilim 1'in dışa aktarma rotasından bir zip olarak indirilir. Dönüşüm saf metin işlemidir, hiçbir TeX kurulumu gerektirmez ve hiçbir model çağrısı yapmaz; dilim 1'in `report/export.py::to_markdown`'ının yürüdüğü aynı bölüm/iddia/tablo/denklem yapısını yürür (paylaşılan bir ara doküman modeli çıkarılmaz, bkz. "Neden ayrı bir ara model yok"). Beş zor kısım gerçek kodla çözülür: (1) `domain/contracts.py`'nin kaçışa duyarlı matematik-aralığı tarayıcısı yeniden kullanılarak düzyazının LaTeX kaçışı ve matematiğin dokunulmadan geçmesi; (2) KaTeX'in kabul edip IEEEtran/amsmath'in etmediği (ya da tersi) yapıların bir liste üzerinden onarılması ya da işaretlenmesi; (3) hiçbir derleme yapılmadığı açıkça söylenmesi ve yalnız `latexmk`/`tectonic` varsa çalışan isteğe bağlı bir geliştirici testi; (4) D59'un iş anahtarlarıyla (`source_key`) `\cite{}`, `bibliography.py`'nin BibTeX yazıcısı küçük, geriye dönük uyumlu bir parametreyle yeniden kullanılarak; (5) tablo hücresi durumlarının düz yazılı biçimi ve 10–13 sütunlu, ~50 satırlı bir tablonun `table*` + `tabularx` ile bölünerek verilmesi.

**Architecture:** Yeni, saf ve model çağırmayan dört modül `backend/deixis/workflow/report/` altına eklenir: `latex_text.py` (kaçış ve matematik-aralığı ayrımı), `latex_math.py` (KaTeX/LaTeX fark denetimi ve `$$…$$` dönüşümü), `latex_table.py` (hücre durumlarının düz metni ve `table*` bölme), `latex_bib.py` (D59 anahtarlarıyla `bibliography.py`'nin yeniden kullanımı) ve bunları birleştiren `latex_export.py`. `latex_export.py`'nin asıl işi iki katmanlıdır: saf bir `render_latex(report, sections, sources, gaps) -> LatexBundle` fonksiyonu (yalnız sözlüklerle çalışır, `ReportStore`'a bağlı değildir, golden-file testleri bunu çağırır) ve ince bir `to_latex(store, reports, report_id) -> LatexBundle` sarmalayıcısı (dilim 1'in `ReportStore`'undan bu sözlükleri okur — tam alan adları dilim 1 kodlanınca kesinleşir, bkz. Açık noktalar). `backend/deixis/workflow/bibliography.py`'ye küçük, geriye dönük uyumlu bir `keys: list[str] | None = None` parametresi eklenir (varsayılan `None` bugünkü `_keys()` davranışını korur); `latex_bib.py` bu parametreyi D59 anahtarlarıyla doldurarak çağırır. `domain/contracts.py`'ye `_math_spans`/`_without_math`'ın davranışını değiştirmeyen iki genel takma ad (`math_spans`, `without_math`) eklenir; bunlar dışında dilim 1'in ya da mevcut kodun hiçbir özel (`_` önekli) adı doğrudan içe aktarılmaz. API tarafında dilim 1'in `GET .../reports/{id}/export?format=markdown` rotası `format=latex` dalıyla genişler: `zipfile`'la bellekte kurulan bir zip, `Content-Disposition` ile indirilir; dışa aktarma uyarıları (KaTeX/LaTeX farkı, Marker/OCR kökenli denklemler) küçük, sınırlı sayıda bir `X-Deixis-Export-Warnings` başlığında JSON dizi olarak döner (bkz. görev 5f). Frontend'de `ReportView.tsx`'e Markdown düğmelerinin yanına bir "Download LaTeX (.zip)" düğmesi eklenir; bu düğme `fetch()` ile indirir, başlıktaki uyarıları okur ve varsa `useToast()` ile tek bir uyarı bildirimi gösterir (D50'nin bugünkü tek-toast deseni, `apps/web/src/Toast.tsx`). Hiçbir yeni migration, şema ya da görev türü **yoktur**: bu dilim hiçbir model adımı eklemez, `skill_package_hash` değişmez.

**Tech Stack:** Python 3.12 (uv, native arm64), stdlib `zipfile`/`re` (yeni bağımlılık yok), FastAPI, pytest; TypeScript/React 19 (`apps/web`), `fetch`/`Blob`/`URL.createObjectURL` (tarayıcı yerlisi, yeni kütüphane yok). Gerçek TeX derlemesi yalnız isteğe bağlı bir geliştirici testinde, sistemde `latexmk` ya da `tectonic` varsa.

**Spec:** docs/product/p6-report-design.md (§2 karar 9 ve 11, §9 "Dışa aktarma"/"Okuma biçimi", §12 madde 5); docs/product/p6-slice1-report-run.md (bkz. "Dilim 1'den beklenenler")

## Neden ayrı bir ara doküman modeli yok

Dilim 1'in `export.py::to_markdown` dolaşımı (bölüm → `paragraph` numarasına göre birleştirilmiş iddialar → `table_ref` gördüğünde TABLE I gömme → `equation_ref` gördüğünde numaralı denklem → sonda kaynakça) zaten dosyaya yazılmış, kodlanmamış bir plandır; ne mevcut ne de dilim 1'de paylaşılan bir ara model (`ReportDocument` gibi) önerilmiş, dilim 1'in kendisi de `export.py`'yi tek bir `to_markdown` fonksiyonu olarak tanımlar (bkz. p6-slice1-report-run.md, task 1j). Bu dolaşımı ayrı bir ara modele çıkarmak dilim 1'in henüz yazılmamış kodunu varsaymadan yapılamaz ve talimatın izin verdiği "küçük, sınırları belli bir refactor" ölçüsünü aşar: iki format (Markdown ve LaTeX) aynı sıralama/gruplama mantığını paylaşsa da, LaTeX'in kaçış, matematik dönüşümü ve tablo bölme adımları Markdown'da hiç yoktur, yani paylaşılacak olan yalnız "hangi sırayla, hangi alanları oku" bilgisidir — bu da zaten her iki modülün de aynı `report_sections`/`report_claims` satırlarını aynı `ordinal`/`paragraph` alanlarıyla okumasıyla paylaşılır, ayrı bir sınıf gerektirmez. Bu yüzden dilim 1'in yürüyüşü **taklit edilir** (aynı alanlar, aynı sıralama), ortak bir sınıf çıkarılmaz. Dilim 1 kodlandıktan sonra iki yürüyüşün gerçekten aynı olduğu görülürse, bu ortaklığı çıkarmak ayrı, küçük bir refactor görevidir (bkz. Açık noktalar).

## Global Constraints

- Python 3.12 `uv` ile, venv native arm64: `python3 -c "import platform; print(platform.machine())"` → `arm64`.
- Backend testleri: `PYTHONPATH=backend uv run pytest` (tümü); odaklı: `PYTHONPATH=backend uv run pytest tests/test_report_latex.py -q`.
- Frontend: `cd apps/web && npm ci && npm run build && npm run lint` (oxlint); `.impeccable.md` görsel değişiklikten önce okunur, ara onay istenmez — değişikliği kendin build/ekran görüntüsüyle doğrula.
- Tek SQLite bağlantısı API ve worker arasında paylaşılır; bu dilim hiçbir yeni tablo ya da yazma eklemez, yalnız var olan `ReportStore` okumalarını (dilim 1) LaTeX'e çevirir.
- Bu dilim şema/sözleşme değişikliği **gerektirmez**: yeni görev türü yok, `contracts/research/*.schema.json` değişmez, `skill_package_hash` değişmez, `tests/fixtures/research/*.json` ve `tests/fakes.py::valid_response` değişmez.
- Bu dilim migration **gerektirmez**: yeni tablo yok, `runs.kind`'a dokunulmaz.
- Fixture kayıtları SYNTHETIC etiketlidir; geçen bir birim testi dönüşümün doğruluğunu gösterir, gerçek bir TeX derlemesinin başarısını değil (bkz. görev 5g).
- Rapor dili sorunun dilidir (yanıtla aynı kural, dilim 1'den değişmeden); LaTeX çıktısı da aynı dilde yazılır, yalnız hücre durumu ve "Evet"/"Hayır" gibi sabit sözcükler dile göre seçilir (`latex_table.py::_STATE_TEXT`).
- Denklemler LaTeX'tir ve yanıtın 7. maddesindeki sırayı izler (önce değişkenler ve anlamları, sonra amaç, sonra kısıtlar; yalnız alıntılanan pasajın verdiği parçalar için) — bu dilim denklemin **içeriğini** değiştirmez, yalnız `$…$`/`$$…$$` çevresini LaTeX'in kabul ettiği bir ortama taşır.
- Nesnede iç kimlikler görünmez: `claim_key`, kısa tutamaçlar, `support_type`, ham JSON hiçbir zaman `.tex`/`.bib` dosyasına yazılmaz (§2 karar 9'un dışa aktarma tarafı).
- Commit'ler doğrudan `main`'e gider (kullanıcının global git kuralı): açıklayıcı İngilizce cümle, AI ilişkilendirmesi/ortak yazarlık yok, yalnız o görevin dosyaları `git commit -- <paths>` ile stage edilir (başka oturumlar aynı ağacı düzenliyor olabilir), sonra `git push origin main`.
- Bu dilimde alınan kalıcı karar `docs/decisions.md`'ye yürütme anındaki ilk boş D numarasıyla eklenir; bu not yazılırken en yüksek numara **D59**'dur (`grep -n '^## D' docs/decisions.md | head -3` ile teyit edildi, tek bir D57 var, çakışma yok) — yürütmeden hemen önce yine de tekrar teyit edilmeli, çünkü dilim 1 ya da başka bir dilim bu arada yeni bir D numarası almış olabilir.
- Dilim 1'in kendisi bu not yazılırken kodda **yoktur** (`backend/deixis/workflow/report/` dizini, `contracts/research/report-*.schema.json`, migration 0034 — hiçbiri yok); bu dilim dilim 1'in planındaki adları tüketir, dilim 1 gerçekten kodlanana kadar bu plandaki dilim-1-bağımlı görevler (5e Task 1'in `to_latex` sarmalayıcısı, 5f'nin rota değişikliği) çalıştırılamaz. Saf dönüşüm görevleri (5a–5d, 5e Task 2'nin golden-file testi, 5g, 5h'nin i18n kısmı) dilim 1'den bağımsız, herhangi bir sırada yazılabilir ve test edilebilir.

## Dosya yapısı

Yeni dosyalar:

- `backend/deixis/workflow/report/latex_text.py` — kaçışa duyarlı matematik-aralığı ayrımı (`split_math_spans`), düzyazı LaTeX kaçışı (`escape_prose`), ikisini birleştiren `escape_mixed`.
- `backend/deixis/workflow/report/latex_math.py` — KaTeX/LaTeX fark tablosu, bilinmeyen makro denetimi (`check_unsupported_macros`), `$$…$$` → `equation`/`aligned`/`gathered` dönüşümü (`convert_math_span`).
- `backend/deixis/workflow/report/latex_table.py` — hücre durumunun düz metni (`cell_text`), `table*`/`tabularx` bölme (`render_table`).
- `backend/deixis/workflow/report/latex_bib.py` — D59 iş anahtarlarının çözümü (`resolve_cite_keys`), `bibliography.to_bibtex`'in yeniden kullanımı (`to_bibtex_for_report`).
- `backend/deixis/workflow/report/latex_export.py` — saf `render_latex()`, `ReportStore` sarmalayıcısı `to_latex()`, `to_zip()`, `filename()`.
- `tests/test_report_latex_text.py`, `tests/test_report_latex_math.py`, `tests/test_report_latex_table.py`, `tests/test_report_latex_bib.py` — birim testleri.
- `tests/test_report_latex_export.py` — golden-file testi (tam SYNTHETIC sabit) ve isteğe bağlı derleme testi.
- `tests/fixtures/research/report-latex-golden.py` — golden fixture'ın Python sözlükleri (rapor/bölüm/kaynak/aday) ve beklenen `.tex`/`.bib` sabitleri, testler arasında paylaşılsın diye ayrı modülde.

Değiştirilecek dosyalar:

- `backend/deixis/domain/contracts.py` — `math_spans = _math_spans`, `without_math = _without_math` genel takma adları (`_math_spans`/`_without_math` tanımlarının hemen altına, davranış değişmeden).
- `backend/deixis/workflow/bibliography.py` — `to_bibtex(sources, keys: list[str] | None = None)`; `keys is None` iken bugünkü `_keys(sources)` davranışı birebir korunur.
- `backend/deixis/workflow/report/export.py` (dilim 1'de yaratılır) — `MEDIA_TYPES`'a `"latex": "application/zip"` eklenir; bu dosyanın kendisi yoksa (dilim 1 henüz kodlanmadıysa) görev 5f bu satırı `latex_export.py`'de tek başına tutar ve dilim 1 kodlanınca birleştirilir (bkz. Açık noktalar).
- `backend/deixis/api/app.py` — dilim 1'in rapor dışa aktarma rotasına `format == "latex"` dalı.
- `apps/web/src/report/ReportView.tsx` (dilim 1'de yaratılır) — "Download LaTeX (.zip)" düğmesi.
- `apps/web/src/i18n.ts` — yeni İngilizce/Türkçe dizeler (görev 5h).
- `docs/decisions.md` — bu dilimin kalıcı kararı (yeni D numarası).
- `docs/product/p6-report-design.md` — §12 madde 5'in durum satırı.

## Görevler

### 5a — Kaçışa duyarlı matematik ayrımı ve düzyazı kaçışı

#### Task 1: `contracts.py`'de genel takma adlar

**Files:**
- Modify: `backend/deixis/domain/contracts.py`
- Test: `tests/test_contracts.py`

**Interfaces:**
- Consumes: `contracts._math_spans`, `contracts._without_math` (mevcut, değişmez).
- Produces: `contracts.math_spans`, `contracts.without_math` (aynı fonksiyonlara genel takma ad).

Bu, "özel adı dikkatsizce içe aktarma" riskini kapatan bilinçli, küçük ve sınırları belli bir ekleme: `_math_spans` kaçışa duyarlı, doğru bir tarayıcıdır (`\$` bir aralık başlatmaz, satır içi aralık satırı geçemez, çift `$$` çok satırlı olabilir — `_check_math`'ın zaten dayandığı kurallar); onu ikinci bir regex'le yeniden yazmak iki uygulamanın zamanla ayrışması riskini taşır. Ekleme yalnız iki isim; `_math_spans`/`_without_math`'ın kendisi, imzası ya da davranışı değişmez.

- [ ] **Step 1: Başarısız testi yaz**

```python
# tests/test_contracts.py'ye eklenir
def test_math_spans_and_without_math_have_public_aliases_for_reuse_outside_this_module():
    assert contracts.math_spans is contracts._math_spans
    assert contracts.without_math is contracts._without_math
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_contracts.py -k public_aliases -v`
Expected: FAIL — `AttributeError: module 'deixis.domain.contracts' has no attribute 'math_spans'`.

- [ ] **Step 3: Takma adları ekle**

`_math_spans` tanımının hemen altına:

```python
math_spans = _math_spans
"""Public alias: reused by report/latex_text.py so it does not re-implement this escaping-aware scanner (P6 slice 5)."""
```

`_without_math` tanımının hemen altına aynı desenle `without_math = _without_math`.

- [ ] **Step 4: Çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_contracts.py -k public_aliases -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/domain/contracts.py tests/test_contracts.py
git commit -m "Expose contracts' math-span scanner under public names for reuse by the LaTeX exporter" -- backend/deixis/domain/contracts.py tests/test_contracts.py
git push origin main
```

---

#### Task 2: `latex_text.py` — kaçış ve ayrım

**Files:**
- Create: `backend/deixis/workflow/report/latex_text.py`
- Test: `tests/test_report_latex_text.py`

**Interfaces:**
- Consumes: `contracts.math_spans` (task 1).
- Produces:

```python
def escape_prose(text: str) -> str: ...
def split_math_spans(text: str) -> list[tuple[bool, str]]: ...  # (is_math, chunk), covers the whole string in order
def escape_mixed(text: str, convert_math: Callable[[str], tuple[str, list[str]]]) -> tuple[str, list[str]]: ...
```

- [ ] **Step 1: Başarısız testleri yaz**

```python
# tests/test_report_latex_text.py
from deixis.workflow.report.latex_text import escape_prose, split_math_spans, escape_mixed


def test_escapes_the_ten_latex_special_characters():
    assert escape_prose("50% of A&B_C #1 {x}~y^2 back\\slash") == \
        r"50\% of A\&B\_C \#1 \{x\}\textasciitilde{}y\textasciicircum{}2 back\textbackslash{}slash"


def test_turkish_letters_pass_through_unescaped_for_xelatex():
    assert escape_prose("İncelenen çalışmalar gecikmeyi ölçmüştür (ığşĞÜÇÖİ).") == \
        "İncelenen çalışmalar gecikmeyi ölçmüştür (ığşĞÜÇÖİ)."


def test_straight_quotes_become_opening_and_closing_ligatures():
    assert escape_prose('He said "no" today') == "He said ``no'' today"


def test_non_breaking_space_becomes_latexs_own_tie():
    assert escape_prose("Section\u00a0I") == "Section~I"


def test_split_math_spans_separates_prose_from_untouched_math():
    chunks = split_math_spans(r"Gecikme $T_{\max}$ ile 50% sınırlanır.")
    assert chunks == [(False, "Gecikme "), (True, r"$T_{\max}$"), (False, " ile 50% sınırlanır.")]


def test_split_math_spans_handles_display_math_and_a_trailing_prose_tail():
    text = "Denklem: $$a+b=c$$ burada a, b, c > 0."
    chunks = split_math_spans(text)
    assert chunks[1] == (True, "$$a+b=c$$")
    assert chunks[-1] == (False, " burada a, b, c > 0.")


def test_escaped_dollar_sign_is_not_treated_as_a_math_boundary():
    # contracts.math_spans already treats \$ as literal; split_math_spans must not invent a span here.
    chunks = split_math_spans(r"Price is \$5, not math.")
    assert chunks == [(False, r"Price is \$5, not math.")]


def test_escape_mixed_escapes_prose_and_delegates_math_to_the_given_converter():
    calls = []

    def convert_math(span):
        calls.append(span)
        return span.upper(), [f"warned about {span}"]

    text, warnings = escape_mixed(r"50% ölçüldü: $T_{\max}$.", convert_math)
    assert text == r"50\% ölçüldü: $T_{\MAX}$."
    assert calls == [r"$T_{\max}$"]
    assert warnings == [r"warned about $T_{\max}$"]
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_latex_text.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'deixis.workflow.report'`.

- [ ] **Step 3: `latex_text.py`'yi yaz**

```python
"""Prose-to-LaTeX text transform for the report's LaTeX export (P6 slice 5, hard part 1).

Reuses domain.contracts' escaping-aware math-span scanner (contracts.math_spans, a public alias added
in this slice) so a claim's inline $...$ and display $$...$$ math is located exactly the way
_check_math already validates it; this module never re-implements that scanning with a second regex.
Text outside a math span is LaTeX-escaped here; a math span is left to report/latex_math.py, which
handles the KaTeX-only constructs that can appear inside it (hard part 2).

XeLaTeX (see latex_export.py's preamble) renders every Unicode code point through a loaded Unicode
font, so Turkish letters (ç ğ ı İ ö ş ü and their capitals) need no escaping or font-encoding package;
only the ten LaTeX-special ASCII characters, a non-breaking space and straight quotes need handling.
"""
from __future__ import annotations

from collections.abc import Callable

from deixis.domain.contracts import math_spans

_ESCAPE = {
    "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "&": r"\&", "%": r"\%",
    "$": r"\$", "#": r"\#", "_": r"\_", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}
_NBSP = "\u00a0"


def escape_prose(text: str) -> str:
    """Escape LaTeX-special characters in text known to contain no math span (a table caption, a
    keyword, or a chunk already separated out by split_math_spans). A straight double quote is turned
    into LaTeX's opening/closing quote ligature; a quote at the start of the string or after
    whitespace is treated as opening, any other as closing."""
    out: list[str] = []
    for i, ch in enumerate(text):
        if ch == _NBSP:
            out.append("~")
        elif ch == '"':
            out.append("``" if i == 0 or text[i - 1].isspace() else "''")
        else:
            out.append(_ESCAPE.get(ch, ch))
    return "".join(out)


def split_math_spans(text: str) -> list[tuple[bool, str]]:
    """(is_math, chunk) pairs covering the whole string in order. Uses contracts.math_spans's own
    escaping-aware span list (in order of appearance, non-overlapping) and locates each span's start
    with a forward-only search, rather than a second boundary-finding regex that could disagree with
    the first about an escaped dollar sign or a display math's line-crossing rule."""
    spans = math_spans(text)
    chunks: list[tuple[bool, str]] = []
    cursor = 0
    for span in spans:
        start = text.index(span, cursor)
        if start > cursor:
            chunks.append((False, text[cursor:start]))
        chunks.append((True, span))
        cursor = start + len(span)
    if cursor < len(text):
        chunks.append((False, text[cursor:]))
    return chunks


def escape_mixed(text: str, convert_math: Callable[[str], tuple[str, list[str]]]) -> tuple[str, list[str]]:
    """Escape the non-math parts of text with escape_prose and pass each math span (including its $
    or $$ delimiters) through convert_math, collecting its warnings in appearance order."""
    warnings: list[str] = []
    out: list[str] = []
    for is_math, chunk in split_math_spans(text):
        if is_math:
            converted, span_warnings = convert_math(chunk)
            out.append(converted)
            warnings += span_warnings
        else:
            out.append(escape_prose(chunk))
    return "".join(out), warnings
```

- [ ] **Step 4: Çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_latex_text.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/workflow/report/latex_text.py tests/test_report_latex_text.py
git commit -m "Add LaTeX prose escaping and a math-span split reused from contracts' scanner" -- backend/deixis/workflow/report/latex_text.py tests/test_report_latex_text.py
git push origin main
```

### 5b — KaTeX/LaTeX fark denetimi ve `$$…$$` dönüşümü

#### Task 1: KaTeX'in kabul edip IEEEtran/amsmath'in reddettiği (ya da tersi) yapılar

DEIXIS'in kendi KaTeX çağrısında (`apps/web/src/MathText.tsx`) `trust` **kapalıdır** ve hiçbir özel `macros` tanımlanmamıştır (`katex.renderToString(..., { displayMode, throwOnError: false })`); bu yüzden `\htmlClass`, `\href` gibi yalnız `trust` açıkken çalışan komutlar ya da `\R` gibi DEIXIS'te tanımlanmamış bir kısayol makro zaten kırık (kırmızı) çizilmiş olurdu — bu denetim bunu **ikinci kez**, saklanan ham metin üzerinde, statik olarak arar; bir garanti değildir.

| Yapı | DEIXIS'in KaTeX'inde (trust kapalı, macros yok) | IEEEtran/amsmath'te | Karar |
|---|---|---|---|
| `\text{...}` | destekli | `amsmath` gerekir | Preamble'a paket (`amsmath` zaten her zaman yüklü) |
| `\operatorname{...}` | destekli | `amsmath` gerekir | Preamble'a paket |
| `\mathbb{...}` | destekli | `amssymb` gerekir | Preamble'a paket |
| `\boldsymbol{...}` | destekli | `amsmath`/`bm` gerekir | Preamble'a paket (`amsmath` + `bm`) |
| `\dfrac{}{}` | destekli | `amsmath` gerekir | Preamble'a paket |
| `\tag{...}` | destekli | `amsmath` gerekir, ama raporun kendi numaralandırmasıyla (`equation_ref`) çakışır | **Onarılır**: `\tag{...}` silinir, uyarı yazılır |
| `$$…$$` içinde `aligned`/`gathered` | destekli | `equation`in doğrudan içinde değil, `equation`i sarmalayan bir ortam olarak kullanılır | **Onarılır**: `$$…$$` `\begin{equation}\label{...}` içine alınır, iç ortam korunur |
| `$$…$$` içinde üst düzey `align` | destekli (KaTeX display modunda) | kendi numaralandırmasını yapar, raporun tek numarasıyla çakışır | **Onarılır**: `align` → `aligned`'e çevrilir, tek `equation` numarası verilir |
| Ortamsız çıplak `\\` (satır sonu) | destekli (display modunda gevşek) | `equation` tek satırlıdır, çıplak `\\` hata verir | **Onarılır**: içerik `gathered` içine alınır |
| `\lt` / `\gt` | destekli (KaTeX'in kendi `<`/`>` takma adı) | düz LaTeX/amsmath'te tanımsız | **Onarılır**: `<`/`>` ile değiştirilir |
| `\R`, `\N` gibi kısayol makrolar | **desteksiz** (DEIXIS'in KaTeX'inde özel makro yok; zaten kırık çizilirdi) | `\newcommand` olmadan tanımsız | **İşaretlenir** (yeniden yazılmaz — hangi anlama geldiği belirsiz) |
| `\htmlClass{}{}`, `\href{}{}` | **desteksiz** (`trust` kapalı; KaTeX zaten reddeder) | karşılığı yok | **İşaretlenir** (sarmalayıcı otomatik soyulmaz: `\href`'in ikinci argümanı görünen metin, `\htmlClass`'ınki matematiğin kendisidir — ikisini karıştırmak içeriği sessizce kaybettirir ya da yinelerdi) |
| `\color{}`, `\textcolor{}{}` | destekli | `xcolor` gerekir | Preamble'a paket (`xcolor`) |

**Files:**
- Create: `backend/deixis/workflow/report/latex_math.py`
- Test: `tests/test_report_latex_math.py`

**Interfaces:**
- Produces:

```python
def check_unsupported_macros(span: str) -> list[str]: ...
def convert_math_span(span: str, label: str | None) -> tuple[str, list[str]]: ...
```

- [ ] **Step 1: Başarısız testleri yaz**

```python
# tests/test_report_latex_math.py
from deixis.workflow.report.latex_math import check_unsupported_macros, convert_math_span


def test_known_amsmath_and_amssymb_macros_are_not_flagged():
    assert check_unsupported_macros(r"T_{\text{gecikme}} \leq \dfrac{L}{R} \in \mathbb{R}") == []


def test_unrecognized_macro_is_flagged_without_being_rewritten():
    warnings = check_unsupported_macros(r"\R \to \mathbb{R}")
    assert any("\\R" in w for w in warnings)
    assert r"\R" in r"\R \to \mathbb{R}"  # not rewritten


def test_katex_trust_only_commands_are_flagged_as_unsupported():
    warnings = check_unsupported_macros(r"\htmlClass{foo}{x}")
    assert any("unsupported" in w and "htmlClass" in w for w in warnings)


def test_inline_math_is_untouched_except_for_katex_only_aliases():
    tex, warnings = convert_math_span(r"$a \lt b \gt c$", label=None)
    assert tex == r"$a < b > c$"
    assert any("lt" in w for w in warnings)


def test_tag_is_stripped_from_display_math_with_a_warning():
    tex, warnings = convert_math_span(r"$$a+b=c \tag{7}$$", label="eq:EQ1")
    assert r"\tag" not in tex
    assert "\\begin{equation}" in tex and "\\label{eq:EQ1}" in tex
    assert any("tag" in w for w in warnings)


def test_plain_display_math_becomes_one_labelled_equation():
    tex, warnings = convert_math_span(r"$$T \leq \dfrac{L}{R} + \tau$$", label="eq:EQ1")
    assert tex == "\\begin{equation}\n\\label{eq:EQ1}\nT \\leq \\dfrac{L}{R} + \\tau\n\\end{equation}"
    assert warnings == []


def test_bare_line_break_is_wrapped_in_gathered():
    tex, warnings = convert_math_span(r"$$a=1 \\ b=2$$", label="eq:EQ2")
    assert "\\begin{gathered}" in tex and tex.count("\\begin{equation}") == 1
    assert any("gathered" in w for w in warnings)


def test_aligned_block_gets_exactly_one_equation_number():
    tex, warnings = convert_math_span(r"$$\begin{aligned} a &= 1 \\ b &= 2 \end{aligned}$$", label="eq:EQ3")
    assert tex.count("\\begin{equation}") == 1
    assert "\\begin{aligned}" in tex


def test_top_level_align_is_rewritten_to_aligned_for_one_shared_number():
    tex, warnings = convert_math_span(r"$$\begin{align} a &= 1 \\ b &= 2 \end{align}$$", label="eq:EQ4")
    assert "\\begin{aligned}" in tex and "\\begin{align}" not in tex
    assert any("align" in w for w in warnings)
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_latex_math.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: `latex_math.py`'yi yaz** (yukarıdaki tablo, koddaki `_KNOWN_MACROS`/`_GREEK`/`_UNSUPPORTED` sabitleriyle):

```python
"""KaTeX-only constructs vs. plain LaTeX/IEEEtran+amsmath (P6 slice 5, hard part 2). See this file's
table in the plan for the per-construct decision. This is a static, best-effort check on stored text,
not a compiler; it can both miss a macro that truly breaks compilation and flag one that would have
compiled fine (task 5g's optional developer test is the only thing that actually compiles anything).
"""
from __future__ import annotations

import re

_LT_GT = [(re.compile(r"\\lt\b"), "<"), (re.compile(r"\\gt\b"), ">")]
_TAG = re.compile(r"\\tag\{[^{}]*\}")
_UNSUPPORTED_NAMES = {"htmlClass", "href", "colorbox", "class", "style", "includegraphics"}

_KNOWN_MACROS = {
    "frac", "dfrac", "tfrac", "sqrt", "sum", "int", "iint", "prod", "lim", "sup", "inf", "min", "max",
    "sin", "cos", "tan", "log", "ln", "exp", "times", "cdot", "div", "pm", "mp", "leq", "geq", "neq",
    "approx", "sim", "propto", "in", "notin", "subset", "subseteq", "supset", "cup", "cap", "forall",
    "exists", "nabla", "partial", "infty", "cdots", "ldots", "vdots", "ddots", "begin", "end", "left",
    "right", "mathbf", "mathit", "mathrm", "mathcal", "mathbb", "mathsf", "mathtt", "boldsymbol", "bm",
    "overline", "underline", "hat", "tilde", "bar", "vec", "dot", "ddot", "binom", "choose", "text",
    "operatorname", "quad", "qquad", "label", "ref", "eqref", "color", "textcolor", "big", "Big",
    "bigg", "Bigg", "langle", "rangle", "lceil", "rceil", "lfloor", "rfloor", "top", "bot", "perp",
    "parallel", "wedge", "vee", "oplus", "otimes", "circ", "star", "dagger", "ddagger", "hbar", "ell",
    "Re", "Im", "aligned", "gathered", "array", "matrix", "pmatrix", "bmatrix", "vmatrix",
}
_GREEK = {
    "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta", "eta", "theta", "vartheta",
    "iota", "kappa", "lambda", "mu", "nu", "xi", "pi", "rho", "sigma", "varsigma", "tau", "upsilon",
    "phi", "varphi", "chi", "psi", "omega", "Gamma", "Delta", "Theta", "Lambda", "Xi", "Pi", "Sigma",
    "Upsilon", "Phi", "Psi", "Omega",
}
_MACRO = re.compile(r"\\([a-zA-Z]+)")


def check_unsupported_macros(span: str) -> list[str]:
    found = []
    for match in _MACRO.finditer(span):
        name = match.group(1)
        if name in _KNOWN_MACROS or name in _GREEK or name in {"lt", "gt", "tag"}:
            continue
        if name in _UNSUPPORTED_NAMES:
            found.append(f"unsupported KaTeX-only command \\{name} has no plain-LaTeX equivalent")
        else:
            found.append(f"unrecognized macro \\{name}, not on the known-safe list; check this equation compiles")
    return found


def _rewrite_katex_only(inner: str) -> tuple[str, list[str]]:
    warnings = []
    for pattern, replacement in _LT_GT:
        if pattern.search(inner):
            warnings.append(f"rewrote KaTeX's {pattern.pattern!r} to {replacement!r}")
            inner = pattern.sub(replacement, inner)
    if _TAG.search(inner):
        warnings.append("removed \\tag{...}: the report numbers this equation itself via equation_ref")
        inner = _TAG.sub("", inner)
    return inner, warnings


def convert_math_span(span: str, label: str | None) -> tuple[str, list[str]]:
    """span includes its delimiters. label is an 'eq:EQ<n>' LaTeX label for display math with an
    equation_ref; inline ($...$) math is never wrapped in a numbered environment and label is ignored."""
    display = span.startswith("$$")
    inner = span[2:-2] if display else span[1:-1]
    inner, warnings = _rewrite_katex_only(inner)
    warnings += check_unsupported_macros(inner)
    if not display:
        return f"${inner}$", warnings
    env_match = re.search(r"\\begin\{(aligned|gathered|align)\}", inner)
    if env_match:
        env = env_match.group(1)
        if env == "align":
            inner = inner.replace("\\begin{align}", "\\begin{aligned}").replace("\\end{align}", "\\end{aligned}")
            warnings.append("rewrote a top-level align inside $$...$$ to aligned so it gets one shared equation number")
        tex = f"\\begin{{equation}}\n\\label{{{label}}}\n{inner.strip()}\n\\end{{equation}}"
    elif "\\\\" in inner:
        warnings.append("wrapped a bare line break in gathered so the equation environment accepts it")
        tex = f"\\begin{{equation}}\n\\label{{{label}}}\n\\begin{{gathered}}\n{inner.strip()}\n\\end{{gathered}}\n\\end{{equation}}"
    else:
        tex = f"\\begin{{equation}}\n\\label{{{label}}}\n{inner.strip()}\n\\end{{equation}}"
    return tex, warnings
```

- [ ] **Step 4: Çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_latex_math.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/workflow/report/latex_math.py tests/test_report_latex_math.py
git commit -m "Add the KaTeX-vs-LaTeX construct check and display-math environment conversion" -- backend/deixis/workflow/report/latex_math.py tests/test_report_latex_math.py
git push origin main
```

### 5c — Kaynakça: D59 iş anahtarlarıyla `\cite{}`

#### Task 1: `bibliography.to_bibtex`'e geriye dönük uyumlu `keys` parametresi

**Files:**
- Modify: `backend/deixis/workflow/bibliography.py`
- Test: `tests/test_bibliography.py` (mevcut dosya; yoksa dosya adı `tests/test_bibliography_export.py` olabilir — yürütmeden önce `grep -rl "to_bibtex" tests/` ile teyit edilir)

**Interfaces:**
- Consumes: mevcut `bibliography._keys`, `bibliography._TYPES`, `bibliography._tex`, `bibliography._version_note` (değişmez, hepsi aynı modül içinde kalır).
- Produces: `to_bibtex(sources: list[dict[str, Any]], keys: list[str] | None = None) -> str`.

- [ ] **Step 1: Başarısız testi yaz**

```python
def test_to_bibtex_accepts_explicit_keys_and_keeps_default_behavior_when_omitted(lib):
    sources = [make_source(title="A Long Title", authors=["Ada Lovelace"], year=2020)]
    assert "@article{lovelace2020long," in to_bibtex(sources)          # unchanged default behavior
    assert "@article{Lovelace20," in to_bibtex(sources, keys=["Lovelace20"])
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_bibliography.py -k explicit_keys -v`
Expected: FAIL — `TypeError: to_bibtex() got an unexpected keyword argument 'keys'`.

- [ ] **Step 3: `to_bibtex`'i genişlet**

```python
def to_bibtex(sources: list[dict[str, Any]], keys: list[str] | None = None) -> str:
    entries = []
    for key, s in zip(keys if keys is not None else _keys(sources), sources):
        entry_type, venue_field, _ = _TYPES[_kind(s["publication_type"])]
        ...  # unchanged body
```

(Fonksiyonun geri kalanı birebir aynı kalır; yalnız `for key, s in zip(_keys(sources), sources):` satırı yukarıdaki gibi değişir.)

- [ ] **Step 4: Testleri çalıştır (yeni + mevcut regresyon)**

Run: `PYTHONPATH=backend uv run pytest tests/test_bibliography.py -v`
Expected: PASS — bugünkü `/api/researches/{id}/bibliography` rotasının davranışı değişmez (o rota `keys` geçirmez, `None` varsayılanı bugünkü `_keys()`'i kullanmaya devam eder).

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/workflow/bibliography.py tests/test_bibliography.py
git commit -m "Let to_bibtex take explicit citation keys, defaulting to its own word-based keys as before" -- backend/deixis/workflow/bibliography.py tests/test_bibliography.py
git push origin main
```

---

#### Task 2: `latex_bib.py` — D59 anahtarlarının çözümü ve geri düşüş

`backend/deixis/workflow/source_keys.py` bu not yazılırken **commit edilmiştir** (migration `0033_work_source_keys.sql`, `Store.source_key(work_id)`, `Store.assign_source_keys()` — bkz. `tests/test_source_keys.py`); MEMORY.md'deki "başka bir oturumun süren işi" notu artık güncel değildir, bu güncel bulgu §"Dilim 1'den beklenenler"de ayrıca kaydedilir. Bağımlılık yine de gerçektir: `works.source_key` bir işe yalnız `assign_source_keys()` çalıştıktan sonra atanır (uygulama başlangıcında) ve tekil bir işe hiç yazar/başlık bulunamazsa `key_stem` yine de `"Source" + yıl` üretir, yani `source_key` pratikte hep bir değer taşır — **null olduğu tek durum**, işin son başlangıçtan sonra eklenmiş olması ve henüz bir sonraki başlangıcın `assign_source_keys()`'ini görmemiş olmasıdır. Bu görev bu boşluk için raporun kendi kapsamında (kütüphane genelinde değil, yalnız bu dışa aktarımda) hesaplanan ve çakışmayan bir yedek anahtar üretir.

**Files:**
- Create: `backend/deixis/workflow/report/latex_bib.py`
- Test: `tests/test_report_latex_bib.py`

**Interfaces:**
- Consumes: `store.source_key(work_id)` (mevcut, `backend/deixis/workflow/store.py:949`), `source_keys.key_stem`, `source_keys.suffixes` (mevcut, `backend/deixis/workflow/source_keys.py`), `bibliography.to_bibtex(sources, keys=...)` (task 1).
- Produces:

```python
def resolve_cite_keys(store: Store, sources: list[dict[str, Any]]) -> list[str]: ...
def to_bibtex_for_report(store: Store, sources: list[dict[str, Any]]) -> str: ...
```

- [ ] **Step 1: Başarısız testleri yaz**

```python
# tests/test_report_latex_bib.py
def test_resolve_cite_keys_uses_the_stored_work_source_key(lib):
    store, svid = seed_source_with_key(lib, source_key="Nakano13")
    source = {"work_id": store.source(svid)["work_id"], "authors": ["Tokuko Nakano"], "title": "T", "year": 2013}
    assert resolve_cite_keys(store, [source]) == ["Nakano13"]


def test_resolve_cite_keys_falls_back_when_a_work_has_no_stored_key_yet(lib):
    store, svid = seed_source_with_key(lib, source_key=None)
    source = {"work_id": store.source(svid)["work_id"], "authors": ["Ada Lovelace"], "title": "T", "year": 2020}
    assert resolve_cite_keys(store, [source]) == ["Lovelace20"]


def test_resolve_cite_keys_avoids_a_local_collision_between_a_stored_and_a_fallback_key(lib):
    store, svid1 = seed_source_with_key(lib, source_key="Lovelace20")
    _, svid2 = seed_source_with_key(lib, source_key=None)
    sources = [
        {"work_id": store.source(svid1)["work_id"], "authors": ["Ada Lovelace"], "title": "T", "year": 2020},
        {"work_id": store.source(svid2)["work_id"], "authors": ["Ada Lovelace"], "title": "U", "year": 2020},
    ]
    assert resolve_cite_keys(store, sources) == ["Lovelace20", "Lovelace20b"]


def test_to_bibtex_for_report_keys_entries_by_source_key_not_the_word_based_default(lib):
    store, svid = seed_source_with_key(lib, source_key="Nakano13")
    source = make_source(svid, title="Molecular Communication Scheduling", authors=["Tokuko Nakano"], year=2013)
    assert "@article{Nakano13," in to_bibtex_for_report(store, [source])
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_latex_bib.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: `latex_bib.py`'yi yaz**

```python
"""Cite keys for the LaTeX export, from the D59 work key (Store.source_key, backend/deixis/workflow/
source_keys.py), reusing bibliography.py's field-building and escaping (D16) with those keys instead of
its own word-based _keys(). D59 is committed and wired (migration 0033, Store.assign_source_keys at
startup); a None here means only that a work was added since the last startup's backfill."""
from __future__ import annotations

from typing import Any

from deixis.workflow import bibliography, source_keys
from deixis.workflow.store import Store


def resolve_cite_keys(store: Store, sources: list[dict[str, Any]]) -> list[str]:
    seen = {k for k in (store.source_key(s["work_id"]) for s in sources) if k}
    keys: list[str] = []
    for s in sources:
        key = store.source_key(s["work_id"])
        if key is None:
            stem, _basis = source_keys.key_stem(s["authors"], s["title"], s["year"])
            for suffix in source_keys.suffixes():
                candidate = stem + suffix
                if candidate not in seen:
                    key = candidate
                    seen.add(candidate)
                    break
        keys.append(key)
    return keys


def to_bibtex_for_report(store: Store, sources: list[dict[str, Any]]) -> str:
    return bibliography.to_bibtex(sources, keys=resolve_cite_keys(store, sources))
```

- [ ] **Step 4: Çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_latex_bib.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/workflow/report/latex_bib.py tests/test_report_latex_bib.py
git commit -m "Key the LaTeX bibliography by each work's D59 source_key with a local fallback for a missing one" -- backend/deixis/workflow/report/latex_bib.py tests/test_report_latex_bib.py
git push origin main
```

**Neden klasik `bibtex`, `biblatex`/`biber` değil.** `bibliography.py` zaten Zotero'nun BibTeX çevirmenini hedefler ve klasik `\bibliographystyle{IEEEtran}` + `bibtex` (biber değil) kullanır. Klasik `bibtex`'in Unicode ile bilinen sorunu **sıralamadır** (aksanlı harflerin harmanlama sırası); IEEEtran'ın `IEEEtran` stili **sırasız**dır (metindeki ilk geçiş sırasını korur, §9), yani sıralama hiç devreye girmez. Alan içerikleri (başlık, yazar) `bibtex` tarafından yalnız kopyalanıp `.bbl`'e yazılır, tipografiye karışmaz; dosya UTF-8 kaydedildiği ve XeLaTeX Unicode yerlisi olduğu sürece Türkçe başlık/yazar adları sorunsuz basılır. Bu yüzden `biblatex`+`biber` gibi yeni bir bağımlılık zinciri eklenmez.

### 5d — Tablo hücresi durumları ve `table*` bölme

#### Task 1: Hücre durumunun düz metni

**Files:**
- Create: `backend/deixis/workflow/report/latex_table.py` (bu görevde yalnız `cell_text`)
- Test: `tests/test_report_latex_table.py`

**Interfaces:**
- Consumes: `latex_text.escape_prose`, `latex_math.convert_math_span` (yalnız `text` biçimli değer hücrelerinde, satır içi matematik taşıyabilir).
- Produces: `cell_text(cell: dict, language: str) -> tuple[str, list[str]]` (metin, uyarılar).

Yedi hücre durumu Markdown dışa aktarımıyla (dilim 1) aynı düz sözcüklerle yazılır — `apps/web/src/EvidenceTable.tsx`'in bugünkü İngilizce etiketleriyle birebir, artı Türkçe karşılıkları:

| Durum | English (EvidenceTable.tsx) | Türkçe |
|---|---|---|
| `not_applicable` | Not applicable | Uygulanamaz |
| `inaccessible` | No text | Metin yok |
| `not_found_in_inspected_scope` | Not found in the text read | İncelenen metinde bulunamadı |
| `not_reported` | (tabloda ayrı etiketlenmez, "Not reported" bugünkü koddan) | Bildirilmedi |
| `unknown` | (tabloda ayrı etiketlenmez) | Bilinmiyor |
| `not_verified` | (tabloda ayrı etiketlenmez) | Doğrulanmamış |

Okuma derinliği hücrede **ayrı gösterilmez** (§9'un renk olmadan gösterme sorusu): renk yoktur, madalyon yoktur; VIII'in özet/tam-metin oranı zaten toplulaştırılmış olarak anlatır (§6, §8 kural #7 "II ve VIII'deki sayılar corpus ile birebir"). Hücre başına derinliği tekrar yazmak tabloyu kalabalıklaştırır ve zaten paydalı toplama cümlesiyle çelişme riski taşır; bu yüzden atlanır, bu bir kayıptır ve Açık noktalar'da yazılır.

- [ ] **Step 1: Başarısız testleri yaz**

```python
def test_state_cells_use_the_same_plain_wording_as_the_markdown_export(lib):
    assert cell_text({"state": "not_applicable", "value": None}, "en") == ("Not applicable", [])
    assert cell_text({"state": "not_applicable", "value": None}, "tr") == ("Uygulanamaz", [])
    assert cell_text({"state": "not_found_in_inspected_scope", "value": None}, "tr") == ("İncelenen metinde bulunamadı", [])


def test_value_cell_prints_by_answer_format():
    assert cell_text({"state": "value", "value": {"number": 40, "unit": "düğüm"}}, "tr") == ("40 düğüm", [])
    assert cell_text({"state": "value", "value": {"answer": "no"}}, "tr") == ("Hayır", [])
    assert cell_text({"state": "value", "value": {"answer": "yes"}}, "en") == ("Yes", [])
    cell = {"state": "value", "value": {"option_ids": ["opt_1"]}, "column_options": [{"id": "opt_1", "label": "Gecikme"}]}
    assert cell_text(cell, "tr") == ("Gecikme", [])


def test_text_value_cell_escapes_prose_and_converts_inline_math():
    cell = {"state": "value", "value": {"text": r"50% $T_{\max}$ ile sınırlı"}}
    text, warnings = cell_text(cell, "tr")
    assert text == r"50\% $T_{\max}$ ile sınırlı"
    assert warnings == []
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_latex_table.py -k cell_text -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: `cell_text`'i yaz**

```python
"""Table I as one or more table* floats (P6 slice 5, hard part 5)."""
from __future__ import annotations

from deixis.workflow.report.latex_math import convert_math_span
from deixis.workflow.report.latex_text import escape_mixed, escape_prose

_STATE_TEXT = {
    "en": {"not_applicable": "Not applicable", "inaccessible": "No text",
           "not_found_in_inspected_scope": "Not found in the text read", "not_reported": "Not reported",
           "unknown": "Unknown", "not_verified": "Not verified"},
    "tr": {"not_applicable": "Uygulanamaz", "inaccessible": "Metin yok",
           "not_found_in_inspected_scope": "İncelenen metinde bulunamadı", "not_reported": "Bildirilmedi",
           "unknown": "Bilinmiyor", "not_verified": "Doğrulanmamış"},
}
_YES_NO = {"en": {"yes": "Yes", "no": "No"}, "tr": {"yes": "Evet", "no": "Hayır"}}


def cell_text(cell: dict, language: str) -> tuple[str, list[str]]:
    state = cell["state"]
    if state != "value":
        return _STATE_TEXT[language][state], []
    value = cell["value"]
    if "text" in value:
        return escape_mixed(value["text"], lambda span: convert_math_span(span, label=None))
    if "number" in value:
        unit = f" {value['unit']}" if value.get("unit") else ""
        return f"{value['number']}{unit}", []
    if "answer" in value:
        return _YES_NO[language][value["answer"]], []
    if "option_ids" in value:
        labels = [o["label"] for o in cell["column_options"] if o["id"] in value["option_ids"]]
        return escape_prose(", ".join(labels)), []
    return "", []
```

- [ ] **Step 4: Çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_latex_table.py -k cell_text -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/workflow/report/latex_table.py tests/test_report_latex_table.py
git commit -m "Print every evidence-cell state and value format the same way for the LaTeX table" -- backend/deixis/workflow/report/latex_table.py tests/test_report_latex_table.py
git push origin main
```

---

#### Task 2: `table*` bölme

Bir `table*` **bölünemeyen bir float**tır: sayfa yüksekliğini aşan bir tabloyu (10–13 sütun, ~50 satır, `\scriptsize`'da bile) hiçbir ortam sayfalar arasında otomatik bölemez, çünkü float içeriği tek bir kutu olarak yerleştirilir. `longtable`/`ltablex` gibi paketler bunu tek sütun genişliğinde çözer, ama iki sütunlu bir `table*`'ın genişliğini (`\textwidth`, iki sütun birden) korurken sayfalar arası bölünmeyi de istemek (`ltxtable`/`ltablex`'in iki sütunlu düzenle güvenilir birleşimi yoktur, elle sayfa kırılması duyarlılığı gerektirir ve derlemeden doğrulanamaz) bu dilimin kapsamı dışında bırakılır. Bunun yerine **bölme stratejisi** seçildi: `MAX_ROWS_PER_PART` (varsayılan 20) satırdan uzun bir tablo TABLE I(a), I(b)… gibi ayrı `table*` parçalarına bölünür, her biri kendi sayfasına sığacak kadar küçüktür. **Kaybedilen:** (1) tek bir "Tablo I" nesnesi yerine harfli parçalar; düzyazı hâlâ yalnız "Tablo I" der, ama basılı tablo birden çok yerde görünür. (2) Bölme noktası **gerçek satır yüksekliğine değil sabit satır sayısına** dayanır — hiçbir derleme yapılmadığı için (§ genel kısıt) olağandışı uzun bir hücre metni olan bir parçanın yine de sayfayı taşırması mümkündür; bu ölçülmedi, yalnız söylenir. Alternatif olarak düşünülüp reddedilen: yatay (landscape) döndürme (`pdflscape`) — bir `table*`'ı IEEEtran'ın iki sütunlu gövdesi içinde döndürmek, float yerleştirmesiyle güvenilir birleşmez ve derlenmeden doğrulanamayacak bir sayfa-kırılması duyarlılığı ekler; bu yüzden v1'de uygulanmadı, yalnız not edildi.

**Files:**
- Modify: `backend/deixis/workflow/report/latex_table.py`
- Test: `tests/test_report_latex_table.py`

**Interfaces:**
- Produces: `render_table(columns: list[dict], rows: list[dict], language: str, caption: str) -> tuple[str, list[str]]`. `columns`: `[{"name": str}, ...]`. `rows`: `[{"source_key": str, "cells": [cell, ...]}, ...]` (bir hücre `cell_text`'in beklediği şekil).

- [ ] **Step 1: Başarısız testleri yaz**

```python
def test_a_table_within_the_row_limit_is_one_table_star_with_a_plain_caption():
    columns = [{"name": "Yöntem"}]
    rows = [{"source_key": "Nakano13", "cells": [{"state": "value", "value": {"text": "X"}}]}]
    tex, warnings = render_table(columns, rows, "tr", "TABLE I. Included sources")
    assert tex.count("\\begin{table*}") == 1
    assert "\\caption{TABLE I. Included sources}" in tex
    assert warnings == []


def test_a_table_over_the_row_limit_is_split_into_lettered_parts(monkeypatch):
    import deixis.workflow.report.latex_table as mod
    monkeypatch.setattr(mod, "MAX_ROWS_PER_PART", 2)
    columns = [{"name": "Yöntem"}]
    rows = [{"source_key": f"S{i}", "cells": [{"state": "unknown", "value": None}]} for i in range(5)]
    tex, warnings = render_table(columns, rows, "en", "TABLE I. Included sources")
    assert tex.count("\\begin{table*}") == 3
    assert "TABLE I. Included sources(a) (1 of 3)" in tex
    assert "TABLE I. Included sources(c) (3 of 3)" in tex


def test_cell_conversion_warnings_are_collected_across_the_whole_table():
    columns = [{"name": "Yöntem"}]
    rows = [{"source_key": "S1", "cells": [{"state": "value", "value": {"text": r"$\R$"}}]}]
    _tex, warnings = render_table(columns, rows, "en", "TABLE I")
    assert any("\\R" in w for w in warnings)
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_latex_table.py -k render_table -v`
Expected: FAIL — `AttributeError: module has no attribute 'render_table'`.

- [ ] **Step 3: `render_table`'ı ekle**

```python
MAX_ROWS_PER_PART = 20


def render_table(columns: list[dict], rows: list[dict], language: str, caption: str) -> tuple[str, list[str]]:
    parts = [rows[i:i + MAX_ROWS_PER_PART] for i in range(0, len(rows), MAX_ROWS_PER_PART)] or [[]]
    align = "l" + " X" * len(columns)
    source_header = {"en": "Source", "tr": "Kaynak"}[language]
    warnings: list[str] = []
    out: list[str] = []
    for i, part in enumerate(parts):
        label = f"{caption}({chr(ord('a') + i)}) ({i + 1} of {len(parts)})" if len(parts) > 1 else caption
        out += [
            "\\begin{table*}[t]", f"\\caption{{{escape_prose(label)}}}", "\\centering", "\\scriptsize",
            f"\\begin{{tabularx}}{{\\textwidth}}{{{align}}}", "\\toprule",
            " & ".join([source_header] + [escape_prose(c["name"]) for c in columns]) + " \\\\", "\\midrule",
        ]
        for row in part:
            printed = [row["source_key"]]
            for cell in row["cells"]:
                text, cell_warnings = cell_text(cell, language)
                printed.append(text)
                warnings += cell_warnings
            out.append(" & ".join(printed) + " \\\\")
        out += ["\\bottomrule", "\\end{tabularx}", "\\end{table*}"]
    return "\n".join(out), warnings
```

- [ ] **Step 4: Çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_latex_table.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/workflow/report/latex_table.py tests/test_report_latex_table.py
git commit -m "Split TABLE I into page-sized table* parts instead of one unbreakable float" -- backend/deixis/workflow/report/latex_table.py tests/test_report_latex_table.py
git push origin main
```

### 5e — Ana derleyici ve golden-file testi

#### Task 1: `render_latex()` — saf birleştirici

**Files:**
- Create: `backend/deixis/workflow/report/latex_export.py`

**Interfaces:**
- Consumes: `latex_text.escape_prose`/`escape_mixed`, `latex_math.convert_math_span`, `latex_table.render_table`, `latex_bib.to_bibtex_for_report`.
- Produces:

```python
from dataclasses import dataclass

@dataclass
class LatexBundle:
    tex: str
    bib: str
    warnings: list[str]
    filename_stem: str

def render_latex(report: dict, sections: list[dict], sources: list[dict], store, table: dict) -> LatexBundle:
    """Pure: report/sections/sources/table are plain dicts (report_view/report/table shape), no I/O.
    store is only used for latex_bib.to_bibtex_for_report's D59 lookups (source_key), never for other reads."""
```

`render_latex` şu sırayı yürür (dilim 1'in `to_markdown`'ıyla aynı yürüyüş, farklı çıktı dili):

1. `\documentclass[journal]{IEEEtran}` ve sabit preamble (bkz. golden fixture) — XeLaTeX seçildi çünkü Türkçe harfler (`ı İ ğ ş ç ö ü`) `fontspec` altında herhangi bir font-kodlaması olmadan doğrudan basılır; `pdfLaTeX` + `inputenc`/`babel`'in Türkçe noktasız-ı için bilinen özel-durum haritalaması gerektirmesi (klasik bir LaTeX tuzağı) böylece atlanır. Bedeli: görev 5g'nin isteğe bağlı derleme testi `xelatex` ister, `pdflatex` değil.
2. `\title{}` rapor planının kapsam cümlesinden türeyen başlık (dilim 1'in `research_title` adımı); `\author{}` gerçek bir kişiyi taklit etmez, sabit "Generated by DEIXIS / Hakem denetiminden geçmemiştir" bloğu.
3. Rapor `draft` ise `\maketitle`'dan hemen sonra düz, renksiz bir "TASLAK: `<section>` doğrulanmadı." paragrafı (§2 karar 11; sürüm numarası hiç yazılmaz).
4. `\begin{abstract}…\end{abstract}`, sonra `\begin{IEEEkeywords}…\end{IEEEkeywords}` (D44 kavram sözlüğünden, yeni terim eklenmez).
5. Sabit iskeletteki her bölüm `\section{<Türkçe/İngilizce başlık>}`; `paragraph` numarasına göre gruplanmış iddialar tek paragrafta `escape_mixed` ile yazılır; `table_ref: "TABLE_I"` gören iddiadan hemen sonra `latex_table.render_table` gömülür; `equation_ref` gören her denklem `latex_math.convert_math_span(span, label=f"eq:{equation_ref}")` ile numaralanır ve düzyazıda `\eqref{eq:EQ1}` olarak anılır (aşağıdaki not).
6. VI'nın adayları düz paragraf, "denetlenmemiş aday; kill-search yapılmadı" ibaresiyle (§7, kod hiçbir sözcüğü değiştirmez, yalnız kaçışlar).
7. `\bibliographystyle{IEEEtran}` + `\bibliography{<filename_stem>}`.
8. Kapanış satırı: "DEIXIS ile üretildi; korpus: …" (II'nin sayılarından, dilim 1'in Markdown kapanışıyla birebir aynı sayılar).

**Denklem numaralandırması `\eqref` ile, metne gömülü sabit sayıyla değil.** Dilim 1'in Markdown dışa aktarımı `equation_ref`'i düz metne "(1)" olarak gömer (`numbering.py::number_equations`, sabit bir sayı). LaTeX'te bunun yerine `equation` ortamının **kendi otomatik sayacı** kullanılır ve metindeki her `equation_ref` kullanımı `\eqref{eq:EQ<n>}`'e çevrilir: ikisi aynı sayıyı üretir, çünkü her iki numaralandırma da aynı sırayla (bölüm `ordinal`'ı, sonra `paragraph`, sonra iddia sırası) yürür ve her görüntülenen denklem dosyada tam bir kez basılır. Bu, LaTeX'in kendi sayacıyla `number_equations()`'ın hesapladığı sayının **aynı belge içinde asla ayrışmayacağını** derleme olmadan da garanti eder (aynı sırayı iki kez yürütmek yerine LaTeX'e devredilir) ve `\eqref`'in çapraz-referans/`hyperref` bağlantısı bedavadan gelir. Golden-file testi (task 2) bunun `number_equations()`'ın sırasıyla aynı olduğunu doğrudan karşılaştırarak doğrular.

- [ ] **Step 1–4:** Bu görev saf bir birleştirme fonksiyonudur; kendi başarısız/geçen testi **task 2'nin golden-file testidir** (ayrı, daha küçük testler yazmak burada gereksiz tekrar olurdu — birleştiricinin her dalı zaten alt modüllerde test edildi). Bu yüzden 5e Task 1 ve Task 2 tek bir commit'te birlikte yürütülür.

#### Task 2: Golden-file testi — SYNTHETIC sabit rapor

**Files:**
- Create: `tests/fixtures/research/report-latex-golden.py`, `tests/test_report_latex_export.py`

Sentetik rapor (etiket: SYNTHETIC): 3 kaynak, 4 sütunlu bir tablo (her 7 hücre durumu en az bir kez), IV'te satır içi matematikli bir iddia ve görüntülenen bir denklem, VI'da iki aday (`corpus_absence`, `stated_limitation`), rapor durumu `draft` (VI doğrulanmadı).

```python
# tests/fixtures/research/report-latex-golden.py
"""SYNTHETIC fixture for the LaTeX export golden-file test (P6 slice 5)."""

REPORT = {
    "id": "rpt_test1", "status": "draft", "language": "tr", "report_version": None,
    "draft_reason_section": "VI",
    "title": "Gecikmeyle Sınırlı Moleküler Haberleşme Çizelgelemesi Üzerine Sınırlı Kanıt Raporu",
    "abstract": "Bu rapor, gecikmeyle sınırlı moleküler haberleşme çizelgelemesi konusunda incelenen "
                "3 kaynaktan üretilmiştir; bulgular özet ve tam metin karışımına dayanır ve TASLAK "
                "durumundadır.",
    "index_terms": ["moleküler haberleşme", "çizelgeleme", "gecikme"],
    "corpus": {"found": 120, "unique": 95, "screened": 40, "included": 3, "full_text": 2},
}

SOURCES = [
    {"work_id": "wrk_1", "source_key": "Nakano13", "authors": ["Tokuko Nakano"], "year": 2013,
     "title": "Molecular Communication Scheduling with Bounded Delay",
     "venue": "IEEE Transactions on Molecular, Biological and Multi-Scale Communications",
     "publication_type": "journal-article", "doi": "10.1109/TMBMC.2013.000001",
     "landing_url": None, "arxiv_id": None, "version_label": "publishedVersion",
     "volume": None, "issue": None, "pages": None},
    {"work_id": "wrk_2", "source_key": "Ozturk21", "authors": ["Ayşe Öztürk"], "year": 2021,
     "title": "Enerji Kısıtlı Ağlarda Gecikme Modellemesi", "venue": "SYNTHETIC Workshop on Networks",
     "publication_type": "journal-article", "doi": None, "landing_url": None, "arxiv_id": None,
     "version_label": "submittedVersion", "volume": None, "issue": None, "pages": None},
    {"work_id": "wrk_3", "source_key": None, "authors": ["J. Ford"], "year": 2022,
     "title": "SYNTHETIC Energy-Aware Routing", "venue": None, "publication_type": "journal-article",
     "doi": None, "landing_url": None, "arxiv_id": None, "version_label": None,
     "volume": None, "issue": None, "pages": None},
]

TABLE = {
    "columns": [{"name": "Yöntem"}, {"name": "Örneklem"}, {"name": "Hakemli mi?"}, {"name": "Ölçüt"}],
    "rows": [
        {"source_key": "Nakano13", "cells": [
            {"state": "value", "value": {"text": r"Gecikmeyi $T_{\max}$ ile sınırlayan rastgele erişim tabanlı bir çizelgeleme yaklaşımı önerilmiştir."}},
            {"state": "value", "value": {"number": 40, "unit": "düğüm"}},
            {"state": "not_verified", "value": None},
            {"state": "value", "value": {"option_ids": ["opt_delay"]}, "column_options": [{"id": "opt_delay", "label": "Gecikme"}, {"id": "opt_throughput", "label": "Verim"}]},
        ]},
        {"source_key": "Ozturk21", "cells": [
            {"state": "not_found_in_inspected_scope", "value": None},
            {"state": "inaccessible", "value": None},
            {"state": "value", "value": {"answer": "no"}},
            {"state": "not_applicable", "value": None},
        ]},
        {"source_key": "Ford22", "cells": [
            {"state": "unknown", "value": None},
            {"state": "not_reported", "value": None},
            {"state": "value", "value": {"answer": "yes"}},
            {"state": "value", "value": {"option_ids": ["opt_throughput"]}, "column_options": [{"id": "opt_delay", "label": "Gecikme"}, {"id": "opt_throughput", "label": "Verim"}]},
        ]},
    ],
}

SECTIONS = [
    {"section_id": "II", "ordinal": 1, "paragraph_text":
        "İnceleme 120 kaydı buldu, tekilleştirmeden sonra 95 iş kaldı, 40'ı tarandı ve 3'ü dahil "
        "edildi; dahil kaynaklardan 2'sinin tam metni okunabildi."},
    {"section_id": "IV", "ordinal": 2, "claims": [
        {"claim_key": "IV.1", "paragraph": 1, "table_ref": "TABLE_I", "citation_source_keys": [],
         "text": "Tablo I, incelenen kaynaklardan çıkarılan kanıtı özetler."},
        {"claim_key": "IV.2", "paragraph": 2, "table_ref": None, "citation_source_keys": ["Nakano13"],
         "text": r"Gecikmeyi $T_{\max}$ ile sınırlayan rastgele erişim tabanlı bir çizelgeleme yaklaşımı önerilmiştir."},
        {"claim_key": "IV.3", "paragraph": 3, "table_ref": None, "equation_ref": "EQ1",
         "citation_source_keys": ["Ozturk21"],
         "text": r"İncelenen pasajda aşağıdaki gecikme kısıtı verilmiştir: "
                 r"$$T_{\text{gecikme}} \leq \dfrac{L}{R} + \tau, \quad \tau \geq 0$$ "
                 r"Bu ifade Marker ile okunmuştur ve sayfayla karşılaştırılarak denetlenmelidir."},
        {"claim_key": "IV.4", "paragraph": 3, "table_ref": None, "citation_source_keys": [],
         "text": "Tam metni incelenen 2 kaynağın 1'i gecikmeyi doğrudan ölçmüştür."},
    ]},
    {"section_id": "VI", "ordinal": 3, "gaps": [
        {"gap_id": "gap1", "kind": "corpus_absence",
         "text": "İncelenen 3 kaynağın tam metni okunan 2'sinde enerji tüketimi ele alınmamıştır; "
                 "bu aday incelenmemiştir, kill-search yapılmadı."},
        {"gap_id": "gap2", "kind": "stated_limitation",
         "text": "Nakano13 kendi sınırlaması olarak örneklem büyüklüğünün küçük olduğunu belirtir; "
                 "bu aday incelenmemiştir, kill-search yapılmadı."},
    ]},
]
```

Beklenen `.tex` (tam, `render_latex(REPORT, SECTIONS, SOURCES, store, TABLE).tex`'in eşiti — testte `textwrap.dedent`/üçlü tırnakla tek sabit olarak tutulur):

```latex
\documentclass[journal]{IEEEtran}
\usepackage{fontspec}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage{bm}
\usepackage{xcolor}
\usepackage{cite}
\usepackage{tabularx}
\usepackage{booktabs}
\usepackage{hyperref}

\begin{document}

\title{Gecikmeyle Sınırlı Moleküler Haberleşme Çizelgelemesi Üzerine Sınırlı Kanıt Raporu}
\author{\IEEEauthorblockN{Generated by DEIXIS}\IEEEauthorblockA{Hakem denetiminden geçmemiştir; tek bir araştırma oturumundan üretilmiştir.}}

\maketitle

\noindent\textbf{TASLAK: VI doğrulanmadı.}

\begin{abstract}
Bu rapor, gecikmeyle sınırlı moleküler haberleşme çizelgelemesi konusunda incelenen 3 kaynaktan üretilmiştir; bulgular özet ve tam metin karışımına dayanır ve TASLAK durumundadır.
\end{abstract}

\begin{IEEEkeywords}
moleküler haberleşme, çizelgeleme, gecikme
\end{IEEEkeywords}

\section{Review Methodology}
İnceleme 120 kaydı buldu, tekilleştirmeden sonra 95 iş kaldı, 40'ı tarandı ve 3'ü dahil edildi; dahil kaynaklardan 2'sinin tam metni okunabildi.

\section{Literature Synthesis}
Tablo I, incelenen kaynaklardan çıkarılan kanıtı özetler.

\begin{table*}[t]
\caption{TABLE I. Included sources and extracted evidence}
\centering
\scriptsize
\begin{tabularx}{\textwidth}{l X X X X}
\toprule
Kaynak & Yöntem & Örneklem & Hakemli mi? & Ölçüt \\
\midrule
Nakano13 & Gecikmeyi $T_{\max}$ ile sınırlayan rastgele erişim tabanlı bir çizelgeleme yaklaşımı önerilmiştir. & 40 düğüm & Doğrulanmamış & Gecikme \\
Ozturk21 & İncelenen metinde bulunamadı & Metin yok & Hayır & Uygulanamaz \\
Ford22 & Bilinmiyor & Bildirilmedi & Evet & Verim \\
\bottomrule
\end{tabularx}
\end{table*}

Gecikmeyi $T_{\max}$ ile sınırlayan rastgele erişim tabanlı bir çizelgeleme yaklaşımı önerilmiştir \cite{Nakano13}.

İncelenen pasajda aşağıdaki gecikme kısıtı verilmiştir:
\begin{equation}
\label{eq:EQ1}
T_{\text{gecikme}} \leq \dfrac{L}{R} + \tau, \quad \tau \geq 0
\end{equation}
Bu ifade Marker ile okunmuştur ve sayfayla karşılaştırılarak denetlenmelidir \cite{Ozturk21}. Tam metni incelenen 2 kaynağın 1'i gecikmeyi doğrudan ölçmüştür.

\section{Candidate Unanswered Aspects}
İncelenen 3 kaynağın tam metni okunan 2'sinde enerji tüketimi ele alınmamıştır; bu aday incelenmemiştir, kill-search yapılmadı.

Nakano13 kendi sınırlaması olarak örneklem büyüklüğünün küçük olduğunu belirtir; bu aday incelenmemiştir, kill-search yapılmadı.

\bibliographystyle{IEEEtran}
\bibliography{rpt_test1}

DEIXIS ile üretildi; korpus: bulunan 120, tekil 95, taranan 40, dahil 3, tam metinli 2.

\end{document}
```

Beklenen `.bib` (yalnız atıf alan iki kaynak; Ford22 tabloda var ama hiç `\cite` almadığı için kaynakçada yok, §8 kural #8 "her kayıt en az bir atıfta"):

```bibtex
@article{Nakano13,
  title = {Molecular Communication Scheduling with Bounded Delay},
  author = {Tokuko Nakano},
  year = {2013},
  journal = {IEEE Transactions on Molecular, Biological and Multi-Scale Communications},
  doi = {10.1109/TMBMC.2013.000001},
  note = {Source version read in DEIXIS: published version},
}

@article{Ozturk21,
  title = {Enerji Kısıtlı Ağlarda Gecikme Modellemesi},
  author = {Ayşe Öztürk},
  year = {2021},
  journal = {SYNTHETIC Workshop on Networks},
  note = {Source version read in DEIXIS: submitted manuscript},
}
```

- [ ] **Step 1: Başarısız testi yaz**

```python
# tests/test_report_latex_export.py
from tests.fixtures.research.report_latex_golden import REPORT, SOURCES, TABLE, SECTIONS
EXPECTED_TEX = """...yukarıdaki tam metin..."""
EXPECTED_BIB = """...yukarıdaki tam metin..."""


def test_render_latex_matches_the_golden_fixture_byte_for_byte(store_with_sources):
    bundle = render_latex(REPORT, SECTIONS, SOURCES, store_with_sources, TABLE)
    assert bundle.tex == EXPECTED_TEX
    assert bundle.bib == EXPECTED_BIB
    assert "unrecognized macro" not in " ".join(bundle.warnings)  # this fixture's math is all known-safe
    assert bundle.filename_stem == "rpt_test1"


def test_no_internal_identifier_leaks_into_the_tex_or_bib(store_with_sources):
    bundle = render_latex(REPORT, SECTIONS, SOURCES, store_with_sources, TABLE)
    for leaked in ("claim_key", "IV.2", "source_stated", "cel_", "gap1", '"'):
        assert leaked not in bundle.tex
        assert leaked not in bundle.bib
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_latex_export.py -v`
Expected: FAIL — `ModuleNotFoundError` ya da (dosya varsa) metin farkı.

- [ ] **Step 3: `render_latex`'i yaz** (yukarıdaki 8 adımlı sıra; sabit preamble ve bölüm başlıkları dile göre `{"tr": {...}, "en": {...}}` sözlüğünden).

- [ ] **Step 4: Çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_latex_export.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/workflow/report/latex_export.py tests/test_report_latex_export.py \
  tests/fixtures/research/report-latex-golden.py
git commit -m "Add the LaTeX export assembler with a golden-file test covering every table cell state" -- backend/deixis/workflow/report/latex_export.py tests/test_report_latex_export.py tests/fixtures/research/report-latex-golden.py
git push origin main
```

### 5f — Zip teslimatı ve API rotası

**Files:**
- Modify: `backend/deixis/workflow/report/latex_export.py` (bu görevde `to_zip`, `filename`, `to_latex` sarmalayıcısı eklenir), `backend/deixis/api/app.py`
- Test: `tests/test_report_latex_export.py`, `tests/test_report_api.py` (dilim 1'de yaratılır; bu görev orada bir dal ekler)

**Interfaces:**
- Consumes: dilim 1'in `ReportStore` (tam alan adları dilim 1 kodlanınca teyit edilir — bkz. Açık noktalar), `render_latex` (5e).
- Produces:

```python
def to_zip(bundle: LatexBundle) -> bytes: ...
def filename(bundle: LatexBundle) -> str: ...  # "deixis-<slug>-report.zip", bibliography.filename()'in deseni
def to_latex(store: Store, reports: "ReportStore", report_id: str) -> LatexBundle: ...  # dilim 1'e bağlı ince sarmalayıcı
```

Rota (dilim 1'in `GET .../reports/{report_id}/export?format=markdown`'ını genişletir):

```python
@app.get("/api/researches/{research_id}/reports/{report_id}/export")
async def export_report(research_id: str, report_id: str, request: Request, format: str = "markdown") -> Response:
    if format == "latex":
        bundle = latex_export.to_latex(store, reports_of(request), report_id)
        body = latex_export.to_zip(bundle)
        headers = {
            "Content-Disposition": f'attachment; filename="{latex_export.filename(bundle)}"',
            "X-Deixis-Export-Warnings": json.dumps(bundle.warnings[:20]),
        }
        return Response(body, media_type="application/zip", headers=headers)
    text = report_export.to_markdown(store, reports_of(request), report_id)  # dilim 1'in mevcut dalı, değişmez
    ...
```

`X-Deixis-Export-Warnings` en fazla 20 uyarı taşır (HTTP başlık boyutu için güvenli bir üst sınır; her uyarı zaten kısa bir cümledir, task 5b/5d'nin ürettiği metinler); 20'den fazlası varsa son eleman `"... and N more"` ile kapatılır.

- [ ] **Step 1: Başarısız testleri yaz**

```python
def test_to_zip_contains_the_tex_and_bib_files_named_by_the_report_id():
    bundle = LatexBundle(tex="\\documentclass{...}", bib="@article{...}", warnings=[], filename_stem="rpt_test1")
    with zipfile.ZipFile(io.BytesIO(to_zip(bundle))) as zf:
        assert set(zf.namelist()) == {"rpt_test1.tex", "rpt_test1.bib"}
        assert zf.read("rpt_test1.tex").decode() == bundle.tex


def test_export_route_with_format_latex_returns_a_zip_with_a_warnings_header(tmp_path):
    ...  # app_for/session/create/start_report/wait_run deseni (dilim 1'in 1k testlerindeki gibi)
    resp = client.get(f"/api/researches/{rid}/reports/{report_id}/export?format=latex")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert "attachment" in resp.headers["content-disposition"]
    warnings = json.loads(resp.headers["x-deixis-export-warnings"])
    assert isinstance(warnings, list)


def test_export_route_with_format_markdown_is_unchanged():
    ...  # dilim 1'in mevcut testinin regresyon kontrolü
```

- [ ] **Step 2: Çalıştır, başarısız olduğunu doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_latex_export.py tests/test_report_api.py -k latex -v`
Expected: FAIL.

- [ ] **Step 3: `to_zip`/`filename`/`to_latex`'i ve rota dalını yaz**

```python
import io
import zipfile


def to_zip(bundle: LatexBundle) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{bundle.filename_stem}.tex", bundle.tex)
        zf.writestr(f"{bundle.filename_stem}.bib", bundle.bib)
    return buf.getvalue()


def filename(bundle: LatexBundle) -> str:
    return f"deixis-{bundle.filename_stem}-report.zip"
```

`to_latex(store, reports, report_id)`: `reports.report(report_id)`, `reports.sections(report_id)`, dahil kaynakların listesini `research_view`'dan (`bibliography.export_sources`'ın yaptığı gibi) okuyup `render_latex`'e geçirir — kesin alan adları dilim 1 kodlanınca netleşir (Açık noktalar).

- [ ] **Step 4: Çalıştır, geçtiğini doğrula**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_latex_export.py tests/test_report_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/workflow/report/latex_export.py backend/deixis/api/app.py \
  tests/test_report_latex_export.py tests/test_report_api.py
git commit -m "Deliver the LaTeX export as a zip through the report export route's format parameter" -- backend/deixis/workflow/report/latex_export.py backend/deixis/api/app.py tests/test_report_latex_export.py tests/test_report_api.py
git push origin main
```

### 5g — İsteğe bağlı geliştirici derleme testi

DEIXIS hiçbir TeX kurulumu **gerektirmez**; bu görev yalnız geliştiricinin makinesinde `xelatex`/`latexmk`/`tectonic` varsa çalışan, yoksa atlanan tek bir testtir. Bu test geçtiğinde bile "dosya derlenir" iddiası yalnız **o fixture için, o TeX dağıtımında** doğrulanmış olur; CI'da hiçbir zaman çalışmaz (TeX kurulu değildir) ve bu yüzden normal test koşusunda "derlenebilirlik" hiç ölçülmez — bu açıkça söylenir, gizlenmez.

**Files:**
- Modify: `tests/test_report_latex_export.py`

**Interfaces:**
- Consumes: `shutil.which` (stdlib), `tests/test_ocr.py`'nin `needs_tesseract` deseni (mevcut).

- [ ] **Step 1: İşareti ve testi yaz**

```python
import shutil
import subprocess

needs_xelatex = pytest.mark.skipif(shutil.which("latexmk") is None, reason="latexmk is not installed")


@needs_xelatex
def test_the_golden_fixture_actually_compiles_with_xelatex(tmp_path):
    """Optional, developer-machine-only: proves nothing about CI, which has no TeX installed."""
    bundle = render_latex(REPORT, SECTIONS, SOURCES, store_with_sources(), TABLE)
    (tmp_path / f"{bundle.filename_stem}.tex").write_text(bundle.tex)
    (tmp_path / f"{bundle.filename_stem}.bib").write_text(bundle.bib)
    result = subprocess.run(
        ["latexmk", "-xelatex", "-interaction=nonstopmode", "-halt-on-error", f"{bundle.filename_stem}.tex"],
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout[-4000:]
    assert (tmp_path / f"{bundle.filename_stem}.pdf").exists()
```

- [ ] **Step 2: Çalıştır (varsa `latexmk`, yoksa atlanır)**

Run: `PYTHONPATH=backend uv run pytest tests/test_report_latex_export.py -k compiles -v`
Expected: `latexmk` yoksa `SKIPPED`; varsa PASS. (Yürütme ortamında `which latexmk` ile önce kontrol edilmeli; bu görev CI'da hiçbir şeyi kırmaz çünkü CI'da atlanır.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_report_latex_export.py
git commit -m "Add an optional developer-only compile check for the LaTeX export, skipped without latexmk" -- tests/test_report_latex_export.py
git push origin main
```

### 5h — Arayüz: dışa aktarma seçeneği, i18n, uyarı bildirimi

`.impeccable.md` önce okunur (`docs/product/p6-report-design.md`'nin "Aesthetic Direction"/"Design Principles" ile aynı restrained, editorial yön; ayrı görsel onay istenmez, build + ekran görüntüsüyle kendin doğrula).

**Files:**
- Modify: `apps/web/src/report/ReportView.tsx` (dilim 1'de yaratılır), `apps/web/src/i18n.ts`
- Test: yok (Playwright acceptance kapsamı dilim 1'in `report.spec.ts`'sine dilim 1 kodlanınca eklenir; bu görev yalnız build/lint ve elle doğrulama ister)

**Interfaces:**
- Consumes: `useToast()`/`ToastAction` (`apps/web/src/Toast.tsx`, mevcut), `t()` (`i18n.ts`, mevcut).
- Produces: `ReportView.tsx`'e "Download LaTeX (.zip)" düğmesi.

- [ ] **Step 1: `npm run build`'in tip hatası verdiğini doğrula** (öncesinde düğme yok, bu adım yalnız mevcut dosyayı elle inceleyerek doğrulanır çünkü dilim 1 henüz kodda değil)

- [ ] **Step 2: Düğmeyi ve indirme akışını ekle**

```tsx
async function downloadLatex() {
  const resp = await fetch(`/api/researches/${researchId}/reports/${report.id}/export?format=latex`)
  if (!resp.ok) { toast('error', t('LaTeX export failed')); return }
  const warnings: string[] = JSON.parse(resp.headers.get('x-deixis-export-warnings') ?? '[]')
  const blob = await resp.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = resp.headers.get('content-disposition')?.match(/filename="(.+)"/)?.[1] ?? 'report.zip'
  a.click()
  URL.revokeObjectURL(url)
  if (warnings.length) {
    const shown = warnings.length > 3 ? `${warnings.slice(0, 3).join('; ')}; ${t('and {n} more', { n: warnings.length - 3 })}` : warnings.join('; ')
    toast('warning', t('LaTeX export has {n} warnings: {list}', { n: warnings.length, list: shown }))
  }
}
```

Markdown "Copy"/"Download Markdown" düğmelerinin yanına: `<Button variant="outline" onClick={downloadLatex}>{t('Download LaTeX (.zip)')}</Button>`.

`i18n.ts`'e: `'Download LaTeX (.zip)': 'LaTeX indir (.zip)'`, `'LaTeX export failed': 'LaTeX dışa aktarımı başarısız oldu'`, `'LaTeX export has {n} warnings: {list}': 'LaTeX dışa aktarımında {n} uyarı var: {list}'`, `'and {n} more': 've {n} tane daha'`.

- [ ] **Step 3: Build/lint çalıştır, ekran görüntüsüyle doğrula**

Run: `cd apps/web && npm run build && npm run lint`
Expected: PASS (dilim 1 kodda olduğunda; bu görev dilim 1'den önce çalıştırılırsa yalnız `i18n.ts` değişikliği bağımsız test edilir, düğme eklemesi dilim 1'e ertelenir).

- [ ] **Step 4: Commit**

```bash
git add apps/web/src/report/ReportView.tsx apps/web/src/i18n.ts
git commit -m "Add a LaTeX export download with a warnings toast next to the Markdown export" -- apps/web/src/report/ReportView.tsx apps/web/src/i18n.ts
git push origin main
```

### 5i — Karar kaydı ve tasarım notu durum güncellemesi

- [ ] **Step 1: `docs/decisions.md`'ye yeni girdi** (dosyanın başına, D1 kuralına uygun; en yüksek numara yürütme anında `grep -n '^## D' docs/decisions.md | head -3` ile teyit edilir, bu not yazılırken D60 boş):

```markdown
## D60 — Export the report as IEEEtran LaTeX and BibTeX, with a static KaTeX-vs-LaTeX check

**Status:** accepted (<execution date>). **Date:** <execution date>. **Context:** P6 slice 5
(`docs/product/p6-slice5-latex-export.md`), a second export format alongside slice 1's Markdown export
(`docs/product/p6-slice1-report-run.md`).
**Decision:** A `format=latex` branch of the report export route returns a zip of a single `.tex`
(IEEEtran, journal mode, XeLaTeX) and a `.bib` file; math is escaped and converted from KaTeX-accepted
constructs to plain LaTeX/amsmath by a static, non-compiling checker that records unsupported macros as
export warnings; citation keys reuse each work's D59 `source_key` with a local fallback; TABLE I splits
into page-sized `table*` parts instead of one unbreakable float; compilation is never required at
runtime and is only checked by an optional, skip-marked developer test.
**Evidence:** the golden-file test (`tests/test_report_latex_export.py`) and, when `latexmk` is present
on the developer's machine, the optional compile check.
**Limits:** the static macro check is a heuristic (can both miss and over-flag); the table split point is
a fixed row count, not measured page height, since nothing is compiled by default; reading depth is not
shown per cell in the LaTeX table, only in VIII's aggregate prose.
```

- [ ] **Step 2: `p6-report-design.md`'nin §12 madde 5'ine durum satırı ekle** (mevcut metni SİLMEDEN): "Dilim 5 uygulandı, bkz. D60 ve `p6-slice5-latex-export.md`."

- [ ] **Step 3: Commit**

```bash
git add docs/decisions.md docs/product/p6-report-design.md
git commit -m "Record the LaTeX export as a durable decision and update the design note's slice 5 status" -- docs/decisions.md docs/product/p6-report-design.md
git push origin main
```

## Self-review

- **Kaçış (hard part 1):** `latex_text.py::escape_prose`/`split_math_spans`/`escape_mixed` (5a Task 2), `contracts.math_spans` genel takma adı (5a Task 1) — `_math_spans` yeniden yazılmaz, yalnız genel adla çağrılır.
- **KaTeX/LaTeX farkı (hard part 2):** yukarıdaki tablo (5b), `check_unsupported_macros`/`convert_math_span` ve her satır için ayrı bir test (5b Task 1).
- **Derleme yok (hard part 3):** hiçbir görev TeX derlemesi çalıştırmaz (5a–5f, 5h); yalnız 5g isteğe bağlı, `skipif`'li, CI'da hiç çalışmayan bir geliştirici testidir; bu açıkça söylenir.
- **Kaynakça (hard part 4):** `bibliography.to_bibtex`'in geriye dönük uyumlu `keys` parametresi (5c Task 1), `latex_bib.py::resolve_cite_keys`/`to_bibtex_for_report` (5c Task 2), D59'un artık commit edilmiş olduğunun teyidi (5c Task 2 girişi ve "Dilim 1'den beklenenler").
- **Tablo hücresi (hard part 5):** `cell_text` (5d Task 1, her 7 durum + 4 değer biçimi), `render_table`'ın bölme stratejisi ve kaybedilenin açık yazımı (5d Task 2).
- **UI (madde 6):** `ReportView.tsx`'e düğme, `i18n.ts` dizeleri, uyarı bildirimi `useToast()` ile (5h); `.impeccable.md` referansı görev başlığında.
- **§2 karar 9 (insan okur biçimi, iç kimlik sızmaması):** golden-file testinin `test_no_internal_identifier_leaks_into_the_tex_or_bib`'i (5e Task 2).
- **§2 karar 11 (taslak banner, sürüm numarasız):** `render_latex`'in 3. adımı ve golden fixture'ın `status: "draft"` durumu (5e).
- **§9 "Dışa aktarma" (IEEEtran, `\cite` `source_key`'den, `table*`, denklemler değişmeden):** 5c, 5d, 5e birlikte.
- **§12 madde 5:** bu planın tamamı; kapanış görevi 5i.

## Dilim 1'den beklenenler

Dilim 1 bu not yazılırken kodda yoktur (yalnız plan); bu dilim aşağıdaki adları **tükettiği gibi** kullanır, hiçbirini yeniden tanımlamaz. Dilim 1 gerçekten kodlanınca bu adlardan biri değişirse (özellikle `ReportStore`'un tam metot imzaları, plan metninde yalnız prosa olarak verildi, literal kod olarak değil), yalnız 5e Task 1'in `to_latex()` sarmalayıcısı ve 5f'nin rota dalı güncellenir — 5a–5d ve 5e Task 2'nin golden-file testi bu adlara hiç dokunmaz, saf sözlüklerle çalışır.

- `backend/deixis/workflow/report/export.py::to_markdown(store, reports, report_id) -> str` — bu dilimin `to_latex`'i aynı imzayı taklit eder; `MEDIA_TYPES` sözlüğüne bu dilim `"latex": "application/zip"` ekler.
- `backend/deixis/workflow/report/numbering.py::number_citations(sections) -> dict`, `number_equations(sections) -> dict` — bu dilim `number_equations`'ı doğrudan çağırmaz (LaTeX kendi `equation` sayacını kullanır, bkz. 5e Task 1'in "Denklem numaralandırması" notu), ama iki numaralandırmanın aynı sırayı yürüdüğünü doğrulamak isteyen bir gelecek test bu fonksiyonu import edebilir.
- `ReportStore` ve tabloları: `reports`, `report_sections`, `report_claims`, `report_citation_links`, `report_gaps`, `report_snapshot` (migration 0034, henüz uygulanmadı).
- Route `GET /api/researches/{research_id}/reports/{report_id}/export?format=markdown` — bu dilim `format=latex` dalını aynı rotaya ekler; rotanın gerçek fonksiyon adı (`export_report` varsayıldı, `bibliography.py`'nin `export_bibliography` adlandırma deseninden) dilim 1 kodlanınca teyit edilmeli.
- Frontend `apps/web/src/report/ReportView.tsx` — Markdown "Copy"/"Download Markdown" düğmelerinin yanına bu dilim üçüncü bir düğme ekler.
- `ReportDetail`/`ReportSectionView` tipleri (`api.ts`) — bu dilim frontend tarafında bunlara dokunmaz, yalnız yeni bir `fetch()` çağrısı ekler.
- **Güncel bulgu (dilim 1'in kendi notunu düzeltir):** dilim 1'in Global Constraints'i "D59 iki kez talep edilmiş" ve dilim 2'nin notu "`source_keys.py` başka bir oturumun süren işi" der; bu ikisi artık **geçersizdir** — `git log --oneline -1 -- backend/deixis/workflow/source_keys.py` ve `backend/deixis/storage/migrations/0033_work_source_keys.sql` bunun commit edilmiş olduğunu gösteriyor (`Store.source_key`, `Store.assign_source_keys`, `tests/test_source_keys.py` hepsi kodda var). Bu dilim D59'u **hazır bir bağımlılık** olarak kullanır, dilim 1'in varsaydığı gibi "başka bir oturumun bitmemiş işi" olarak değil.
- Highest D number bu not yazılırken **D59**'dur (`docs/decisions.md`, tek bir D57 var, dilim 1'in bahsettiği çakışma da artık yok); bu dilimin kararı D60'ı dener, yürütmeden hemen önce yeniden teyit eder.

## Açık noktalar

- **`ReportStore`'un tam okuma metotları bilinmiyor.** 5e Task 1'in `to_latex()` sarmalayıcısı ve 5f'nin rota dalı, dilim 1'in `ReportStore.report(id)`/`.sections(id)` gibi adları taşıyacağını varsayar (dilim 1'in kendi plan metninden, `report/export.py`'nin `Consumes` satırı); gerçek imzalar dilim 1 kodlanınca netleşene kadar bu iki görev **yazılamaz**, yalnız tasarlanabilir. 5a–5d ve 5e Task 2 bundan bağımsızdır.
- **`export.py`/`latex_export.py` dosya sınırı.** Bu plan `MEDIA_TYPES`'ı `report/export.py`'de (dilim 1) değiştirmeyi önerir ama o dosya henüz yok; dilim 1 kodlanana kadar bu satır `latex_export.py`'nin kendi modül-seviyesi sabiti olarak durur (`LATEX_MEDIA_TYPE = "application/zip"`) ve dilim 1 birleşince `export.py::MEDIA_TYPES`'a taşınır — küçük bir birleştirme adımı, ayrı yazılmadı.
- **Okuma derinliğinin tabloda gösterilmemesi** (5d Task 1) bir kayıptır: renk yoktur, madalyon yoktur, yalnız VIII'in toplulaştırılmış cümlesi vardır. Sahip bunun yeterli olup olmadığına yürütmeden önce karar vermeli; yeterli değilse her hücreye küçük bir üstsimge (`\textsuperscript{FT}`/`\textsuperscript{Ö}`) eklemek küçük bir ek görevdir.
- **`table*` bölme eşiği (`MAX_ROWS_PER_PART = 20`) ölçülmedi.** Gerçek bir 50 satırlık, 13 sütunlu tablonun `\scriptsize`'da bir sayfaya sığıp sığmadığı yalnız görev 5g'nin isteğe bağlı derlemesiyle, gerçek bir raporla denenebilir; bu plan bir sabit önerir, doğrulamaz.
- **Bilinmeyen makro listesi (`_KNOWN_MACROS`) tüketici değildir.** Yaygın ama listede olmayan meşru bir amsmath makrosu yanlışlıkla "kontrol et" diye işaretlenebilir (yanlış pozitif); listede olmayan gerçekten kırık bir makro varsa ve tesadüfen tek harfli/bilinen bir örüntüye benziyorsa kaçabilir (yanlış negatif). Bu heuristiktir, garanti değildir (görev 5b'nin kendi metninde de yazılı).
- **XeLaTeX seçimi tersine çevrilemez değildir.** pdfLaTeX + `inputenc`/`babel`(turkish) alternatifi düşünüldü ve Türkçe noktasız-ı özel durumunun elle haritalanması gerektirdiği için reddedildi; XeLaTeX kurulu olmayan bir geliştirici makinesinde görev 5g atlanır ama bu üretim davranışını etkilemez (hiç derleme yapılmaz).
- **`bibliography.py`'nin test dosyasının gerçek adı teyit edilmedi** (5c Task 1, `tests/test_bibliography.py` varsayıldı); yürütmeden önce `grep -rl "to_bibtex" tests/` ile kesinleştirilmeli.
- **Ortak ara doküman modeli çıkarılmadı** (bkz. "Neden ayrı bir ara doküman modeli yok"); dilim 1 kodlandıktan sonra iki yürüyüşün (Markdown, LaTeX) gerçekten ayrışmadığı görülürse bu ayrı, küçük bir refactor görevidir, bu planın konusu değildir.
