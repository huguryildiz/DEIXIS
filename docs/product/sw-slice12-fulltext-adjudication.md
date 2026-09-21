# SW dilim 12 — Tam metin kararı: uygulama planı

**Tarih:** 22 Eylül 2026. **Durum:** yazıldı, uygulanmadı. **Ana dosya:** [sw-status.md](sw-status.md). **Ana plan:** [sw-implementation-plan.md](sw-implementation-plan.md) (§2 kuralları geçerlidir). **Spec:** [search-workflow-review-2026-09-18.md](search-workflow-review-2026-09-18.md): **SW1** madde 1, 5 (yalnızca "kapı kapalı"), 6, 7; **SW11** madde 1–5; **SW15** madde 5; **SW16** madde 1 ve 5. **Önkoşul:** 02, 10, 11 (kapandı). **Tür:** Kur. **Uygulayan:** Grok 4.7 (sahibin kararı). **İnceleme:** tam, biter bitmez (Opus · high).

**Sahibin kararları (22 Eylül 2026, plan sohbeti):**

1. **Okuma ayrı bir koşudur ve getirmeden sonra kendiliğinden başlar.** Yeni koşu türü `fulltext_adjudication` (migration `0046`): `sw` araştırmasının `fulltext_fetch` koşusu `completed` olunca kuyruğa girer. Getirme koşusu, bütçesi ve testleri olduğu gibi kalır. İşçi tek olduğu için bu koşu sürerken yanıt ya da keşif başlatmak isteyen kullanıcı onu duraklatır; yazılmış kararlar kalır.
2. **Koşu başına iş sınırı 20 / 50 / 150** (quick / standard / detailed), iş başına iki model çağrısı, yani 40 / 100 / 300 çağrı. Elle seçildi, **ölçülmedi**. Sınırın dışındaki iş silinmez, `not_read_yet` kalır ve sonraki koşu oradan sürer.
3. **Uygulayan Grok 4.7, inceleyen Opus.** Bu depoda Grok ilk kez uygular; dosya bu yüzden "uydurma, dur ve bildir" kuralına ve adıyla istenen testlere yaslanır.

**Goal:** Bugün `sw` araştırmasında hiçbir iş kodla dahil edilmez: özet aşaması yalnızca aday üretir (D81), getirme koşusu metni getirip `not_read_yet` yazar (D83). Bu dilimden sonra: (1) kod, metni olan işleri sıraya koyar ve planı dondurur; (2) her iş için model, o işin **seçilmiş pasajlarını** iki bağımsız koşuda okur ve ölçütün **her parçası** için bir etiket + birebir alıntı önerir; (3) kod her alıntıyı **sayfa metninde** doğrular ve sayfa numarasını saklar; (4) kural tablosu kararı yazar: `include` (iki koşu da her parça için doğrulanmış alıntı verdi), `criterion_not_met` (iki koşu da hiçbir parçayı bulamadı), yoksa nedenine göre `unresolved`; (5) `include` → `selections.included`, `criterion_not_met` → `excluded` (`code_rule`), kullanıcının seçimi her zaman üstündür. Model yalnızca önerir; güven puanı yok; kod kapısı **kapalı** (her metin modele gider); model kapalıyken her iş `not_read_yet` bekler.

**Architecture:** yeni saf modül `workflow/adjudication.py` (plan, okuma listesi, öneri ayıklama, alıntı doğrulama, koşu hükmü, birleştirme). `flow._fulltext_adjudication` yeni koşu türünü yürütür; gönderim `_send_through_limiter` ile (iş birimi = (iş, koşu no)). Adımlar: `code:adjudication_plan` (anahtar `adjudication_plan`), `model:fulltext_adjudication` (anahtar `fulltext_adjudication:{baş}:{koşu no}`), `code:adjudication_summary`. Yeni sözleşme `contracts/research/fulltext-adjudication.schema.json`, yeni yöntem dosyası `references/fulltext-adjudication.md`; **`skill_package_hash` değişir**. **Migration `0046`** (yalnızca koşu türü `CHECK`'i; `model_proposals` parça başına öneriyi `0038`'den beri taşıyor). Bir yeni gerekçe kodu.

**Tech stack:** Python 3.12. `apps/web`'de yalnızca Task 8.

## Global constraints

