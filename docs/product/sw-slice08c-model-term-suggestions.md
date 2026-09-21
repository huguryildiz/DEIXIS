# SW dilim 08c — Kullanıcı isteyince model terim önerir: uygulama planı

**Tarih:** 21 Eylül 2026. **Durum:** yazıldı, uygulanmadı; **dilim 09 commit'lenmeden başlamaz** (aşağıda "Sıra"). **Ana dosya:** [sw-status.md](sw-status.md). **Ana plan:** [sw-implementation-plan.md](sw-implementation-plan.md) (§2 kuralları geçerlidir). **Spec:** [search-workflow-review-2026-09-18.md](search-workflow-review-2026-09-18.md): **SW2** madde 5 ve 6, SW1 madde 3 (iddia sözcüğü sorguya girmez), SW14 madde 2 ve 6, SW17 madde 2. **Önkoşul:** 08a, 08b (kapandı), 09 (commit'lenmiş). **Tür:** Kur (ölçülmedi). **İnceleme:** toplu. Arayüz görevlerinden önce [.impeccable.md](../../.impeccable.md) ve [AGENTS.md](../../AGENTS.md) "Frontend/UX".

**Sahibin kararı (21 Eylül 2026):** otomatik tetik **yok**. SW2.5 "ilk tur zayıfsa ya da kullanıcı isterse" der; bu dilim yalnızca ikinci yarıyı kurar: onay kartında bir **Modelden terim öner** düğmesi. "İlk tur zayıf" eşiği tanımlanmaz, dilim 24'ün ölçümüne bırakılır. Model sorgu değil terim listesi önerir; her terim soru terimleriyle aynı sayım sınamasından geçer, kökeni `model` olarak görünür ve **kullanıcı eklemeden hiçbir terim sorguya girmez**.

**Sıra:** bu dilim yeni bir sözleşme ve yöntem dosyası getirir, `skill_package_hash` değişir. Dilim 09 da aynı dosyalara dokunur (`step-input.schema.json`, `domain/contracts.py`, `domain/skill.py`, `domain/rules.py`, `api/app.py` bütçesi, `SKILL.md`, `provenance.json`, `tests/fixtures/research/*`, `tests/fakes.py`, `fixture_server.py`, `determinism_stages.py`, `Transcript.tsx`, `labels.ts`, `i18n.ts`). İki uygulama sohbeti aynı anda koşarsa özetler ve fikstürler çakışır. Bu yüzden 08c'nin uygulaması, satır 09 en az `uygulandı, inceleme bekliyor` olduktan (commit'i `main`'de olduktan) sonra başlar. 08c, 09'un önkoşulu değildir ve 09'un davranışına dokunmaz.

**Goal:** Bugün onay kartındaki kullanıcı, sorusunda geçmeyen ama alanın kullandığı bir adı ancak kendisi biliyorsa ekleyebilir. Bu dilimden sonra karttaki düğmeye basınca koşu kısa bir süre çalışır: model, kartta duran arama terimlerinin **başka adlarını** önerir; kod önerileri süzer (zaten var olan, iddia ya da dışlama sözcüğü taşıyan), kalan her ifadeyi sayar (sıfır kayıt: düşer) ve koşu yeniden onay için durur. Kart önerileri ayrı bir grupta gösterir; kullanıcı istediğini **Ekle** ile taslağına alır. Onayda bu terimler 08a'nın `add` işlemi olarak gider, tek kod yolundan (`build_vocabulary`) geçer ve protokolde kökenleri `model` olur.

