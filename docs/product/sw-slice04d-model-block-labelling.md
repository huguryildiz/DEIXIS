# SW dilim 04d — Blok atamasını modele sordur, kararı kodda tut: uygulama planı

**Tarih:** 21 Eylül 2026. **Durum:** yazıldı, uygulanmadı. **Ana dosya:** [sw-status.md](sw-status.md). **Ana plan:** [sw-implementation-plan.md](sw-implementation-plan.md) (§2 kuralları geçerlidir). **Spec:** [search-workflow-review-2026-09-18.md](search-workflow-review-2026-09-18.md): **SW17** (tümü), SW2 madde 2 ve 6, SW1 madde 3. **Önkoşul:** dilim 04a (D73) kapandı. **Tür:** Kur. Ölçüldü: `.local/sw-block-labelling-2026-09-21/` (8 soru, 28 ifade, kural 19/28, model 28/28, üç koşuda tam kararlı). **İnceleme:** tam — yanlış blok ataması hiçbir hata vermeden sorguyu ve dolayısıyla bulunan kanıtı değiştirir.

**Goal:** Dilim 04a ifadeleri sorudan kodla çıkarıyor, ama hangi ifadenin hangi bloğa gireceğine ifadeden önceki edata bakarak karar veriyor. Bu kural ölçümde 28 ifadenin 9'unda yanıldı ve pahalı yönde yanıldı: `with` yöntem işareti olduğu için "in patients with type 2 diabetes" cümlesinde `type 2 diabetes` iddia sayılıp sorgudan düşüyor. SW17, çıkarmayı kodda bırakıp yalnızca **etiketlemeyi** modele verir: model listeye ifade ekleyemez, ifadeyi bölemez, değiştiremez, atlayamaz. Bu dilim o adımı kurar. Model kapalıyken akış kuralın atamasıyla arar; ilk aramanın modele bağımlı hâle gelmesi kabul edilmez.

**Architecture:** `domain/vocabulary.py::extract` değişmez. `flow._discovery`'nin `sw` dalında, `extract` ile `build_vocabulary` arasına yeni bir model adımı girer: `vocabulary_labels`, üç kez (`vocabulary_labels_1..3`), hepsi `optional=True`. Adım girdisi soruyu ve çıkarılan ifade listesini taşır (`vocabulary_target`), izin listesi ifadelerin kendisidir. `workflow/vocabulary.py::apply_labels` üç koşuyu birleştirir (2/3 çoğunluk), `Extraction`'ı yeniden kurar ve `block_assignment`'ı `"model"` yapar. Sonrası aynen 04a'daki gibi: `build_vocabulary` sayım sınamasını koşar, `compile_block_queries` sorguyu derler. Kural, modelin ulaşılamadığı ya da çoğunluğun oluşmadığı her yerde yerinde durur.

**Tech stack:** Python 3.12. Yeni bağımlılık yok. Yeni sözleşme şeması ve yeni bir yöntem paketi dosyası var; bu yüzden `skill_package_hash` **değişir**.

## Global constraints

- `apps/web/` ve mevcut migration dosyalarına dokunma. Bu dilim şema değişikliği istemiyor: her şey adım çıktısında ve protokol gövdesinde durur.
- `legacy` araştırmanın davranışı değişmez: `vocabulary_labels` adımı yalnızca `sw` dalında açılır, `legacy` `search_plan` adımını koşmaya devam eder.
- **Dilim 04a'nın kabul koşulu korunur ve bu dilimin en önemli testidir:** model bağlantısı her çağrıda hata verirken `sw` keşif koşusu yine arar. 04a'daki "sw keşif koşusunda hiçbir model çağrısı yoktur" kuralı burada "hiçbir **zorunlu** model çağrısı yoktur"a daralır; `optional=True` ve kurala düşüş bunu sağlar.
- Model ifade uyduramaz: izin listesi dışındaki ifadeyi adlandıran çıktı **reddedilir, onarılmaz** (şema onarımı bu adımda kapalıdır).
- Ürün koduna konuya özgü sözcük girmez; bu kural yöntem paketindeki yeni dosya için de geçerlidir. Örnekler alan-bağımsız olmalı ve `.local/sw-block-labelling-2026-09-21/questions.json`'daki sorular **örnek olarak yazılmamalıdır** (o set ölçüm setidir; prompta girerse ölçüm kirlenir).
- Testlerde ağ yok; model `tests/fakes.py::FakeAdapter` ile sürülür.
- Karar numarası bu not yazılırken `D73`, son migration `0040`'tır; başlamadan önce kontrol et.

## Dosya yapısı

Yeni: `contracts/research/vocabulary-labels.schema.json`, `methods/deixis-research/references/vocabulary-labels.md`, `tests/test_vocabulary_labels.py`.