- `legacy` araştırmada koşu kuyruğa girmez ve tür 422 alır; `discovery`, `fulltext_fetch`, `answer`, `pdf_collection` koşularının adımları ve bütçeleri **aynı** kalır. `CAPABILITIES.supported_tasks`'e yeni görev **eklenmez** (dilim 09'un gerekçesi: her saklı StepInput değişirdi).
- **Karar yetkisi koddadır** (§2 kural 3): modelin etiketi tek başına hiçbir şey yazmaz; iki koşu + kural tablosu yazar. Modelin verdiği güven, puan ya da "emin değilim" metni kullanılmaz. Model adımı araç almaz; sınırlı şema onarımı dışında döngü yok.
- **Kullanıcı üstündür:** tam metin aşamasında insan kararı taşıyan iş plana girmez; `HumanDecisionStands` yutulmaz, o iş atlanır; `derive_selection` `origin = user` seçimi ezmez. Kullanıcının dışladığı iş okunmaz. Kullanıcının dahil ettiği iş okunur (kanıt üretir) ama seçimi değişmez.
- **Kod kapısı kapalı** (SW16.1): ifade sayımı hiçbir işi kapatmaz, hiçbir işi modelden esirgemez; ifadeler yalnızca okunacak pasajları sıralar (dilim 11'in `criterion_order`'ı, ikinci bir sıralayıcı yazılmaz). Ön baskı ve model ailesi kuyruk nedeni **değildir** (SW11.5); sürüm etiketi kararın yazıldığı sürümden okunur.
- **Ders A: koşular arasında kalan satırlar araştırmanın geçmişidir.** Adıyla:
  - Ölçüt yalnızca `store.frozen_criterion(rid, question, steering)` ile okunur ve **plan adımında dondurulur** (ölçüt cümlesi, parçalar, ifadeler, `protocol_revision`); sürdürülen koşu saklı planı okur. Ölçüt yoksa (`None`) plan `reason: "no_criterion"` ile kapanır, hiçbir çağrı yapılmaz, koşu `completed` olur; kendiliğinden kuyruğa girme de ölçüt yoksa koşu açmaz.
  - `not_read_yet` ve bu dilimin yazdığı kodlar koşudan koşuya kalır. **Taze** (eskimemiş) bir model kararı (`all_parts_verified`, `criterion_absent`, `fulltext_runs_disagree`, `include_quote_unverified`, `part_without_evidence`, `fulltext_runs_agree_unresolved`, `pdf_identity_unconfirmed`) taşıyan iş yeniden okunmaz: "sonraki koşu kaldığı yerden sürer" budur. **Eskimiş** karar (soru ya da ölçüt değişti; `decisions.is_stale`) taşıyan iş yeniden plana girer.
  - **Yanıtsız kalan çağrı:** iki koşusundan biri yanıt vermeyen iş (bağlantı hatası, hız sınırı, duraklatma) **karar almaz**, `not_read_yet` kalır; aynı koşu sürdürülünce yalnızca eksik çağrı yapılır; koşu bittiyse sonraki koşunun planına girer ve **iki çağrısı da yeniden yapılır** (önceki koşunun adım çıktısına bakılmaz: o, o koşunun kaydıdır). Geçersiz çıktı (`invalid_model_output`) yanıt sayılır: o koşuda yinelenmez, iş karar almaz, sonraki koşu yeniden okur (dilim 09'un kuralı).
  - **Kimlik denetimi okuma anında yeniden hesaplanır** (`identity.check`, saf); dilim 10'un `code:fulltext_work` adım çıktısından **okunmaz** — o çıktı başka bir koşunundur ve ekli PDF'ler (`already_text`) için hiç yoktur.
- **Ders B: kayıtlar araştırmalar arasında ortaktır.** PDF metni ve pasajlar ortak satırlardır; öneriler ve kararlar `research_id` taşır. Okunacak sürüm yalnızca `store.work_versions(rid, head)` içinden seçilir: başka bir araştırmanın aynı işe bağladığı ama bu araştırmaya üye olmayan sürüm satırı okunmaz. Bu dilim ortak satır açmaz; açması gerekirse dur ve bildir.
- **Ders C: `store.step` okurken adım açar.** Yalnızca adımı yürüten yol çağırır; görünüm, özet ve testler açmayan yoldan okur (`latest_step_output`, `_other_copy_step` kalıbı). Sınaması: koşu görünümünü okumak hiçbir koşuda `pending` adım bırakmaz; başka koşu türleri bu dilimin adımlarını açmaz.
- **Ders D: bütçe koşunun toplamına bakar ve başlatılan her çağrı sayılır.** Bütçe: `{"max_model_calls": 2 * N, "max_provider_requests": 0, "max_fulltext_reads": N}`, `N = FULLTEXT_READ_LIMIT[effort]`. **Yeni pay yok:** şema onarımı ve başarısız çağrı aynı toplamdan öder; ayrı bir yineleme payı eklenmez. Sonucu adıyla: onarım ya da başarısız çağrı harcandıysa planın **sonundaki** işler okunmaz; bu sessiz olmaz — özet adımı onları `not_reached` diye sayar, karar yazılmaz (`not_read_yet` kalır), sonraki koşu okur. Bir iş **yarım gönderilmez:** borçlu olduğu çağrıların hepsi bütçeye sığmıyorsa hiçbiri gönderilmez (`_model_calls_left(run, len(owed), submitted, spent_before)`; dilim 09 kalıbı). Sürdürülen koşuda depodan geri okunan yanıt bütçeye yazılmaz (dilim 09 incelemesinin hatası). Uygulayan, onarım denemesinin `usage["model_calls"]`'a yazılıp yazılmadığını koddan okur ve son iletide söyler.
- **Eşzamanlılık için ikinci düzenek yazılmaz:** tek yol `flow._send_through_limiter`; `asyncio.gather`, kendi semaforu, yeni döngü yok. Aynı işin iki koşusu aynı anda uçuşta olabilir (bağımsızdırlar).
- **Plan dondurulur;** adım anahtarları baş kimliğine bağlıdır, sıradaki yere değil.
- Elle seçilen sayılar `domain/rules.py`'de adlı sabittir ve `sw` protokolünün `thresholds.fulltext_adjudication` alanına yazılır: `FULLTEXT_READ_LIMIT = {"quick": 20, "standard": 50, "detailed": 150}`, `FULLTEXT_RUNS = 2`, `FULLTEXT_PASSAGES_PER_CALL = 12`, `FULLTEXT_CRITERION_PASSAGES = 8`, `FULLTEXT_QUOTE_MIN_CHARS = 12`.
- Araştırma genelindeki okumalar birkaç sorguda yapılır (kayıt başına sorgu yok). Testlerde ağ yok; fikstürler SYNTHETIC ve en az iki alandan; ürün koduna konuya özgü sözcük girmez.
- Başlamadan kontrol et: son karar `D84`, son migration `0045`. Bu dilim `D85` ve `0046` alır.

## Dosya yapısı

Yeni: `backend/deixis/storage/migrations/0046_fulltext_adjudication_run_kind.sql`, `backend/deixis/workflow/adjudication.py`, `contracts/research/fulltext-adjudication.schema.json`, `methods/deixis-research/references/fulltext-adjudication.md`, `tests/test_adjudication.py` (saf), `tests/test_adjudication_flow.py` (`create_app` ile).

Değişecek: `domain/rules.py`, `domain/reason_codes.py`, `domain/contracts.py`, `domain/skill.py` (`RUNTIME_FILES`), `contracts/research/step-input.schema.json`, `methods/deixis-research/SKILL.md` + `provenance.json`, `config.py` (`Settings.fulltext_adjudication`), `workflow/flow.py`, `workflow/store.py` (koşu aşaması eşlemesi, `STEP_OUTPUT_KINDS`, `page_texts`), `workflow/decisions.py` (`work_outcome`), `workflow/protocol.py`, `api/app.py`, `tests/fakes.py`, `tests/fixtures/research/{step-inputs,fake-outputs}.json`, `tests/determinism_stages.py`, `tests/acceptance/fixture_server.py`, `apps/web/src/{api.ts,labels.ts,i18n.ts,Transcript.tsx,BackgroundJobs.tsx,ResearchView.tsx}`, `docs/decisions.md`, SW belgesi (SW1, SW11, SW16 durum satırları), `sw-status.md`.

## Task 1: koşu türü, ayar, bütçe, gerekçe kodu

- Migration `0046`: `runs.kind` `CHECK`'ine `fulltext_adjudication`; `0045` kalıbıyla (`-- deixis:foreign-keys-off`, satırlar korunur). `store.create_run` aşama eşlemesi: → `inspection`.
- `Settings.fulltext_adjudication`: `auto` | `off`, `DEIXIS_FULLTEXT_ADJUDICATION`, varsayılan `auto`. `tests/test_fulltext_flow.py`'nin kurulumu ve `tests/acceptance/fixture_server.py` `off` alır (getirme koşusundan sonra ikinci bir koşunun açılmamasına dayanıyorlar); beklentileri değişmez.
- `api/app.py`: `StartRun.kind`'a tür; yalnızca `sw`'de (yoksa 422). Bütçe tek işlevden (`adjudication.read_budget(effort)`), `flow` da onu çağırır. `TEST_EFFORT_BUDGETS`'a dokunulmaz.
- `reason_codes.py`: **yeni** `fulltext_runs_agree_unresolved` (fulltext / unresolved / code / human_queue) ve `pdf_identity_unconfirmed` (fulltext / unresolved / code / human_queue). Öbür kodlar dilim 02'den beri tabloda. `stage_decisions.reason_code` düz `TEXT`'tir, migration gerekmez (doğrula).

- [ ] **Tests first:** migration eski satırları korur; `legacy`'de 422; bütçe 40 / 100 / 300 çağrı ve 20 / 50 / 150 iş; iki yeni kod tabloda ve `pending`'e türer.

## Task 2: plan ve okuma listesi (saf)

`adjudication.read_plan(works, order, limit) -> {"works": [baş…], "not_reached": [baş…]}`. `works` satırı dilim 10'un `_fulltext_works` satırıdır (yeniden kullan; gerekiyorsa alan ekle, ikinci bir sorgu seti yazma). **Uygun iş:** `work_versions` içinde PDF metni olan en az bir sürümü var; `fulltext.group_of(work)` bir grup veriyor (kullanıcının dahil ettiği → aday → `unresolved`; aynı işlev, aynı sıra, grup içinde `order`); tam metin aşamasında insan kararı yok; taze model kararı yok (Ders A listesi). `text_unreadable` ve `no_fulltext` iş uygun değildir (okunacak metin yok). İlk `limit` iş `works`, gerisi `not_reached`.

`adjudication.reading_list(passages, criterion, topic_ranked, per_call, criterion_share) -> {"passages": [...], "whole_text": bool}`. Okunan sürüm `store.answer_version`'ın seçtiğidir. İşin `pdf_page` pasajı `per_call`'dan azsa **hepsi** verilir (`whole_text: true`). Değilse: önce ölçüt pasajları, **parça parça turlarla** — her parçanın kendi ifadeleriyle `criterion_passages.criterion_order` çağrılır (parçasız ifadeler ayrı bir grup sayılır), tur *r* her parçanın *r*'inci pasajını alır, `criterion_share` (8) dolana dek; sonra konu sırası (`topic_ranked`: `store.search_passages([svid], fts, …)`, `_retrieve`'in terim listesiyle); kalan yer sayfa sırasıyla. Özet pasajı verilmez (karar tam metinden çıkar). Liste sayfa sırasına dizilerek gönderilir. İfade yoksa ölçüt adımı boş geçer ve liste konu sırası + sayfa sırasıdır. `_retrieve`'in terim kuran bölümü davranışı değişmeden `_topic_terms(rid, scope)` yardımcı işlevine **taşınabilir** (adıyla izinli; `legacy` seçimi aynı kalmalı, dilim 11'in testleri bunu gösterir).