**Architecture:** Yeni model görevi `term_suggestions` (tek çağrı, onarımsız), yeni saf modül `workflow/suggestions.py`, `flow._approval` içinde yeni bir dal ve `_term_suggestions`. Adımlar: `code:term_suggestions` (anahtar `term_suggestions:{n}`, n = istek sırası) ve onun içindeki `model:term_suggestions` (anahtar `term_suggestion:{n}`). Yeni rota `POST /api/runs/{run_id}/term-suggestions` yalnızca isteği kaydeder ve koşuyu kuyruğa alır; **model çağrısı ve sayım istekleri işçide** yapılır (08a'nın kuralı). `views.approval_view` `suggestions` alanını kazanır; kart onu okur. Migration yok.

**Tech stack:** Python 3.12, React 19. `skill_package_hash` **değişir**. Yeni bağımlılık yok.

## Global constraints

- **Otomatik tetik yok.** Model yalnızca rota çağrılınca sorulur. `as_proposed` modunda ve önceki onayla kapanan koşuda (`earlier_approval`) adım hiç açılmaz. İlk turun zayıflığını ölçen hiçbir kod yazılmaz.
- **Kullanıcı eklemeden hiçbir öneri sorguya girmez.** Öneriler adım çıktısında ve görünümde durur; dağarcığa, sorgulara ve protokole yalnızca kullanıcının `add` işlemiyle girer. Düğmeye basıp hiçbirini eklemeden onaylayan kullanıcının sorguları önerinin sorgularıyla **bayt bayt aynıdır** (testi zorunlu).
- **Köken sunucuda türetilir, istemciden alınmaz.** `add` işleminin biçimi değişmez (`canonical_edits` yalnızca `op`, `phrase`, `block` taşır). Eklenen ifade, `norm` sonrası bu onayın kayıtlı önerilerinden biriyle aynıysa terim kökeni `model`, değilse `user` olur. Blok kökeni her iki durumda da `user`'dır: ifadeyi o bloğa koyan kullanıcının eklemesidir.
- **Tek kod yolu dağarcık kurar** (08a): eklenen öneri `edited_extraction` → `build_vocabulary` yolundan geçer; kök / öbek kararı, `and_only` ve geçit daraltması orada verilir. Önerinin okunmuş sayımı `known`'a katılır ve yeniden sorulmaz.
- **İddia sözcüğü sorguya girmez** (SW1.3): bir iddia ya da dışlama ifadesini bitişik sözcük dizisi olarak taşıyan öneri kodla düşer ve nedeniyle kayıtta kalır; karttan eklenemez.
- **Aynı araştırmada model yeniden sorulmaz** (SW2.6): bir onay adımında `ready` dönen öneri ikinci kez istenmez; aynı soru + yönlendirme + `key_terms` için yeniden sorulan kart (08a incelemesinin "kimsenin görmediği ölçüt" durumu) önceki onayın önerilerini taşır, modeli çağırmaz. Yalnızca `failed` biten istek yinelenebilir.
- **Hiçbir şey yerinde düzenlenmez** (SW14.2): öneri listesi olduğu gibi kalır; eklenen, eklenmeyen ve düşen ayrı ayrı okunabilir.
- `legacy` araştırmada hiçbir adım açılmaz, rota 409 döner, protokol gövdesi ve özeti aynı kalır. Öneri istenmeyen bir `sw` koşusunun protokol gövdesi ve özeti de bu dilimden önceki değerle **aynıdır** (yeni gövde alanı yalnızca istek yapıldıysa yazılır).
- Mevcut hiçbir testin beklentisi değişmez. Mevcut Playwright A–G ve H senaryoları değişmeden geçer.
- Elle seçilen her sayı adlı sabittir ve ölçülmemiştir: `MAX_SUGGESTED_TERMS = 12`, `SUGGESTION_CALLS = 1` (`domain/rules.py`). İfade sınırları 08a'nınkidir (`MAX_TERM_CHARS = 80`, `MAX_TERM_WORDS = 6`).
- **İstem ölçülmeden kurulur.** Aşağıdaki yöntem dosyası hiçbir modelle denenmedi; bu dilimde de denenmez. Canlı model çağrısı, sağlayıcı isteği ve kuru çalıştırma **yok**. D kaydı ve satır 08c bunu "ölçülmedi" diye yazar.
- Testlerde ağ yok. Fikstürler SYNTHETIC ve en az iki alandan. Ürün koduna ve yöntem dosyasına konuya özgü sözcük girmez.
- Başlamadan kontrol et: satır 09 commit'li; son karar `D81` (09'un); son migration `0044`. Bu dilim sıradaki boş numarayı alır (beklenen `D82`), migration almaz. `skill_package_hash`'in başlangıç değeri 09'un bıraktığıdır; önce ve sonra kaydedilir.

## Dosya yapısı

Yeni: `contracts/research/term-suggestions.schema.json`, `methods/deixis-research/references/term-suggestions.md`, `backend/deixis/workflow/suggestions.py`, `tests/test_term_suggestions.py` (saf + sözleşme), `tests/test_suggestion_flow.py` (`create_app` ile).