Değişecek: `contracts/research/step-input.schema.json` (`task_type` enum, `vocabulary_target`, `allowlist.phrases`), `backend/deixis/domain/contracts.py` (anlam denetimleri), `backend/deixis/domain/skill.py` (`RUNTIME_FILES`), `backend/deixis/domain/rules.py` (`LITERATURE_TASKS`), `backend/deixis/workflow/flow.py` (`_step_input` ve `_discovery`'nin `sw` dalı), `backend/deixis/workflow/vocabulary.py` (`apply_labels`), `backend/deixis/workflow/protocol.py` (`block_origin`), `methods/deixis-research/SKILL.md` (yeni dosyaya bağlantı) ve `provenance.json` gerekiyorsa, `tests/fixtures/research/step-inputs.json`, `tests/fixtures/research/fake-outputs.json`, `tests/fakes.py::valid_response`, `tests/determinism_stages.py`, `tests/test_vocabulary_flow.py`, `docs/decisions.md`, SW belgesi (SW17 durum satırı), `docs/product/sw-status.md`.

## Task 1: sözleşme

`contracts/research/vocabulary-labels.schema.json`, `schema_version = "deixis.vocabulary_labels.v1"`. Diğer adımlarla aynı dört zorunlu alan (`step_input_id`, `scope_revision`, `skill_package_hash`, `schema_version`) artı:

```json
{"labels": [{"phrase": "…", "block": "setting|task|outcome|claim|exclusion|not_a_term"}]}
```

`labels` zorunlu, `additionalProperties: false`, `maxItems` izin listesinin üst sınırıyla aynı (40). Gerekçe alanı **yoktur**: adım tek bir sınıflandırma yapar, serbest metin istemek çıktıyı uzatır ve denetlenmez.

`step-input.schema.json`: `task_type` enum'una `vocabulary_labels`; `extraction_target` kalıbında isteğe bağlı `vocabulary_target` (`question_text`, `language`, `phrases: [{"phrase": …, "rule_block": …}]`); `allowlist`'e isteğe bağlı `phrases` (dizgi dizisi).

`domain/contracts.py`: `step_output_schema("vocabulary_labels")` katı şemayı üretir; `validate_model_output` bu görev için iki anlam denetimi ekler — (1) her `phrase` izin listesinde olmalı (değilse `phrase_not_in_allowlist`, **hata**), (2) izin listesindeki her ifade tam bir kez etiketlenmiş olmalı (eksik ya da yinelenen → `phrase_label_incomplete`, **hata**). İkisi de uyarı değil hatadır: eksik etiket sessizce kuralın atamasını bırakır ve bunu görmek isteriz.

- [ ] **Tests first:** izin listesi dışı ifade reddedilir; eksik ifade reddedilir; yinelenen ifade reddedilir; geçerli çıktı geçer; `tests/fakes.py::valid_response` yeni görev türünü üretir; `step-inputs.json` ve `fake-outputs.json` fixture'ları eklenir.

## Task 2: yöntem paketi

`methods/deixis-research/references/vocabulary-labels.md`: adımın tek işi. İçeriği (İngilizce, paketin üslubuyla): verilen ifade listesinden çıkma; ifade ekleme, bölme, yeniden yazma, atlama yok; altı etiketin tanımı; ve üç zor durum kuralı —

- Bir ifadenin önündeki sözcük bloğunu belirlemez; ifadenin anlamı belirler.
- `claim` yalnızca soru, yazında **o belirli yöntemin ya da savın** kullanılıp kullanılmadığını soruyorsa kullanılır. Yalnızca ortamı daraltmak için anılan bir yöntem `setting`'dir.
- İki kavramı birleştiren ifade, baştaki kavramın bloğunu alır.

`domain/skill.py::RUNTIME_FILES`'a `"vocabulary_labels": ("SKILL.md", "references/vocabulary-labels.md")`. `SKILL.md`'de yeni dosyaya göreli bağlantı (bütünlük denetimi bağlantının çözülmesini ister). `skill_package_hash` değişir; bu beklenen ve kaydedilecek bir sonuçtur.

- [ ] **Tests first:** paket bütünlük denetimi geçer; `RUNTIME_FILES["vocabulary_labels"]` dosyaları yüklenir; `package_hash` eski değerden farklıdır ve testlerde sabit beklenen bir hash varsa güncellenir.

## Task 3: `apply_labels`

`workflow/vocabulary.py`:

```python
LABEL_RUNS = 3          # SW17.3: a label is kept when it appears in at least two runs
LABEL_MAJORITY = 2
MAX_LABELLED_PHRASES = 40

def apply_labels(extraction: Extraction, runs: list[dict[str, str]]) -> tuple[Extraction, list[dict[str, Any]]]: ...
```

- Girdi: kuralın `Extraction`'ı ve her koşunun `{ifade: etiket}` sözlüğü. Başarısız koşu listeye hiç girmez.
- Her ifade için etiketler sayılır. En az `LABEL_MAJORITY` kez çıkan etiket kazanır. Beraberlik ya da çoğunluk yoksa ifade **kuralın** etiketini korur ve sorguya girmez (SW17.3).
- Etiket → konum: `setting`/`task`/`outcome` bloklara; `claim` → `claim_words`; `exclusion` → `exclusion_words`; `not_a_term` → hiçbir yere (ifade tamamen düşer).
- Sonuç `Extraction`'ın `block_assignment`'ı: hiç koşu yoksa `"rule"`, en az bir koşu varsa `"model"`. (Kullanıcı `key_terms` verdiyse bu adım hiç koşmaz, `"user"` kalır; SW2.6.)
- İkinci dönen değer ifade başına kayıttır: `{"phrase", "rule_block", "runs": [...], "block", "origin": "model"|"rule"}`; adım çıktısına ve protokole girer.
- Sıra sorudaki sıradır; hiçbir yerde küme yinelemesi sonucu belirlemez.

- [ ] **Tests first:** 3/3 aynı etiket uygulanır; 2/3 uygulanır; 1/1/1 kuralı korur ve ifade sorguya girmez; iki koşu başarısızsa tek koşunun etiketi çoğunluk sayılmaz ve kural kalır; `not_a_term` ifadeyi düşürür; `claim` sorgudan çıkarır; kuralın `method` dediği ifade model `setting` derse **sorguya girer** (SW17.4, denemenin gerekçesi); `key_terms` yolunda `apply_labels` çağrılmaz.

## Task 4: akışa bağlama

`flow._discovery`, `sw` dalı, `extract` ile `build_vocabulary` arasında:

- `extraction.block_assignment == "user"` ise (kullanıcının `key_terms`'i) etiketleme adımı **atlanır**.
- İfade sayısı `MAX_LABELLED_PHRASES`'i aşarsa adım atlanır (`labelling_skipped: "too_many_phrases"`); kural kalır.
- Aksi hâlde `for run_index in range(LABEL_RUNS)`: `self._model_step(run, scope, f"vocabulary_labels_{run_index + 1}", "vocabulary_labels", optional=True, vocabulary_target=…)`. `OptionalStepFailed` yakalanır, sayılır, koşu durmaz. `_checkpoint` üç çağrının arasında da işler: duraklatma ve iptal beklemez.
- Adım `succeeded` ise saklı çıktı kullanılır; sürdürülen koşu modeli yeniden çağırmaz (bu dilimin tekrarlanan-çağrı sorusu).
- Üç koşunun hepsi başarısızsa kural atamasıyla devam edilir ve `vocabulary` adım çıktısına `labelling: {"runs_ok": 0, "reason": …}` yazılır. Koşu **duraklamaz**.
- Bütçe: üç çağrı `max_model_calls` sayacına girer. Bütçe dolduysa `_model_step` zaten `budget_exhausted` ile `OptionalStepFailed` atar; akış kurala düşer. Bütçenin bu adım yüzünden tarama adımlarını aç bırakmaması dilim 09'un (K3) işidir; burada yalnızca not edilir.
- `vocabulary` kod adımının çıktısına `block_assignment`, `labelling` (koşu sayısı, başarısızlık nedenleri) ve ifade başına kayıt eklenir. Adım çıktısı kanonik sıralı kalır.
- `protocol.build_protocol`: her terimin `block_origin`'i (`rule` | `model` | `user`) ve `vocabulary.block_assignment` protokol gövdesine girer. Protokole **ilk koşuda** alınan etiketler girer, yeniden sorulmaz.
- Pasaj sıralamasının terim okuyan yeri değişmez (etiketleme yalnızca hangi terimin nereye gittiğini değiştirir).

- [ ] **Tests first** (`tests/test_vocabulary_labels.py`, `create_app` ile): model her çağrıda hata verirken keşif koşusu arar ve kuralın blokları kullanılır (**04a kabul koşulunun korunması**); üç koşu 2/3 anlaşırsa sorgu modelin bloklarını taşır; duraklatılıp sürdürülen koşu modeli yeniden çağırmaz; izin listesi dışı ifade dönen model çıktısı o koşuyu düşürür ve kalan iki koşu kullanılır; `legacy` araştırmada `vocabulary_labels` adımı açılmaz; `key_terms` verilmiş araştırmada adım açılmaz; dondurulan protokolde `block_origin` doludur ve aynı saklı çıktıyla ikinci kez kurulunca aynıdır.

## Task 5: tekrar aşaması

`tests/determinism_stages.py`'deki `vocabulary` aşaması, sabit üç koşuluk bir etiket sözlüğü ve karıştırılmış koşu sırasıyla `apply_labels`'ı da kapsar. İki hash tohumu ve iki karışımda tek özet. Koşuların geliş sırası sonucu değiştirmemelidir.

## Task 6: dilimi kapat

- [ ] Ağsız kuru çalıştırma: `.local/sw-block-labelling-2026-09-21/questions.json`'daki 8 sorunun `extract` + sahte etiket çıktısı değil, **iki konu sorusunun** (kuantum dolanıklık dağıtımı; KAA'da paket boyutu) kural ataması ile — canlı `deepseek-flash` ile yapılmış tek bir etiketleme koşusunun ataması yan yana son iletiye yazılır. Bu ölçüm değildir, ölçüm `.local/sw-block-labelling-2026-09-21/`'de yapıldı ve dilim 24'te yinelenecek. Canlı çağrı yaptıysan söyle; canlı kütüphaneye ve 8765 portuna dokunma.
- [ ] `PYTHONPATH=backend:. uv run pytest` tamamı; bilinen tek başarısızlık `tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`. `git diff --check`.
- [ ] `docs/decisions.md` en üste `## D<NN> — Let a model sort the extracted phrases into concept blocks, bounded to the list code found, and keep the rule as the fall-back`. Limits adıyla söylemeli: yalnızca `sw`; SW17'nin ölçümü 8 soru / 28 ifade, tek model, tek prompt, tek etiketleyici, kuralın çıktısı görüldükten sonra yazılmış beklentiler; gerçek `claim` vakası tek, "iddia sorguya sızar mı" ölçülmedi ve edat vetosu bilerek kaldırıldı; İngilizce olmayan ve bozuk sorular denenmedi; üç koşu araştırma başına üç model çağrısıdır ve tek koşunun yetip yetmeyeceği ölçülmedi; iki kavramı birleştiren ifadeler (çıkarma kusuru) bu dilimde düzelmez; onay ekranı yoktur (dilim 08); `skill_package_hash` değişti.
- [ ] SW belgesinde SW17 **Status** satırına bir cümle; SW2 durum satırına madde 5'in daraldığı notu. `sw-status.md` satır 04d: `uygulandı, inceleme bekliyor` + açık kalanlar.
- [ ] Tek commit, `git push origin main` (ana plan §2.11).

## Son ileti

Değişen ve eklenen dosyalar; temel ve son test sayıları ve komut; eski ve yeni `skill_package_hash`; iki konu sorusunun kural ve model ataması yan yana; model kapalıyken aramanın koştuğunu gösteren testin adı; yazıldığı gibi yapılamayan her şey ve seçilen her sapma; yapılmayanlar; dokunulan kanıt sınırları (beklenen: yok; protokol gövdesi ve yöntem paketi özeti değişir); canlı servise dokunulmadığı; commit özeti.

## Açık noktalar

- **Bilerek yapılmayan:** SW17.4, kuralın yöntem konumunu ikinci bir veto olarak tutmuyor. Öneri aşamasında "kuralın yöntem konumu dediği ifade model ne derse desin sorguya girmez" biçimindeydi; ölçüm o frenin düzeltilen iki vakanın ikisini de geri bozduğunu gösterdi (28/28 yerine 26/28). Kabul edilen risk: gerçek bir yöntem iddiası, model yanılırsa sorguya girebilir. Sette bunun tek örneği vardı ve model altı koşunun altısında doğru dedi; dilim 24 bunu daha çok soruyla sınamalı.
- **Ölçülmedi:** üç koşu yerine tek koşu. Denemede 28 ifadenin 28'i üç koşuda da aynıydı, yani çoğunluk kuralı hiçbir şeyi değiştirmedi. Yine de üç koşu kuruluyor, çünkü kararlılığın başka alanlarda ve başka modellerde de süreceği gösterilmedi. Tek koşuya inme kararı dilim 24'ün ölçümünden sonra verilir ve `LABEL_RUNS` tek sabittir.
- **Sınır:** çıkarma kusuru (`packet size affect energy consumption` gibi iki kavramı kaynatan ifadeler) etiketlemeyle düzelmez. Fiillerin bölme noktası olması `domain/vocabulary.py` değişikliğidir ve bu dilimin dışındadır; gerekirse kendi dilimini ister.
- **Sıra:** bu dilim 04b ve 04c'den bağımsızdır; üçü herhangi bir sırayla koşabilir. 04b'nin veriden gelen terimleri etiketlenmez (onların bloğu geldikleri terimin bloğudur); bunu 04b'nin dosyası yazarken doğrula.