- [ ] **Tests first:** grup sırası; taze model kararlı iş girmez, eskimiş girer; insan kararlı ve kullanıcının dışladığı iş girmez; metinsiz iş girmez; `limit`'te keser, hiçbir işi düşürmez; kısa metin bütün verilir; turlar her parçaya yer verir; ifade yokken liste konu + sayfa sırası; `per_call` aşılmaz; iki hash tohumunda aynı.

## Task 3: sözleşme ve yöntem dosyası

- `step-input.schema.json`: `task_type` enum'una `fulltext_adjudication`; yeni `adjudication_target = {"source_id", "criterion", "parts": [{"name", "definition"}], "runs", "run"}` (additionalProperties false). Parçasız ölçüt (`criterion_parts: []`) tek parça olarak gönderilir: `{"name": "criterion", "definition": <ölçüt cümlesi>}`.
- `fulltext-adjudication.schema.json` (`deixis.fulltext_adjudication.v1`): `schema_version`, `step_input_id`, `scope_revision`, `skill_package_hash`, `parts: [{"part", "label": "present" | "absent" | "unclear", "quote" (≤ 600; yalnızca `present`'te dolu), "passage_id", "rationale" (1–300)}]`.
- `contracts.py`: `SCHEMA_FILES`, `SCHEMA_VERSIONS`, `TASK_OUTPUTS`, hedef denetimi (`adjudication_target_mismatch`, `adjudication_run_out_of_range`), `_check_fulltext_adjudication` — kayıt düzeyi kusurlar **uyarıdır** ve `adjudication.proposals_of` ile aynı adımda tutulur: bilinmeyen parça, yinelenen parça (iki kopya da düşer), eksik parça, alıntısız `present`, izin listesinde olmayan `passage_id` → o parça o koşuda `unclear` sayılır. `flow.HANDLE_TASKS`'e görev eklenir (pasajlar `psg_P…` tutamağıyla gider, D12).
- Yöntem dosyası `references/fulltext-adjudication.md`, metni **değiştirilmeden** şu:

  > You are given one paper's selected passages, one inclusion criterion and its parts. For each part decide whether these passages show that the paper itself contains it. Answer every part exactly once, by its name.
  > `present`: a passage states it. Copy one continuous quote from that passage, character for character, at most 600 characters, and name the passage. Do not join text from two places, do not correct, translate or complete it. An equation may be quoted as it is printed.
  > `absent`: the passages describe what the paper does and this part is not among it. No quote.
  > `unclear`: the passages do not let you tell. No quote. Passages are a selection, not the whole paper: when the part could be elsewhere in the paper, say `unclear`, not `absent`.
  > What the paper cites, surveys or plans as future work is not something the paper contains. Judge only the passages given; use nothing you remember about this paper. Give one sentence of rationale per part. Do not state a confidence.

  `SKILL.md`'ye görev paragrafı, `provenance.json`'a türetilmiş dosya girdisi, `skill.RUNTIME_FILES`'a satır. **İstem hiçbir modelle denenmedi** (dilim 13 duman testi ilk denemedir).