Değişecek: `contracts/research/step-input.schema.json` (`task_type` enum, isteğe bağlı `suggestion_target`), `domain/contracts.py`, `domain/skill.py`, `domain/rules.py`, `workflow/approval.py` (`edited_extraction`'a model kökeni), `workflow/flow.py`, `workflow/protocol.py`, `workflow/store.py`, `workflow/views.py`, `api/app.py` (rota, bütçe), `methods/deixis-research/SKILL.md` ve `provenance.json`, `tests/fixtures/research/{step-inputs,fake-outputs}.json`, `tests/fakes.py::valid_response`, `tests/acceptance/fixture_server.py`, `tests/determinism_stages.py`, `apps/web/src/api.ts`, `ProtocolApproval.tsx`, `Transcript.tsx` (faz eşlemesi), `labels.ts`, `i18n.ts`, `workspace.css` (yalnızca gerekirse), `apps/web/e2e/protocol-approval.spec.ts`, `docs/decisions.md`, SW belgesi (SW2 durum satırı), `sw-status.md`.

## Task 1: sözleşme, StepInput hedefi ve yöntem dosyası

**`suggestion_target`** (StepInput'ta, yalnızca `term_suggestions` görevinde; `vocabulary_target` ile aynı "var / yok" denetimi):

```json
{"question_text": "…",
 "phrases": [{"phrase": "…", "block": "setting", "records": 1234}],
 "avoid": ["…"],
 "max_terms": 12}
```

- `phrases`: onay **önerisinin** aranan iki bloğundaki (`vocabulary.GATE_BLOCKS`) bütün terimler, dağarcığın kurulduğu sırayla, **düşmüş olanlar dâhil** (sıfır kayıtlı bir ifade, "alan buna başka ne diyor" sorusunun en iyi çapasıdır). `records` terimin `phrase_count`'udur, okunamadıysa `null`. Bunlar modelin `synonym_of` ile adlandırabileceği **çapalardır** ve StepInput izin listesine `phrases` olarak girer (`flow._step_input`'taki `vocabulary_target` dalının aynısı).
- `avoid`: önerinin öbür bütün ifadeleri (`claim_words`, `exclusion_words`, `outcome_terms`), aynı sırayla.
- Model kullanıcının karttaki **taslak** düzeltmelerini görmez (taslak yalnızca tarayıcıdadır); öneriyi görür. Açık noktalarda adıyla yazılı.

**`contracts/research/term-suggestions.schema.json`** (`TermSuggestions`, `schema_version` = `deixis.term_suggestions.v1`): zarf alanları (`step_input_id`, `scope_revision`, `skill_package_hash`) + `terms`: en çok 12 öğe, her biri `{"phrase": string 1–80, "synonym_of": string 1–200}`, `additionalProperties: false`. Gerekçe alanı ve blok alanı **yok**: blok çapanın bloğudur ve kod türetir; serbest metin denetlenemez. Boş `terms` geçerlidir.

**Anlamsal denetim** (`domain/contracts.py::_check_term_suggestions`): `synonym_of` izin listesindeki bir ifade değilse hata (`phrase_not_in_allowlist`) — yeri olmayan terim kabul edilmez. Başka hiçbir şey hata değildir: yinelenen, zaten var olan, fazla uzun ya da iddia sözcüğü taşıyan öneri çıktıyı geçersiz kılmaz, Task 2'de kodla düşer ve kaydedilir. Görev `NO_REPAIR_TASKS`'a girer (tek deneme): kullanıcı kartın başında bekliyor ve yineleme zaten onun düğmesidir. Görev `LITERATURE_TASKS`'a da girer (öbür plan görevleriyle aynı model rolü).

**`methods/deixis-research/references/term-suggestions.md`** — metin aşağıdaki gibidir, ölçülmemiştir, uygulayan değiştirmez:

```markdown
# Term suggestions

Goal: for the search phrases the application already holds, give the other
names the literature uses for the same thing. The application built its search
from the words of the question; you add only names an author of a relevant
paper would write instead. You propose a term list. You never write a query.

1. Read `suggestion_target.question_text` and `suggestion_target.phrases`. Each
   phrase carries the `block` it is searched in and `records`, the number of
   indexed papers that hold the phrase (`null` when it was not counted). A
   phrase with few or no records is one the field probably calls something
   else; those phrases need other names most.
2. Return `terms`: at most `suggestion_target.max_terms` entries. Each entry
   has `phrase`, the name you propose, and `synonym_of`, copied exactly from
   the given phrase it is another name for. Every proposed name must stand for
   the same thing as its `synonym_of` phrase in the sense the question uses it.
3. A proposed `phrase` is 1 to 6 words, lower case, written as it appears in
   the running text of a paper: a synonym, a standard abbreviation or its
   spelled-out form, a spelling variant, or the established name of the same
   thing in a neighbouring community.
4. Do not propose a phrase that is already given, in `phrases` or in
   `suggestion_target.avoid`, and none that contains a phrase from `avoid`.
   The application keeps the `avoid` phrases out of its query deliberately.
5. Echo `step_input_id`, `scope_revision` and `skill_package_hash` exactly as
   they were given, and set `schema_version` to `deixis.term_suggestions.v1`.

Hard cases:

- A broader term, a narrower term and a related topic are not other names.
  Leave them out even when they are common in the field: a broader term floods
  the search and a neighbouring topic moves it away from the question.
- Propose only names you know the literature uses. The application counts the
  records that hold each proposed phrase and drops one that no record holds,
  and the user decides which of the rest enter the search. An empty `terms`
  list is a good answer when the given phrases are already the usual names.
- Do not combine two given phrases into one proposed phrase, and do not
  translate.

Do not search, do not write Boolean operators or quotation marks, and do not
explain your proposals: there is no field for a rationale and none is wanted.
```

`SKILL.md`'ye görev için bir satır ve `provenance.json`'a bir girdi (dilim 06'nın `criterion-proposal.md` girdisinin kalıbı: DEIXIS için yazıldı, yukarı akıştan uyarlanmadı, SW2.5, bu dilimin D numarası, **ölçülmedi**). `domain/skill.py::RUNTIME_FILES`'a `"term_suggestions": ("SKILL.md", "references/term-suggestions.md")`. Fikstürler ve `fakes.valid_response` yeni görevi tanır: sahte yanıt, hedefteki ilk çapa için sabit SYNTHETIC bir başka ad döndürür.

- [ ] **Tests first:** geçerli çıktı geçer; listede olmayan `synonym_of` tek başına çıktıyı geçersiz kılar; boş `terms` geçerlidir; var olan ifadeyi yineleyen çıktı **geçerlidir** (kod düşürür); görevin onarım sayısı 0; `suggestion_target` başka görevde, ya da bu görevde eksikken StepInput denetimi hata verir; yöntem paketi bütünlük denetimi geçer ve özet değişir.

## Task 2: süzme ve sayım (`workflow/suggestions.py`, saf)

- `anchors(vocabulary) -> list[dict]`: `suggestion_target.phrases`'in satırları. Boşsa öneri istenemez (`no_anchor_phrases`).
- `target(question, vocabulary) -> dict`: Task 1'in hedefi.
- `screen(vocabulary, proposed) -> list[dict]`: modelin `terms` listesinden kart satırları. Her satır `{"phrase", "synonym_of", "block", "phrase_count": None, "dropped": None}`; `phrase` `norm` edilir, `block` çapanın bloğudur. Düşme nedenleri, bu sırayla sınanır ve ilki yazılır: `too_long` (6 sözcükten uzun), `already_present` (`norm` sonrası önerideki herhangi bir ifadeyle aynı — `approval.proposal_blocks`), `contains_claim_word` / `contains_exclusion_word` (ifadenin sözcük dizisi bir iddia / dışlama ifadesini bitişik olarak içeriyor), `duplicate` (aynı ifade listede ikinci kez; ilki kalır). Sıra kanoniktir (SW14.6): çapanın dağarcıktaki yeri, sonra `phrase`.
- Sayım akışta yapılır (Task 3), kuralı buradadır: düşmemiş her satır için tek istek, `query_compiler.quoted(phrase)` ile — `build_vocabulary`'nin ifade sınamasının **aynı sorgusu**, böylece onaydan sonra `known` aynı anahtarı bulur. Sayım 0 ise `dropped = "zero_results"`; okunamadıysa (`None`) satır kalır ve "sayılamadı" görünür, asla 0 değil. En çok 12 istek; kök sözcük ve geçit sınamaları burada **yapılmaz**, onaydan sonra `build_vocabulary` yapar.
- `known_counts(rows) -> dict[str, int]`: sayımı okunmuş satırlar için `{quoted(phrase): count}`.
- `model_phrases(rows) -> set[str]`: kökeni `model` sayılacak `norm` edilmiş ifadeler (düşenler dâhil: kullanıcı düşmüş bir öneriyi elle yazarsa kökeni yine `model`'dir ve `known`'daki 0 onu yine düşürür).

`approval.edited_extraction(vocabulary, term_edits, model_phrases=frozenset())`: eklenen ifadenin kökeni, kümedeyse `model`, değilse `user`. Varsayılan boş küme bugünkü çıktıyı bayt bayt korur.

- [ ] **Tests first:** her düşme nedeni ayrı ayrı; iddia ifadesini ortasında taşıyan öneri düşer, yalnızca bir sözcüğünü paylaşan düşmez; sıra, modelin verdiği sıradan bağımsızdır; `known_counts` `None` sayımı taşımaz; `edited_extraction` model kökenini yalnızca kümedeki ifadeye verir; iki alandan SYNTHETIC örnek.

## Task 3: akış

**Onay adımının çıktısı** iki alan kazanır: `"suggestion_requests": n` (rota artırır; yoksa 0) ve — adım `succeeded` olurken — `"suggestions": <son hazır liste ya da null>`. Yeni onay adımı yazılırken (`_approval`'ın `output is None` dalı), aynı `asked_for`'lu en yeni `succeeded` onayın (`store.approvals_of`) `suggestions`'ı doluysa `"carried_suggestions": {"terms": [...], "from_step_id": …}` olarak kopyalanır; bu durumda model yeniden sorulmaz.

**`_approval` içinde yeni dal**, öneri yazıldıktan hemen sonra ve `submitted` / `earlier` / `as_proposed` dallarından **önce**: `n > 0` ve `code:term_suggestions` adımı (`term_suggestions:{n}`) `succeeded` değilse `await self._term_suggestions(run, scope, vocabulary, n)` çalışır ve ardından **her durumda** `_pause(run_id, "protocol_approval_needed", …)` — eski bir `submitted` dursa bile (fazla geniş bir gönderimden sonra öneri isteyen kullanıcı): öneri isteyen koşu o girişte asla onaylamaz.

**`_term_suggestions`**: kod adımını başlatır; `_checkpoint`; `_model_step(run, scope, f"term_suggestion:{n}", "term_suggestions", optional=True, suggestion_target=…)`. `OptionalStepFailed` ya da `invalid` çıktı: adım `succeeded` kapanır, çıktısı `{"status": "failed", "failure": <neden>, "terms": []}` (ölçüt adımının kalıbı: sürdürülen koşu modeli yeniden çağırmaz; yineleme kullanıcının yeni isteğidir, yeni `n`). Geçerli çıktı: `screen`, sonra düşmemiş satırlar için `self._count_probe(scope)` ile sayım, her istekten önce `_checkpoint` yok, döngüden önce ve sonra var; çıktı `{"status": "ready", "terms": rows, "step_input_id": …}`. Sayımlar tek seferde, adım kapanırken saklanır.

**Onayda** (`_approved_vocabulary`): bu koşunun önerileri = son `ready` kod adımının satırları, yoksa `carried_suggestions`; `reapply` (önceki onay) yolunda önceki adımın `suggestions`'ı. `edited_extraction`'a `model_phrases`, `build_vocabulary`'nin `known`'ına `known_counts` katılır. Hiç terim işlemi yoksa bugünkü erken dönüş aynen kalır.

**Protokol gövdesi:** `approval` kaydına, **yalnızca öneri istendiyse ya da taşındıysa**, `"suggestions": {"requests": n, "proposed": <satır sayısı>, "dropped": <düşen>, "accepted": <eklenen model kökenli terim>, "step_input_id": … | null, "carried_from_step_id": … | null}`. Terim satırlarının `origin`'i `model` olabilir; `TERM_FIELDS` değişmez. `protocol.py`'nin köken okuyan yerleri `model` değerini tanır.

**Bütçe:** `api/app.py`'de `sw` keşif koşusuna `CRITERION_CALLS`'ın yanına `SUGGESTION_CALLS = 1` eklenir (ön ayarlara dokunulmaz; dilim 06 incelemesinin dersi). Başarısız isteğin yinelenmesi bu tek çağrıyı aşarsa `_model_step` `budget_exhausted` ile isteğe bağlı olarak düşer ve kart nedeni gösterir; koşu durmaz.

- [ ] **Tests first** (`tests/test_suggestion_flow.py`): düğmesiz akış bugünküyle aynı (adım yok, gövde ve özet bu dilimden önceki değerle aynı); istekten sonra koşu yeniden `protocol_approval_needed` ile durur ve o anda hiçbir `provider_search` adımı, aday ve protokol kaydı yoktur; sahte sağlayıcı yalnızca sayım isteği görmüştür ve sayısı düşmemiş öneri sayısıdır; öneri isteyip **hiçbirini eklemeden** onaylanan koşunun sorguları önerininkiyle bayt bayt aynıdır ve gövdede `accepted = 0`; eklenen öneri gönderilen sorgu metnine girer, protokolde `origin = "model"` ve `block_origin = "user"` taşır, ifade sayımı **yeniden sorulmaz**; sıfır kayıtlı öneri elle eklenirse `zero_results` ile düşer; model her çağrıda hata verirken istek `failed` kaydedilir, koşu onay için durur ve kullanıcı önerisiz onaylayabilir; `failed`'dan sonra ikinci istek yeni `n` ile yeniden çağırır; öneri sırasında duraklatılıp sürdürülen koşu modeli ve sayımları yinelemez; aynı kapsamda ikinci keşif koşusu durmaz, düzeltmeleri yeniden uygular ve model kökenini korur; yeniden sorulan kart önerileri taşır ve modeli çağırmaz; genişleme revizyonu model kökenli terimi taşır (`_freeze_expansion` tuzağı); `as_proposed` ve `legacy` hiçbir öneri adımı açmaz; öneri beklerken gelen kapsam revizyonu koşuyu iptal eder.

## Task 4: rota ve görünüm

`POST /api/runs/{run_id}/term-suggestions`, gövdesiz; `protocol-approval` rotasının yanında, genel koşu eyleminden **önce** tanımlanır. 409 durumları, ayrı ayrı ve nedenini söyleyerek: onay adımı yok ya da önerisiz; adım `succeeded`; koşu `paused` değil ya da nedeni `APPROVABLE_PAUSES` dışında; çapa yok (`no_anchor_phrases`); bu adımda `ready` bir öneri ya da `carried_suggestions` var (`already_suggested`). Geçerliyse **tek işlemde** `suggestion_requests` bir artar ve koşu `queued` olur (`store.request_term_suggestions`, `submit_approval`'ın kalıbı, olay `run_resumed`), sonra `worker.wake()`. CSRF ve Host / Origin denetimi mevcut ara katmandan gelir.

`views.approval_view` → `"suggestions": {"status": "none" | "requested" | "ready" | "failed", "available": bool, "unavailable_reason": null | "no_anchor_phrases" | "already_suggested", "failure": <neden> | null, "carried": bool, "terms": [{"phrase", "synonym_of", "block", "phrase_count", "dropped"}]}`. `requested`: `n > 0` ve `n`'inci kod adımı kapanmamış. Onaylanmış koşuda alan durur (ne önerildi, ne eklendi okunabilsin). `_approval_side` terim satırları `origin = "model"`'i olduğu gibi taşır.

- [ ] **Tests first:** her 409 ayrı; CSRF'siz istek reddedilir; görünüm `none` → `requested` → `ready` ve `failed` geçişlerini taşır; `carried` doğru; `legacy` koşusunda `approval` yine `None`.

## Task 5: kart

`api.ts`: `ApprovalSuggestions`, `SuggestedTerm` tipleri, `suggestTerms(runId)`, terim `origin` tipine `'model'`. `labels.ts` + `i18n.ts` (EN + TR): köken rozeti `model: 'suggested by the model'`; düşme nedenleri (`already_present`, `contains_claim_word`, `contains_exclusion_word`, `too_long`, `duplicate`); istek hataları için tam cümleler. `Transcript.tsx`: `code:term_suggestions` ve `model:term_suggestions` **plan** fazına bağlanır (08b incelemesinin bulgusu yinelenmesin).

Kartın **Arama terimleri** bölümünün sonunda:

- `available` iken ikincil düğme **Modelden terim öner** ve tek cümle: model, bu terimlerin başka adlarını önerir; hiçbiri siz eklemeden aramaya girmez. `unavailable_reason` varsa düğme yerine o cümle.
- `requested` iken kart kilitlenir (`submitted` kilidinin aynısı) ve "Model terim öneriyor; öneriler sayılıyor" der. **Taslak düzeltmeler bu gidiş dönüşte korunur** (bileşen sökülmez; sökülüyorsa taslak bir üst durumda tutulur).
- `ready` iken **Model önerileri** grubu: her satırda ifade, "*çapa* için başka ad", sayım (yoksa "sayılamadı"), `model` rozeti ve **Ekle**. Ekle, satırı çapanın bloğunda bir taslak `add` yapar (08b'nin eklenen terimiyle aynı satır, rozeti `model`; "onaydan sonra sınanacak" yerine okunmuş sayımı gösterir); taslaktan kaldırınca öneri gruba döner. Düşmüş satır soluk ve nedeniyledir, eylemi yoktur. Liste boşsa: "Model yeni bir ad önermedi." Değişiklik özeti eklenen önerileri ayrıca sayar.
- `failed` iken neden (mevcut duraklatma nedeni metinleri yeniden kullanılır) ve **Yeniden dene**.
- `approved` özetinde eklenen terim `model` rozetiyle görünür; açılınca eklenmeyen öneriler "önerildi, eklenmedi" diye listelenir.

Kart abartmaz: önerilerin doğruluğunu sınayan tek şey sayımdır ve metin bunu söyler ("bu adı taşıyan kayıt sayısı"), "doğrulandı" demez. Erişilebilirlik 08b'nin kurallarıdır; öneri gelince `aria-live` ile duyurulur.

## Task 6: Playwright ve fikstür sunucusu

`fixture_server.py`'nin betikli modeli `term_suggestions`'ı yanıtlar: iki SYNTHETIC başka ad (biri sahte OpenAlex sayımında kayıtlı, biri sıfır) ve var olan bir ifadenin yinelemesi; soru işareti `[suggest-down]` model hatasını seçer. Senaryo **H**'ye (aynı ikinci sunucu) eklenen durumlar:

1. Bir taslak düzeltme yapılır, **Modelden terim öner**'e basılır; kart kilitlenir, sonra öneriler görünür; taslak düzeltme yerindedir; zaman çizelgesinde hâlâ arama adımı yoktur.
2. Sıfır kayıtlı ve yinelenen öneri soluk ve nedenlidir, **Ekle**'si yoktur.
3. Bir öneri eklenir, **Onayla ve ara**; onaylanmış özette terim `model` rozetlidir, eklenmeyen öneri "önerildi, eklenmedi" altındadır.
4. `[suggest-down]`: hata cümlesi ve **Yeniden dene** görünür; önerisiz onay tek tıkla sürer.

Ekran görüntüleri (`DEIXIS_ACCEPTANCE_DIR`): bekleyen kart önerilerle, hata durumu, onaylanmış özet; açık ve koyu tema, 390 px. `Read` ile açılıp bakılır, bulunan düzeltilir.

## Task 7: dilimi kapat

- [ ] `PYTHONPATH=backend:. uv run pytest` tamamı; bilinen tek başarısızlık `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`. `cd apps/web && npm run build && npm run lint`; `DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance npm run test:acceptance` (A–G + H). `git diff --check`.
- [ ] `docs/decisions.md` en üste `## D<NN> — Let the user ask a model for other names of the search terms on the approval card; count every proposal, and let none into the query unless the user adds it`. Limits adıyla söylemeli: yalnızca `sw` ve yalnızca kullanıcı isteyince — **SW2.5'in "ilk tur zayıfsa" yarısı kurulmadı**, eşik tanımlanmadı (dilim 24); **SW2.5'in "doğrulanmış bir pozitifte geçmeyen terim kalmaz" kuralı kurulmadı** (doğrulanmış pozitif dilim 12'den önce yok; terim başına verim dilim 19); **istem ve sınırlar hiçbir modelle ölçülmedi** (kaç öneri sayımı geçiyor, kaçı gerçekten başka ad, kaçı alanın komşu konusu — 04b'de görülen kayma burada da beklenebilir); tek çağrı, oylama yok, yani liste koşudan koşuya değişebilir ve yalnızca saklandığı için tekrarlanabilir; sayım bir adın literatürde var olduğunu gösterir, aynı şeyi adlandırdığını değil; model kullanıcının taslak düzeltmelerini görmez; öneri yalnızca aranan iki blok için; iptal edilen koşunun önerileri sonraki koşuya taşınmaz (yalnızca onaylanmış adımınkiler); sayım istekleri `provider_requests` sayacına girmiyor (04a ile aynı).
- [ ] SW belgesinde SW2 **Status** satırına bir cümle (madde 5: yalnızca "kullanıcı isterse" yarısı, ölçülmedi). `sw-status.md` satır 08c: `uygulandı, inceleme bekliyor` + açık kalanlar + `skill_package_hash` önce / sonra. Tek commit, `git push origin main`.

**Bölünme noktası:** Task 5–6 (kart ve Playwright) ayrı bir sohbete bırakılabilir. O durumda Task 1–4 + 7 commit'lenir, satır 08c "arka uç uygulandı, kart bekliyor" der ve bunu adıyla yazar: öneri yalnızca API ile istenebilir. Fikstür sunucusunun yeni görevi yanıtlaması Task 1'le birlikte gider (yoksa H kırılmaz ama yeni görev yanıtsız kalır).

## Son ileti

Eklenen ve değişen dosyalar; temel ve son test sayıları ve komut; build, lint, Playwright (A–G ve H ayrı); `skill_package_hash` önce / sonra; "eklenmeyen öneri sorguya girmez", "eklenen önerinin sayımı yeniden sorulmaz", "model kökeni sunucuda türetilir" ve "öneri istenmeyen koşunun gövdesi aynı" testlerinin adları; bakılan ekran görüntülerinin yolları ve onlarda bulunup düzeltilenler; yöntem dosyasının metnine dokunulmadığı; yazıldığı gibi yapılamayan her şey ve seçilen her sapma; yapılmayanlar; dokunulan kanıt sınırları (beklenen: `sw` protokolünde terim kökeni `model` olabilir; `approval` gövdesi öneri istendiyse `suggestions` kazanır; hiçbir öneri kullanıcı eklemeden aranmaz); canlı servise, ürün veritabanına ve hiçbir canlı modele dokunulmadığı; commit özeti.

## Açık noktalar

- **Ölçüm (dilim 24):** iki konuda, öneri istenen ve istenmeyen kollar; bakılacaklar: sayımı geçen öneri payı, kullanıcının (ölçümde: önceden dondurulmuş bir kabul kuralının) eklediği pay, eklenen terimlerin getirdiği yeni pozitif ve yeni satır sayısı, komşu konuya kayma. "İlk tur zayıf" eşiği ancak bu ölçümden sonra tanımlanır; o zamana kadar otomatik tetik yoktur.
- **Tek çağrı mı, üç çağrı mı:** etiketleme ve ölçüt adımları üç koşu ve 2/3 oy kullanıyor, çünkü çıktıları kimse görmeden protokole giriyordu. Burada her terimin önünde iki süzgeç var (sayım, kullanıcı) ve 2/3 oyu tam da aranan seyrek ama doğru adı eler; kullanıcı da kartın başında bekliyor. Üç koşunun birleşimi ("kaç koşu önerdi" sinyaliyle) dilim 24'te denenecek bir koldur, bu dilimde kurulmaz.
- **Taslağı görmeyen model:** kullanıcı bir terimi taşıdıktan ya da sildikten sonra öneri isterse model yine ilk öneriyi görür. Taslağı istekle göndermek rotaya ikinci bir düzeltme paketi ve ikinci bir doğrulama getirirdi; ilk sürümde yok.
- **Sonuç ve ölçüt ifadeleri:** model yalnızca aranan iki bloğa ad önerir; `outcome` terimleri ve ölçütün ipucu ifadeleri için öneri yok (ifadeler zaten model üretimi, dilim 06).
- **`vocabulary_empty` durumunda:** hiçbir çapa yoksa düğme kapalıdır; çıkış yolu yine terim eklemek ya da `key_terms`'tir. Çapalar düşmüş ama varsa (hepsi sıfır kayıtlı) düğme açıktır ve en yararlı olduğu durum budur.
