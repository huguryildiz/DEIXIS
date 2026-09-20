# SW dilim 03 — Kayıt türü ve sürüm birleştirme: uygulama planı

**Tarih:** 20 Eylül 2026. **Durum:** yazıldı, uygulanmadı. **Ana dosya:** [sw-status.md](sw-status.md). **Ana plan:** [sw-implementation-plan.md](sw-implementation-plan.md) (§2 kuralları geçerlidir). **Spec:** [search-workflow-review-2026-09-18.md](search-workflow-review-2026-09-18.md): SW6 madde 1–3 ve 5–9 (madde 4, dış bağlantılar, dilim 05'tedir). **Önkoşul:** dilim 02 (D71) kapandı.

**Goal:** Bugün iki kayıt yalnızca DOI eşitse tek kayıt olur; ayrı DOI'li bir ön baskı ile yayımlanmış kaydı ancak başlıkları birebir aynıysa ve ilk yazar tutuyorsa aynı işe bağlanır (D48, `store._join_if_same_publication`), bağlanmanın hangi kuralla ve hangi puanla yapıldığı saklanmaz, geri alınamaz; geri kalan benzer kayıtlar yalnızca "aynı başlık" diye işaretlenir. SW6, DOI eşleşmesi yokken kararı başlık benzerliği, yazar soyadları ve özet benzerliğinin birlikte vermesini, yalnızca ön baskı–yayımlanmış ve ön baskı–ön baskı çiftlerinin birleşmesini, diğer çiftlerin adlı bir bağlantıyla ayrı kalmasını ve her birleştirmenin kuralı, puanları ve kaynağıyla saklanıp geri alınabilmesini ister. Bu dilim bunu `sw` araştırmaları için kurar. `legacy` araştırmalarında hiçbir şey değişmez.

**Architecture:** Karar saf bir işlevdir: `domain/record_identity.py::classify_pair` iki kaydın alanlarından bir hüküm (`Verdict`) üretir; veritabanına, modele ve gömmeye bakmaz (SW6.6). `workflow/links.py`, hükmü yeni `record_links` tablosuna yazar, gerekiyorsa iki işi birleştirir ve birleştirmeyi geri alır. `Store.record_search`, araştırmanın kapsamı `search_workflow = 'sw'` ise bugünkü `_flag_suspected_duplicates` yerine `links.link_records`'u çağırır; `legacy` ise bugünkü yol aynen koşar. İşler kütüphane geneli olduğu için (D46) bağlantılar da kütüphane genelidir: `record_links` araştırma kimliği taşımaz.

**Tech stack:** Python 3.12, SQLite. Yeni bağımlılık yok.

## Global constraints

- `apps/web/`, `contracts/research/`, `methods/deixis-research/`, `backend/deixis/workflow/flow.py`, `backend/deixis/workflow/views.py`, `backend/deixis/api/` ve mevcut migration dosyalarına dokunma. `skill_package_hash` değişmez.
- `legacy` araştırmanın hiçbir davranışı değişmez: `is_preprint`, `is_published`, `same_publication`, `_flag_suspected_duplicates`, `work_heads` ve `_settle_work_head`'in davranışı ve mevcut test beklentileri aynı kalır. Değişiyorsa dur ve sor.
- Model, gömme ve ağ çağrısı yok. Konuya özgü sözcük yok: tür listeleri depo ve bildirim adlarıdır, alan adı değil.
- İki yayımlanmış kayıt hiçbir yoldan aynı işe girmez; bu, dilimin en önemli değişmezidir.
- Migration numarası bu not yazılırken `0039`, karar numarası `D72`'dir; başlamadan önce ikisini de kontrol et.

## Dosya yapısı

Yeni: `backend/deixis/domain/record_identity.py`, `backend/deixis/workflow/links.py`, `backend/deixis/storage/migrations/0039_record_links.sql`, `tests/test_record_identity.py`, `tests/test_record_links.py`.

Değişecek: `backend/deixis/workflow/store.py` (`record_search`, `_join_if_same_publication`'dan ayrılan `_join_works`, iki kalıcı silme döngüsü), `backend/deixis/workflow/protocol.py` (yalnızca `sw` için eşikler), `tests/test_migrations.py`, `tests/determinism_stages.py`, `docs/decisions.md`, SW belgesi (SW6 durum satırı), `docs/product/sw-status.md`.

## Task 1: `domain/record_identity.py`

Kaynak: ölçümün kendi betikleri. Başlamadan önce oku: `.local/quantum-dedup-2026-09-18/title_pairs.py` (`norm`, `grams`, `jac`), `classify.py` (`sur`, yazar örtüşmesi), `signals.py` (`PRE`, `ART`, `kind`).

```python
TITLE_MERGE = 0.85          # SW6.3
ABSTRACT_MERGE = 0.8        # SW6.3, SW6.6
TITLE_RELATED = 0.6         # SW6.6: below this a pair is not examined
AUTHOR_OVERLAP = 0.5        # share of the shorter surname list (the measured rule)
MAX_YEAR_GAP = 5            # SW6.7
MIN_TITLE_CHARS = 12        # same value as store.MIN_TITLE_KEY_CHARS; not in SW6 (see Açık noktalar)
THRESHOLDS = {"title_merge": TITLE_MERGE, "abstract_merge": ABSTRACT_MERGE, "title_related": TITLE_RELATED,
              "author_overlap": AUTHOR_OVERLAP, "max_year_gap": MAX_YEAR_GAP}

PREPRINT_DOI_PREFIXES = ("10.48550/", "10.21203/", "10.36227/", "10.1101/", "10.20944/", "10.2139/")
ARTIFACT_DOI_PREFIXES = ("10.5281/", "10.6084/", "10.24433/", "10.4121/", "10.13140/", "10.17632/")
NOTICE_TITLE_PREFIXES: dict[str, str]   # normalised title prefix -> "correction" | "withdrawal" | "retraction"
ARTIFACT_TITLE_PREFIXES = ("data supporting",)
PLACEHOLDER_AUTHORS = ("anonymous", "unknown")

def normalize_text(text: str | None) -> str: ...
def trigrams(text: str) -> frozenset[str]: ...            # of an already normalised string
def similarity(a: str | None, b: str | None) -> float | None: ...   # None when either side normalises to nothing
def record_kind(record: dict) -> str: ...                 # preprint | published | artifact | notice | unknown
def notice_type(title: str | None) -> str | None: ...     # correction | withdrawal | retraction
def surnames(authors: list[str]) -> list[str]: ...
def author_agreement(a: list[str], b: list[str]) -> str: ...   # agree | differ | unknown

@dataclass(frozen=True)
class Verdict:
    link_kind: str            # same_work | extended_version | probable_version | related_suspected | artifact_of | notice_of
    rule: str
    merge: bool
    title_similarity: float | None
    abstract_similarity: float | None
    author_agreement: str
    year_gap: int | None
    parent: str | None        # "a" or "b": the paper an artifact or a notice belongs to

def classify_pair(a: dict, b: dict, *, names_published_doi: bool = False) -> Verdict | None: ...
```

Kayıt sözlüğü `doi`, `title`, `authors` (liste), `year`, `abstract`, `version_label`, `publication_type` alanlarını taşır; eksik alan `None` sayılır.

Kurallar:

- `normalize_text`: `unicodedata.normalize("NFKD")`, birleşen işaretler atılır (`unicodedata.combining`), `casefold`, HTML etiketleri ve `$...$` arası boşlukla değişir (`<[^>]+>|\$[^$]*\$`), harf ve rakam dizileri (`[^\W_]+`) tek boşlukla birleştirilir. ASCII başlıkta ölçümdeki `norm` ile aynı sonucu verir; farkı, Latin dışı harfleri atmamasıdır.
- `trigrams`: dolgu yok, `{s[i:i+3]}`; üç karakterden kısa metin boş küme verir. `similarity` Jaccard'dır; iki taraftan biri boşsa `None`.
- `record_kind`, sırayla: normalleştirilmiş başlık bir bildirim önekiyle başlıyorsa `notice`; DOI `ARTIFACT_DOI_PREFIXES`'ten biriyle ya da başlık `ARTIFACT_TITLE_PREFIXES`'ten biriyle başlıyorsa `artifact`; DOI `PREPRINT_DOI_PREFIXES`'ten biriyle başlıyorsa ya da `store.is_preprint` doğruysa (arXiv DOI'si, `submittedVersion`, `arXiv…` etiketi) `preprint`; DOI varsa `published`; yoksa `unknown`. `is_preprint`'i içe aktarma (döngü olur); aynı üç koşulu burada yaz ve ikisinin aynı kaldığını bir testle sabitle.
- Bildirim önekleri ölçümdeki düzenli ifadeden gelir (`publisher correction`, `author correction`, `correction`, `erratum`, `corrigendum` → `correction`; `withdrawn`, `withdrawal` → `withdrawal`; `retracted`, `retraction` → `retraction`). `corrigendum` ve `withdrawal` ölçümde yoktu; eklendiğini karar kaydına yaz. Önek, başlığın **başında** ve ardından sözcük sınırı gelirse sayılır ("Correction of errors in quantum memories" bildirim değildir: önekten sonra `to`, `:` ya da başlığın sonu beklenir; bu ayrımı testle göster ve tutmuyorsa raporla).
- `surnames`: ad virgül içeriyorsa virgülden öncesi, yoksa son sözcük; `normalize_text`'ten geçer, boşluklar atılır. `PLACEHOLDER_AUTHORS` içindeki adlar ve boş adlar listeye girmez.
- `author_agreement`: iki soyadı kümesinden biri boşsa `unknown`. Kesişim ÷ küçük küme ≥ `AUTHOR_OVERLAP` ise `agree`. Değilse bir tarafın adları **ters** okunur (virgülsüz adın ilk sözcüğü soyadı sayılır) ve aynı oran yeniden hesaplanır; tutarsa `agree`, tutmazsa `differ`. D48'in "ilk yazar aynı olmalı" koşulu burada yoktur; ölçülen kural budur.

`classify_pair` sırası (ilk tutan döner):

| # | Koşul | Hüküm | `rule` | `merge` |
|---|---|---|---|---|
| 1 | İki kayıt da `notice` ya da `artifact` | `None` | | |
| 2 | Biri `notice`: öneki atılmış başlığı ile diğerinin başlığı ≥ `TITLE_MERGE` ve yazarlar `differ` değil | `notice_of` | bildirim türü (`correction` / `withdrawal` / `retraction`) | hayır |
| 3 | Biri `artifact`: öneki atılmış başlıklar ≥ `TITLE_MERGE` ve yazarlar `agree` | `artifact_of` | `artifact_same_title` | hayır |
| 4 | 2 ya da 3'e giren ama koşulu tutmayan çift | `None` | | |
| 5 | `names_published_doi` ve türler `preprint` + `published` | `same_work` | `preprint_names_published_doi` | evet |
| 6 | Başlık benzerliği yok ya da < `TITLE_RELATED`, ya da normalleştirilmiş başlıklardan biri `MIN_TITLE_CHARS = 12`'den kısa | `None` | | |
| 7 | Yazarlar `differ` | `None` | | |
| 8 | Yazarlar `unknown` | `related_suspected` | `authors_unknown` | hayır |
| 9 | İkisi de `published`, başlık ≥ `TITLE_MERGE` | `extended_version` | `two_published_similar_title` | hayır |
| 10 | İkisi de `published` (başlık 0,6–0,85) | `related_suspected` | `two_published` | hayır |
| 11 | Türlerden biri `unknown` | `related_suspected` | `kind_unknown` | hayır |
| 12 | Yıl farkı > `MAX_YEAR_GAP` (iki yıl da biliniyorsa) ve 13 ya da 14 tutacaktı | `related_suspected` | `year_gap_blocks_merge` | hayır |
| 13 | Başlık ≥ `TITLE_MERGE`, iki özet de var, özet benzerliği ≥ `ABSTRACT_MERGE` | `same_work` | `title_authors_abstract` | evet |
| 14 | Özetlerden en az biri yok ve normalleştirilmiş başlıklar birebir aynı | `same_work` | `identical_title_authors` | evet |
| 15 | İki özet de var, özet ≥ `ABSTRACT_MERGE`, başlık < `TITLE_MERGE` | `probable_version` | `abstract_agrees_title_differs` | hayır |
| 16 | Geri kalan | `related_suspected` | `similar_title_same_authors` | hayır |

13–16'ya yalnızca `preprint` + `published` ve `preprint` + `preprint` çiftleri ulaşır. Satır 5'te yıl farkı engel değildir: bağlantıyı yazar kendisi vermiştir ve D48 bugün de böyle davranır. Hüküm simetriktir: `classify_pair(a, b)` ile `classify_pair(b, a)` yalnızca `parent` alanında (`"a"` ↔ `"b"`) ayrılır.

- [ ] **Tests first**, satır başına en az bir test ve şunlar: "Last, First" ile "First Last" aynı yazar; aksanlı ve aksansız soyadı aynı; ters yazılmış adlar `agree`; `["Anonymous"]` `unknown`; HTML ve `$...$` kalıntılı başlık temiz başlıkla benzerlik 1,0; Latin dışı başlık boş normalleşmez; iki yayımlanmış kayıt hiçbir girdiyle `merge = True` vermez (başlık 1,0, özet 1,0, yazarlar aynı olsa bile); yıl farkı 6 birleştirmez, 4 birleştirir; bir özet yokken başlık 0,9 birleştirmez, birebir aynı başlık birleştirir; simetri; `record_kind`'ın ön baskı koşulu `store.is_preprint` ile aynı kayıtlarda aynı cevabı verir. Bütün girdiler SYNTHETIC.

## Task 2: migration

**Files:** Create `0039_record_links.sql`. Modify `tests/test_migrations.py`.

```sql
CREATE TABLE record_links (
  id TEXT PRIMARY KEY,
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  other_source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  link_kind TEXT NOT NULL CHECK (link_kind IN ('same_work', 'extended_version', 'probable_version', 'related_suspected',
                                               'artifact_of', 'notice_of')),
  rule TEXT NOT NULL,
  source TEXT NOT NULL CHECK (source IN ('text', 'arxiv_doi')),
  parent_source_version_id TEXT REFERENCES source_versions(id),
  title_similarity REAL,
  abstract_similarity REAL,
  author_agreement TEXT NOT NULL CHECK (author_agreement IN ('agree', 'differ', 'unknown')),
  year_gap INTEGER,
  merged INTEGER NOT NULL CHECK (merged IN (0, 1)),
  undo_json TEXT,
  closed_at TEXT,
  closed_reason TEXT CHECK (closed_reason IS NULL OR closed_reason IN ('undone', 'superseded')),
  closed_note TEXT,
  created_at TEXT NOT NULL,
  CHECK (source_version_id < other_source_version_id),
  CHECK ((closed_at IS NULL) = (closed_reason IS NULL))
);
CREATE UNIQUE INDEX record_links_open ON record_links(source_version_id, other_source_version_id) WHERE closed_at IS NULL;
CREATE INDEX record_links_other ON record_links(other_source_version_id);
```

Çift her zaman sıralı saklanır (küçük kimlik solda); ek ürün ve bildirimde yön `parent_source_version_id`'dedir. `source`, dilim 05'te `semantic_scholar` ve `crossref_relation` ile genişler (o dilim tabloyu yeniden kurar). Silme tetikleyicisi yoktur: tablo araştırma kimliği taşımaz, satır yalnızca kaynağın kendisi kalıcı silinirken gider (Task 5).

- [ ] **Tests first:** tablo ve sütunlar vardır; ters sıralı çift eklenemez; aynı çift için ikinci açık satır eklenemez ama kapalı satırın yanına açık satır eklenebilir; `closed_at` olup `closed_reason` olmayan satır eklenemez.

## Task 3: `workflow/links.py` — yazma, okuma, geri alma

`store.py` bu modülü içe aktaracağı için `links.py`, `Store`'u yalnızca `TYPE_CHECKING` altında içe aktarır. İşlevler `store`'u ilk argüman alır; sınıf yok.

```python
def save_link(store, a: str, b: str, verdict: Verdict, source: str) -> dict | None: ...
def links_for(store, source_version_id: str, include_closed: bool = False) -> list[dict]: ...
def research_links(store, research_id: str) -> list[dict]: ...
def undo_link(store, link_id: str, note: str | None = None) -> dict: ...
```

Önce `store.py`'de küçük bir ayırma: `_join_if_same_publication`'ın (~1332) işleri taşıyan yarısı `_join_works(self, keep_work_id: str, drop_work_id: str) -> dict` olur ve geri almanın ihtiyacını döndürür: `{"dropped_work": {"id", "created_at", "source_key", "source_key_basis"}, "moved": [taşınan source_version kimlikleri, sıralı]}`. `_join_if_same_publication` onu çağırır; `legacy` davranışı ve testleri aynı kalır.

`save_link` kuralları (çağıran işlemi tutar; kendi işlemini açmaz):

- Çift için `closed_reason = 'undone'` olan bir satır varsa hiçbir şey yazılmaz, `None` döner: geri alınan bağlantı bir daha kendiliğinden kurulmaz (User Authority).
- Açık satır aynı `link_kind` ve aynı `rule` ile varsa o döner, yeni satır yok (sürdürülen koşu, tekrar bulunan kayıt).
- Açık satır başka bir hükümle varsa: açık satır `merged = 1` ise dokunulmaz ve o döner (birleşmiş iş, sonradan gelen daha zayıf bir hükümle ayrılmaz); değilse `closed_reason = 'superseded'` ile kapanır ve yenisi yazılır (örneğin özet sonradan gelince `related_suspected` → `same_work`).
- `verdict.merge` ise ve iki kayıt ayrı işlerdeyse birleştirmeden önce **koruma**: birleşecek iki işin bütün kayıtları içinde `record_kind == 'published'` olan ve DOI'leri farklı iki kayıt olacaksa birleştirme yapılmaz; satır `related_suspected` / `work_already_has_published` / `merged = 0` olarak yazılır. Bu koruma satır 5 (`preprint_names_published_doi`) için de geçerlidir.
- Birleştirmede kalan iş: `published` kaydın işi; iki ön baskıda `works.created_at`'i eski olan, eşitse küçük kimlik. `_join_works`'ün döndürdüğü `undo_json`'a yazılır, `merged = 1`. İki kayıt zaten aynı işteyse satır `merged = 0` ile yazılır.

`undo_link`:

- Açık olmayan satır için `ValueError`. Satır `closed_reason = 'undone'` ile kapanır, `closed_note` yazılır.
- `merged = 1` ise: `undo_json`'daki iş aynı kimlik ve `created_at` ile yeniden açılır; `moved` listesindeki kayıtlardan **hâlâ o işte duranlar** geri taşınır; `source_key` boşsa geri verilir, başka bir iş almışsa `store._assign_source_key(work_id)` yenisini verir (D59: verilmiş anahtar değişmez, alınmış anahtar geri istenmez). İki işin üyesi olduğu her araştırma için `store._settle_work_head` çağrılır.
- Geri alma yalnızca o bağlantının taşıdığını ayırır; aynı işe sonradan başka bir bağlantıyla giren kayıtlar yerinde kalır. Birleşme sırasında yeni işin başına kopyalanan seçim (`_settle_work_head`) geri alınmaz; her kaydın kendi `selections` satırı zaten durur.
- Geri alma hiçbir alıntıyı bozmaz: yanıtlar iş kimliğine değil kayda bağlıdır. Bunu bir testle göster (alıntılanan bir kaydın işi ayrıldıktan sonra `store.source(svid)` ve pasajları yerinde).

- [ ] **Tests first**, her kural için bir test; ayrıca: geri alınan birleşme aynı aramayla yeniden kurulmaz; anahtarı başkası almış işe yeni anahtar verilir; A+B birleşip sonra C aynı işe girdikten sonra A–B geri alınınca C, A ile kalır.

## Task 4: `record_search`'e bağlama

```python
def link_records(store, research_id: str, source_version_ids: list[str]) -> None: ...
```

`Store.record_search` (~1259) içinde `_flag_suspected_duplicates` çağrısı, araştırmanın güncel kapsamı `search_workflow == 'sw'` ise `links.link_records(self, research_id, found)` ile yer değiştirir; aynı işlemin içinde kalır. `legacy` için satır aynen durur. `sw` araştırmasında `suspected_duplicates` tablosuna yazılmaz.

`link_records`:

- Evren, bugünkü işlevdeki gibi araştırmanın adaylarıdır (`candidates`). Karşılaştırma **yeni gelen kayıtlar × bütün adaylar**dır, bütün çiftler değil; normalleştirme ve trigram kümeleri çağrı başına bir kez hesaplanır.
- `names_published_doi` çiftleri bugünkü iki sorguyla bulunur (`identifier_mappings`, `scheme = 'published_doi'`, ~1315–1321) ve başlık eşiğinden bağımsız sınanır; `source = 'arxiv_doi'`. Diğer bütün hükümler `source = 'text'`.
- Özetler (`passages.kind = 'abstract'`) yalnızca başlık eşiğini geçen ya da bildirim / ek ürün olan kayıtlar için okunur.
- Aynı işteki iki kayıt için de hüküm üretilir ve saklanır (`merged = 0`); DOI ile tek kayıt olmuş kayıtlar zaten tek `source_version`'dır ve çift oluşturmaz (SW6.1).
- Çiftler sabit bir sırayla işlenir: önce `arxiv_doi`, sonra başlık benzerliği azalan, sonra sıralı kimlik çifti. Aynı saklı girdi aynı bağlantıları verir.
- Ek ürün ve bildirim kayıtları bu dilimde aday listesinde **kalır**; yalnızca ana makaleye bağlanır. Adaylıktan çıkmaları bir neden koduyla olur ve o kodu özet taramasının kod aşaması yazar (dilim 09).

`protocol.py`: `build_protocol`, `scope["search_workflow"] == "sw"` iken `thresholds`'a `record_identity` anahtarı altında `THRESHOLDS`'u ekler. `legacy` gövdesi ve özeti değişmez; bunu testle sabitle.

- [ ] **Tests first** (`tests/test_record_links.py`, kurulum kalıbı `tests/test_stage_decisions.py`'deki `research`, `search`, `record` yardımcılarıdır; özet ve yazar alabilen bir `record` yaz): `legacy` araştırmada `record_links` boş kalır ve `suspected_duplicates` bugünkü gibi dolar; `sw` araştırmada başlığı 0,9 benzer, yazarları "Last, First" / "First Last" yazılmış, özetleri aynı ön baskı + yayımlanmış kayıt tek iş olur, başı yayımlanmış kayıttır (D48) ve bağlantı satırı kuralı, üç puanı ve `merged = 1` taşır; aynı başlıklı iki yayımlanmış kayıt ayrı işlerde kalır ve `extended_version` ile bağlanır; ön baskısı zaten bir yayımlanmış kayda bağlı işe ikinci bir yayımlanmış kayıt girmez (`work_already_has_published`); aynı yazarların kardeş makalesi (başlık ~0,7, özet farklı) `related_suspected` kalır; başlığı değişmiş sürüm (başlık ~0,7, özet aynı) `probable_version` olur ve birleşmez; "Publisher Correction: …" kaydı ana makaleye `notice_of` / `correction` ile bağlanır ve `parent_source_version_id` makaledir; aynı arama ikinci kez kaydedilince satır sayısı değişmez; ön baskının seçimi birleşmede başa geçer (mevcut D48 testindeki beklenti `sw` için de tutar).

## Task 5: kalıcı silme

`store.py`'de `source_versions` satırının silindiği iki döngü (`purge_research` ~296–302, `purge_sources` ~1635–1641): kayıt silinmeden önce `DELETE FROM record_links WHERE source_version_id = ? OR other_source_version_id = ? OR parent_source_version_id = ?`. Başka bir araştırmada yaşayan kaydın bağlantıları durur.

- [ ] **Tests first:** bağlantısı olan kayıtlarıyla bir araştırma kalıcı silinebilir; iki araştırmanın paylaştığı kaydın bağlantısı, biri silinince durur; kaldırılmış ve bağlantılı bir kaynak `purge_sources` ile silinebilir.

## Task 6: tekrar aşaması

`tests/determinism_stages.py`'ye `link_records`: sabit bir SYNTHETIC kayıt kümesi (bir birleşen çift, bir `extended_version`, bir `related_suspected`, bir bildirim, ilgisiz iki kayıt) karıştırılmış sırayla geçici bir veritabanındaki `sw` araştırmasına tek aramayla kaydedilir. Çıktı, sağlayıcı kayıt kimlikleriyle yazılmış iş grupları ve bağlantılardır (`çift`, `link_kind`, `rule`, `merged`); rastgele üretilen `srv_` / `wrk_` kimlikleri ve işin başı çıktıya girmez. Kümede, sonucu geliş sırasına bağlı tek durum olan "iki yayımlanmış kayıt aynı ön baskıyı istiyor" **bulunmaz**; o durum Limits'e yazılır. Test dosyasındaki karışım tohumları (1 ve 2) birleşen çiftin sırasını gerçekten ters çevirmeli; çevirmiyorsa satırların yerini değiştir.

## Task 7: ikinci konunun 127 çifti (ürün kodu değil)

`.local/sw-slice03-pairs-2026-09-20/check_pairs.py` (izlenmeyen dizin): `.local/second-topic-packet-size-2026-09-20/staged.json`'daki `trigram_pairs` (127 çift) ve `records` okunur; yazarlar ve yıl OpenAlex'ten toplu alınır (`filter=openalex:W1|W2…`, 50'lik partiler, `select=id,authorships,publication_year`; anahtar `.env`'de varsa kullanılır; istek başarısız olursa yazarlar `unknown` kalır ve bu söylenir). Her çift `classify_pair`'den geçer; `pairs.csv` yazılır: iki başlık, iki DOI, iki tür, üç puan, yıl farkı, hüküm, kural. Son iletide hüküm ve kural başına sayılar verilir. **Gözle denetimi inceleme sohbeti yapar**; uygulayan sohbet yalnızca dosyayı üretir ve `merge = True` çıkan çiftlerin başlıklarını son iletiye yazar. Canlı kütüphaneye ve 8765 portuna dokunulmaz.

## Task 8: dilimi kapat

- [ ] `PYTHONPATH=backend:. uv run pytest` tamamı; temel ve son sayılar. Beklenen temel: `1 failed, 766 passed`; bilinen tek başarısızlık `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`.
- [ ] `link_records`'un bir çağrısının süresi: 1.500 SYNTHETIC adayı olan bir araştırmaya 50 yeni kayıt; ölç, son iletiye yaz. 1 saniyeyi aşıyorsa kod değiştirmeden raporla (çağrı olay döngüsü iş parçacığında, işlem içinde koşar).
- [ ] `git diff --check`
- [ ] `docs/decisions.md` en üste `## D<NN> — Link records of one work by title, authors and abstract together, merge only a preprint with its published record, and keep every link undoable`. Limits şunları adıyla söylemeli: yalnızca `sw` araştırmaları; işler kütüphane geneli olduğundan bir `sw` araştırmasının birleştirmesi aynı kayıtları taşıyan `legacy` araştırmada da görünür (D48 birleştirmeleri bugün de böyledir); eşikler tek konuda elle seçildi, DOI'siz kayıtlar ölçülmedi, ürün içinde ölçülmedi (dilim 24); başlık benzerliği 0,6'nın altındaki çiftlere bakılmaz, başlığı tümüyle değişmiş sürüm ancak dilim 05'in dış bağlantısıyla bulunur; tür kuralı kısa bir önek listesidir; iki yayımlanmış kaydın hangisinin bildiri, hangisinin dergi makalesi olduğu saklanmıyor, tam metin kararının dergi makalesini yeğlemesi (SW6.5) dilim 12'ye kalır; `extended_version` çiftlerinin iş düzeyi sayılarda bir kez sayılması hiçbir yerde uygulanmadı (dilim 20); ek ürün ve bildirimler aday listesinde duruyor (dilim 09); bir işin başı hâlâ D48'in dar ön baskı testiyle seçiliyor, arXiv dışı bir ön baskı DOI'si yayımlanmış sayılıp işin başı olabilir; iki yayımlanmış kayıt aynı ön baskıyı isterse ilk gelen alır; bağlantılar ve geri alma arayüzde görünmüyor, `sw` araştırmasında "may duplicate" işareti de yok; geri alma, birleşmede başa kopyalanan seçimi geri almaz; testler SYNTHETIC girdiyle koşar.
- [ ] SW belgesinde SW6 **Status** satırına bir cümle: 1–3 ve 5–9'un `D<NN>` ile `sw` araştırmaları için uygulandığı, madde 4'ün dilim 05'te olduğu, ürün içinde ölçülmediği.
- [ ] `sw-status.md` satır 03: `uygulandı, inceleme bekliyor`, commit özeti, `D<NN>`, açık kalanlar.
- [ ] Tek commit, `git push origin main` (ana plan §2.11). `.local/` izlenmez; commit'e girmez.

## Son ileti

Değişen ve eklenen dosyalar; temel ve son test sayıları ve komut; `link_records` süresi; 127 çiftin hüküm sayıları ve birleşen çiftlerin başlıkları; `_join_works` ayırmasının `legacy` davranışını değiştirmediğini nasıl doğruladığın; bu dosyada yazıldığı gibi yapılamayan her şey ve seçtiğin her sapma; yapmadıkların; dokunulan kanıt sınırları (beklenen: kaynak kimliği ve iş gruplaması, yalnızca `sw` araştırmalarının aramasında); canlı servise dokunulmadığı; commit özeti.

## Açık noktalar

- **Yorum:** SW6.6 "yazarlar tutuyor, özet ≥ 0,8, başlık daha düşük → `probable_version`" der ve tür saymaz. İki yayımlanmış kayıt hiç birleşmeyeceği için (SW6.5) bu dilim o çifti `related_suspected` / `two_published` yapar; `probable_version` yalnızca birleşebilecek türlere verilir.
- **Yorum:** SW6.5 "bildiri ve dergi makalesi" der; sağlayıcıların çoğu ikisini de `article` diye verir (OpenAlex), bu yüzden kural tür ayırmaz: yazarları tutan, başlığı ≥ 0,85 iki yayımlanmış kayıt `extended_version`'dır.
- **Yorum:** SW6.2'nin "aday listesinden çıkar" yarısı bu dilimde yok. Kayıt gizlenmez; dilim 09'un kod aşaması ona bir neden koduyla `out_of_scope` verir, böylece kullanıcı görür ve ezebilir. Ana planın dilim 09 satırına not düşüldü.
- Birleştirmeyi ve geri almayı kullanıcıya açan uç nokta ve ekran yok; `probable_version` insan kuyruğuna dilim 16'da girer.
- `MIN_TITLE_CHARS = 12`, `store.MIN_TITLE_KEY_CHARS` ile aynı değerdir ve SW6'da yoktur; "Editorial" gibi başlıkların yazarı bilinmeyen kayıtlarla `related_suspected` yığını üretmesini önlemek için konmuştur.