- `tests/fakes.py::valid_response`: her parça `present`, alıntı = ilk pasajın ilk 60 karakteri, `passage_id` o pasaj (iki koşu anlaşır, alıntı doğrulanır). Fikstürler: `H_fulltext_adjudication` girdi; çıktılar `fulltext_adjudication_valid`, `…_unknown_duplicate_and_quoteless_are_warnings`, `…_label_outside_the_schema`. Fikstür sunucusu `valid_response`'tan başlar.

- [ ] **Tests first:** sözleşme testleri (`tests/test_contracts.py` kalıbı); yöntem paketi bütünlük denetimi geçer; `skill_package_hash` değişti.

## Task 4: alıntı doğrulama ve kural tablosu (saf)

- `store.page_texts(svid) -> {physical_page: text}`: aynı sayfanın parçaları `rowid` sırasıyla boşlukla birleştirilir (salt okuma; parçalar örtüşmez). `adjudication.verify(quote, pages, named_page, min_chars) -> {"verified", "page"}`: `contracts.locate_anchor` ile, yalnızca `exact` / `normalized` (bulanık eşleşme kabul edilmez); önce modelin adını verdiği pasajın sayfası, sonra **modele gösterilen** öbür sayfalar. Gösterilmeyen sayfada arama yapılmaz. Parça sınırında bölünmüş alıntı sayfa metninde bulunur (SW12.2).
- Koşu hükmü `adjudication.verdict(parts)`: her parça `present` → `include`; hiçbir parça `present` değil ve en az biri `absent` → `not_met`; bazı parçalar `present`, bazıları değil → `partial`; hepsi `unclear` → `unclear`.
- `adjudication.combine(first, second)`; kimlik satırı `combine`'ın değil planın işidir (Task 5.1), tabloda bütünlük için durur:

| durum | kod |
|---|---|
| koşulardan biri yok (yanıtsız / geçersiz) | `None` — karar yazılmaz |
| `identity == "unconfirmed"` (metin bu işin DOI'sini / başlığını taşımıyor) | `pdf_identity_unconfirmed` — çağrı **yapılmadan** plan anında yazılır |
| hükümler farklı | `fulltext_runs_disagree` |
| ikisi `include`, iki koşunun **her** parça alıntısı doğrulandı | `all_parts_verified` |
| ikisi `include`, en az bir alıntı doğrulanamadı | `include_quote_unverified` |
| ikisi `not_met` | `criterion_absent` |
| ikisi `partial` | `part_without_evidence` |
| ikisi `unclear` | `fulltext_runs_agree_unresolved` |

  `abstract_promise_absent` **kurulmaz:** özet aşaması ölçüt parçalarını değil kapsamı yargılıyor, "özetin vaadi" saklı değil. Kullanıcının kendi eklediği PDF (`origin` kullanıcı yüklemesi) kimlik denetiminden muaftır.
- `decisions.work_outcome`: **eskimiş ve insan eliyle verilmemiş** tam metin kararı iş adına konuşmaz; özet aşamasının sonucu kullanılır (dilim 10'un açık noktası). Eskimiş **insan** kararı konuşmaya devam eder (SW11.10: saklanır, "yeniden bak" diye işaretlenir).

- [ ] **Tests first:** tablonun her satırı; sayfa sınırı içinde parça sınırında bölünmüş alıntı doğrulanır; bulanık eşleşme doğrulanmaz; gösterilmeyen sayfadaki alıntı doğrulanmaz; `min_chars` altı doğrulanmaz; `proposals_of` kusurlu parçayı `unclear` sayar; `work_outcome` eskimiş kod kararını atlar, eskimiş insan kararını atlamaz.

## Task 5: akış

`flow._fulltext_adjudication(run, scope)`; `execute`'ta yeni dal.

1. **`code:adjudication_plan`.** `succeeded` ise saklı çıktı. Değilse ölçüt (`frozen_criterion`), `read_plan`, her iş için okunan sürüm ve `identity.check` (kullanıcı yüklemesi değilse). `unconfirmed` işlere kod hemen yazılır ve plana alınmazlar. Çıktı: `{"limit", "criterion": {…, "protocol_revision"}, "works": [{"head", "read_version"}], "not_reached": n, "identity_unconfirmed": n, "reason": null | "no_criterion"}`.
2. **Çağrılar** `_send_through_limiter` ile; iş = (baş, koşu no), anahtar `fulltext_adjudication:{baş}:{koşu no}`; her gönderimden önce `_checkpoint(run_id, scope_revision)`. Okuma listesi gönderim anında kurulur ve StepInput ile saklanır. Yanıtlamış adım (`succeeded` ya da `invalid_model_output`) yeniden gönderilmez ve bütçeye yazılmaz. Bütçe kuralı Ders D'deki gibi.
3. **İşi kapatma** (iki koşu da döndüğünde, olay döngüsünde kısa işlemle, `await` yok): her koşunun her parçası için `add_proposal(stage="fulltext", run_no, label, criterion_part=<parça adı>, quote, quote_verified, quote_passage_id, quote_page)`; `combine`; `DecisionStore.record(kod, step_id=<son koşunun adımı>)` **okunan sürüme**; `derive_selection`. Yazma kuralı dilim 09 / 10'un `should_write` ruhunda (aynı taze kod yeniden yazılmaz; insan kararı varsa yazılmaz). Koşu etkin değilse ya da kapsam revizyonu değiştiyse uçuştaki yanıtın adımı saklanır ama karar **yazılmaz** (`_table_fill` kuralı).
4. Bir işin beklenmeyen istisnası koşuyu durdurmaz. Model bağlantısı yoksa / kapalıysa davranış `_abstract_call`'un bugünkü davranışıdır (yeni bir yol uydurma): hiçbir karar yazılmaz, işler `not_read_yet` bekler.
5. **`code:adjudication_summary`**, bu koşunun **saklı adımlarından ve yazdığı kararlardan**: `{"read": n, "include": n, "criterion_not_met": n, "unresolved": {kod: n}, "not_settled": n, "not_reached": n, "identity_unconfirmed": n, "whole_text": n, "model_calls": n}`.

**Kendiliğinden kuyruğa girme:** `execute`, bir `fulltext_fetch` koşusunu `completed` yaptıktan hemen sonra (araya `await` girmeden), araştırma `sw`, ayar `auto`, ölçüt var ve `read_plan` en az bir iş veriyorsa `create_run(rid, "fulltext_adjudication", bütçe, idempotency_key=f"fulltext_adjudication:after:{run_id}")`.

- [ ] **Tests first** (`tests/test_adjudication_flow.py`): `auto` iken tamamlanan getirme koşusunu okuma koşusu izler; `off`, `legacy` ve ölçütsüz araştırmada izlemez; iki koşu anlaşıp alıntılar doğrulanınca iş `all_parts_verified` + seçimi `included` + `code_rule`, karar okunan sürümde ve sayfa numarası saklı; doğrulanamayan alıntıya dayanan `include` dahil **edilmez** (`include_quote_unverified` + `pending`); iki `not_met` → `excluded`; anlaşmazlık → `pending`; kullanıcının dışladığı iş okunmaz, kullanıcının dahil ettiği iş `criterion_absent` alsa da `included` kalır; insan kararlı iş okunmaz; model kapalıyken hiçbir karar yazılmaz ve işler `not_read_yet` kalır (kabul koşulu); bir koşusu yanıtsız kalan iş karar almaz, sürdürülünce yalnızca eksik çağrı yapılır, **sonraki** koşuda iki çağrı da yapılır; geçersiz çıktı o koşuda yinelenmez; taze kararlı iş sonraki koşuda okunmaz (model çağrı sayısıyla), soru revize edilince okunur; sınırın dışındaki iş `not_reached` ve ikinci koşu onu okur; **plan boyu sınıra eşitken ortada duraklatılıp sürdürülen koşu planın tamamını bitirir, hiçbir çağrıyı iki kez yapmaz ve özeti kesintisiz koşununkiyle aynıdır**; harcanan onarım / başarısız çağrı sondaki işi `not_reached` bırakır ve hiçbir iş yarım gönderilmez; uçuşta en çok `limiter.limit` çağrı; kapsam revizyonu koşuyu iptal eder ve uçuştaki yanıt karar yazmaz; `unconfirmed` kimlikli iş çağrı yapılmadan `pdf_identity_unconfirmed` alır, kullanıcı yüklemesi muaf; başka araştırmanın üye olmayan sürüm satırı okunmaz (Ders B); görünüm okumak `pending` adım bırakmaz ve öbür koşu türleri bu adımları açmaz (Ders C); `discovery` / `fulltext_fetch` / `answer` koşuları bu dilimden önceki adımları verir.

## Task 6: protokol ve tekrar aşaması

`protocol.py`: `sw` gövdesinde `thresholds.fulltext_adjudication` (Global constraints'teki beş sabit; `read_limit` kapsamın eforundan). `legacy` gövdesi aynı. `determinism_stages.py`'ye `adjudication` aşaması: sabit işler + pasajlar + iki koşunun sabit önerileri → plan, okuma listeleri, doğrulamalar ve kodlar tek özet; iki hash tohumu.

## Task 7: görünüm

`store.STEP_OUTPUT_KINDS`'e `code:adjudication_plan` ve `code:adjudication_summary`. Yeni uç nokta ve `views.py`'de yeni alan yok; kararların, alıntıların ve kuyruğun ekranı dilim 16–18 / 20.

## Task 8: arayüz (en az)

Önce [.impeccable.md](../../.impeccable.md). Dilim 10 Task 8'in kalıbı: `api.ts` `RunKind`; `labels.ts` + `i18n.ts` (EN + TR): koşu "Full-text reading" / "Tam metin okuma"; adımlar "Reading plan (code)" / "Okuma planı (kod)", "Full-text proposal" / "Tam metin önerisi", "Reading summary (code)" / "Okuma özeti (kod)"; `Transcript.tsx` faz ve plan cümlesi "A model reads selected passages of each work twice; code checks every quote on the page and decides." (TR karşılığıyla); `BackgroundJobs.tsx` `JOB_KINDS`; `ResearchView.tsx` koşu türü süzgeci. Yeni Playwright senaryosu yok; A–H geçer (sunucu `off`).

## Task 9: dilimi kapat

- [ ] `PYTHONPATH=backend:. uv run pytest` tamamı (bilinen tek başarısızlık aynı). `cd apps/web && npm run build && npm run lint`, Playwright A–H. `git diff --check`. Canlı model çağrısı, kuru çalıştırma **yok**.
- [ ] `docs/decisions.md` en üste `## D85 — Follow an sw retrieval run with a full-text reading run: two model runs propose a label and a verbatim quote per criterion part, code checks every quote on the page, and only agreement with every quote verified includes a work`. Limits adıyla: yalnızca `sw`; **istem, iş sınırı, çağrı başına 12 pasaj ve 8 / 4 bölüşümü, alıntı alt sınırı hiçbir modelle denenmedi ve ölçülmedi** (dilim 13 duman, dilim 24 ölçüm); model işin **seçilmiş** pasajlarını görür, bu yüzden `criterion_absent` "gösterilen pasajlarda yok" demektir ve iş kodla `excluded` olur — kullanıcı ezebilir, iş kendi grubunda görünür kalır (SW11.2), ama bunu gösteren ekran yok; birebir doğrulama alıntının var olduğunu gösterir, etiketi desteklediğini değil (SW1 Limits); iki koşu aynı modelin iki koşusudur, tutarlılığı gösterir, doğruluğu değil; kapı kapalı, tasarruf yok; `abstract_promise_absent`, kapı–model çelişkisi, kuyruk ekranı ve kullanıcının PDF eklemesine anında yanıt (SW11.9) kurulmadı; "üçüncü koşu" yok; onarım ve başarısız çağrı sondaki işlerin okunmamasına yol açar; tek işçide üçüncü sıralı koşu.
- [ ] SW belgesinde SW1, SW11, SW16 **Status** satırlarına birer cümle. `sw-status.md` satır 12: `uygulandı, inceleme bekliyor` + açık kalanlar. Tek commit, `git push origin main`.

## Güncellenecek mevcut testler (adıyla izinli)

- `tests/test_fulltext_flow.py` kurulumu ve `tests/acceptance/fixture_server.py`: `fulltext_adjudication="off"` (beklenti değişmez).
- `test_a_stale_fulltext_decision_still_shadows_a_newer_abstract_decision`: davranış bu dilimde **düzeltilir**; test yeniden adlandırılır ve beklentisi özet aşamasının sonucuna döner.
- `test_only_an_sw_protocol_carries_the_record_identity_thresholds`: `sw` gövdesi `thresholds.fulltext_adjudication` kazanır.
- Görev listesini ya da yöntem paketinin dosyalarını tam liste olarak sayan sözleşme / paket testleri yeni görevi ve dosyayı kazanır.
- Bunların dışında bir mevcut test kırılırsa dur ve bildir.

## Son ileti

Eklenen ve değişen dosyalar; temel ve son test sayıları, komut, Playwright sonucu; `skill_package_hash` önce / sonra (beklenen: değişti); "doğrulanamayan alıntı dahil etmez", "model kapalıyken karar yok", "kullanıcının seçimi ezilmez", "sürdürülen koşu planı bitirir ve hiçbir çağrıyı iki kez yapmaz", "yanıtsız iş sonraki koşuda iki çağrıyla okunur", "iş yarım gönderilmez", "okuma adım açmaz" ve "öbür koşular aynı" testlerinin adları; onarım denemesinin `usage["model_calls"]`'a yazılıp yazılmadığı; `_topic_terms` taşıması yapıldıysa; yazıldığı gibi yapılamayan her şey ve her sapma; yapılmayanlar ve "ölçülmedi" kalanlar; dokunulan kanıt sınırları (beklenen: **kod ilk kez bir işi kullanıcı onayı olmadan `included` yapıyor** — yalnızca iki koşu anlaşıp her parçanın alıntısı sayfada birebir bulunduğunda; kod, seçilmiş pasajlara dayanarak işi `excluded` yapabiliyor; `sw` yanıtı artık elle dahil etmeyi beklemiyor); canlı servise ve ürün veritabanına dokunulmadığı; commit özeti.

## Açık noktalar

- **Sahip görmeli:** bu dilimden sonra `sw` yanıtının dayandığı işleri kod seçer. Yanlış `include`'un tek freni birebir alıntı ve iki koşudur; ikisi de etiketin doğruluğunu göstermez. Dilim 13 ilk gerçek koşudur; dilim 24'e kadar doğruluk **ölçülmemiş** kalır.
- **Seçilmiş pasajlarla "yok" demek:** yöntem dosyası modeli `unclear`'a yönlendiriyor, ama kaç `criterion_absent`'in aslında gösterilmeyen sayfada olduğu bilinmiyor. `whole_text` sayısı özet adımında tutulur ki dilim 24 ikisini ayırabilsin.
- **Kuyruk boş ekran:** `human_queue`'ya giden beş neden artık satır üretiyor, onları gösteren ekran dilim 16–18'de.
- **Süre:** `detailed` eforda 300 çağrı, tek işçide, öbür koşuları bekletir. Ölçülmedi.
- **Sürüm:** kullanıcının sonradan eklediği yayımlanmış sürümün ön baskı kararının önüne geçmesi (SW11.9) kurulmadı; yeni sürümün kararı `work_outcome`'ın `versions_disagree` kuralına düşer.
