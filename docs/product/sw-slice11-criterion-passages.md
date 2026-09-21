# SW dilim 11 — Ölçüt pasajları: uygulama planı

**Tarih:** 21 Eylül 2026. **Durum:** yazıldı, uygulanmadı. **Ana dosya:** [sw-status.md](sw-status.md). **Ana plan:** [sw-implementation-plan.md](sw-implementation-plan.md) (§2 kuralları geçerlidir). **Spec:** [search-workflow-review-2026-09-18.md](search-workflow-review-2026-09-18.md): **SW12** madde 1–3 ve 5 (madde 4'ün yalnızca sıra işlevi; tüketicileri dilim 12 / 16), **SW15** madde 4 (yalnızca "ölçüt pasajları" yarısı) ve 21 Eylül eki. **Önkoşul:** 06 (kapandı); ifadelerin onayı 08a / 08b (kapandı). **Tür:** Kur. **İnceleme:** toplu.

**Sahibin kararları (21 Eylül 2026, plan sohbeti):**

1. **Bu dilim ölçmez.** Ana plandaki girdi "iki kotanın 48 pasajlık çok kaynaklı girdideki etkisini dilim ölçer" diyordu; §2 kural 7 geçerlidir, ölçüm dilim 24'tedir. Etki **ölçülmedi** diye yazılır; elle seçilen her sayı adlı sabitte ve protokolün `thresholds` alanında durur. Ana plandaki cümle bu plan sohbetinde düzeltildi.
2. **Tek sıra işlevi kurulur ve bugün var olan tek tüketiciye bağlanır:** `sw` yanıt koşusunun pasaj seçimi (`flow._retrieve`). SW12.4'ün öbür üç tüketicisi bugün kodda yok: tam metin modelinin okuyacağı pasajlar dilim 12'de, kuyruktaki "hayır" satırlarının ipucu cümleleri dilim 16'da aynı işlevi çağırır; Marker'a gidecek sayfaların seçimi tüketicisi gelene kadar **kurulmaz** (bugün Marker bütün PDF'i okur). İpucu cümlesi çıkaran ya da sayfa seçen yardımcı bu dilimde yazılmaz.

**Goal:** Bugün yanıt girdisinde "ölçüt pasajı"na ayrılan yer, tek konu için elle yazılmış `FORMULATION_TERMS` listesiyle doldurulur. `sw` araştırmasında bu yer artık o araştırmanın protokolünde **onaylanmış ipucu ifadeleriyle** dolar: (1) kod ifadeleri düz (literal) desenlere derler; (2) her pasaj "kaç ayrı ifade geçiyor, toplam kaç kez" çiftiyle puanlanır; (3) konu pasajları bugünkü gibi sıralanır (soru + dağarcık sözcükleri, isteğe bağlı gömme, RRF), ölçüt pasajları ayrı bir kotadan ifade puanıyla girer ve her kaynak iki listeden de pasaj verir; (4) ifade yoksa ölçüt kotası konu sırasına düşer. Sıra yalnızca sıralar: hiçbir karar, seçim ya da `stage_decisions` satırı yazılmaz, hiçbir pasaj silinmez. `legacy` akış olduğu gibi kalır.

**Architecture:** yeni saf modül `workflow/criterion_passages.py` (derleme, puan, sıra). `flow._retrieve` `sw` araştırmasında ayrı bir dala girer; `legacy` dalı **bayt bayt** bugünkü koddur (`FORMULATION_TERMS`, `formulation_score`, `FORMULATION_SCORE_THRESHOLD` yerinde kalır, dilim 24'e kadar). `sw` yanıt koşusu bir kod adımı kazanır: `code:criterion_phrases` (anahtar `criterion_phrases`), ifadelerin nereden geldiğini ve hangilerinin derlendiğini saklar. Model çağrısı yok, sözleşme ve yöntem paketi değişmez, **migration yok**.

**Tech stack:** Python 3.12. `skill_package_hash` **değişmez**. `apps/web`'de yalnızca Task 5 (tek adım etiketi).

## Global constraints

- `legacy` araştırmanın yanıt koşusu ve `_retrieve`'in `legacy` dalı **bayt bayt** aynı kalır; yeni adım `legacy` koşuda açılmaz. Tablo koşusunun pasaj seçimi (`_cell_passages`) değişmez.
- **Sıra karar vermez** (SW15.4, §2 kural 3–4): bu dilim hiçbir `stage_decisions` satırı, seçim ya da gerekçe kodu yazmaz; ifade puanı sıfır olan pasaj silinmez, yalnızca ölçüt listesine girmez. Alıntı doğrulaması sayfa metninde koşmaya devam eder (`contracts`'a dokunulmaz).
- **Ders A (dilim 10 incelemesi): koşular arasında kalan satırlar koşunun değil araştırmanın geçmişidir.** `protocol_records` satırları bütün koşulardan ve kapsam revizyonlarından kalır. İfadeleri okumanın tek yolu `store.frozen_criterion(rid, question, steering)`'dir (var, salt SQL okuması): aynı soru ve yönlendirme için ölçütü dolu **en yeni** protokol satırı. Eskimiş ve yanıtsız satırın ne olacağı, adıyla:
  - soru ya da yönlendirme değişmişse eski satır eşleşmez → ifade yok → konu sırası; eski sorunun ifadeleri hiçbir zaman kullanılmaz;
  - protokol hiç yoksa (keşif koşmadan yanıt; yalnızca eklenen PDF'lerle araştırma) ya da ölçütü `null` ise (model yanıt vermedi, ikiden az geçerli öneri) → ifade yok → konu sırası; aynı araştırmada aynı soru için ölçütü dolu daha eski bir satır varsa **o** kullanılır (D78'in keşif koşusunda yaptığının aynısı);
  - onay kartında bekleyen, henüz onaylanmamış öneri **okunmaz**: ifadeler yalnızca `protocol_records`'tan gelir, adım çıktılarından değil;
  - kullanıcının onayladığı **boş** ifade listesi geçerli bir yanıttır → konu sırası, neden `no_phrases`;
  - aynı kapsamda ikinci bir keşif koşusu ölçütü değiştirdiyse sonraki yanıt koşusu yenisini okur; önceki yanıt geçersiz sayılmaz (sıra kanıt değildir).
- **`criterion_phrases` adımı koşunundur ve dondurulur:** adım `succeeded` ise sürdürülen koşu ifadeleri saklı çıktıdan okur, protokolü yeniden okumaz (dilim 07 / 09 / 10'un "plan dondurulur" dersi). Başka bir yanıt koşusu kendi adımını açar ve protokolü yeniden okur; önceki koşunun adımına **bakılmaz**.
- **Ders B: kayıtlar araştırmalar arasında ortaktır.** Pasajlar, parçaları ve gömmeleri bütün araştırmaların ortak satırlarıdır; ifadeler ise araştırmaya özgüdür. İfade puanı **hiçbir tabloya yazılmaz**, pasaj satırına ya da pasaj kimliğiyle anahtarlanan bir yere konmaz; her `_retrieve` çağrısında bellekte hesaplanır (saklı metnin ve saklı ifadelerin saf işlevidir, dilim 24 yeniden türetebilir). İfade araması kütüphane genelinde FTS ile yapılmaz: yalnızca bu araştırmanın dahil edilmiş işlerinin, `_retrieve`'in zaten yüklediği pasajları (`passages_for`) puanlanır. Bu dilim ortak satır açmaz; açması gerekirse dur ve bildir (üyelik ayrıca sağlanmak zorunda olurdu).
- **Geriye örtüşme kurulmaz** (SW12.2 "ucuzsa" diyor; ucuz değil): parçalama değişirse bütün araştırmaların (`legacy` dâhil) ortak pasajları yeniden kesilir, pasaj kimlikleri değişir; o kimlikleri kanıt bağlantıları, tablo hücreleri ve saklı gömmeler taşır. Ölçülen kazanç: 205 alıntının 12'si sınırda bölünüyor, sıralama iyileşmiyor, alıntı doğrulaması zaten sayfa metninde koşuyor. `CHUNK_CHARS = 1400` ve `chunk_page` aynı kalır.
- **Ders C: `store.step` okurken adım açar; salt okuma için kullanılmaz.** `criterion_phrases` adımını yalnızca onu yürüten `_answer` yolu `store.step` ile alır. Başka her okuma (görünüm, test yardımcısı, sonraki dilimler) adımı açmayan yoldan yapılır (`latest_step_output` ya da `_other_copy_step` kalıbı). `legacy` koşuda ve `_inspect` / `pdf_collection` yolunda adım hiç açılmaz; sınaması Task 3'te.
- **Ders D: bütçe.** Bu dilim **model çağrısı ve yeni çağrı payı eklemez**; `max_model_calls`, `max_answer_passages` ve gömme adımı (`semantic_retrieval`) aynı kalır, yeni adım bütçeden hiçbir şey harcamaz. Ölçüt pasajları gömmeyle bulunmaz (SW12.5). Uygulayan bir model çağrısı ya da çağrı payı eklemek zorunda kalırsa durur ve bildirir (bütçe koşunun toplamına bakar, başlatılan her çağrı başarısız olsa da sayılır; yinelemenin kimin payından ödendiği yazılmadan pay eklenmez).
- Desenler **yalnızca** `re.escape` ile kurulur; modelin ya da kullanıcının yazdığı metin hiçbir zaman düzenli ifade olarak derlenmez.
- Elle seçilen sayılar adlı sabittir ve `sw` protokolünün `thresholds.criterion_passages` alanına yazılır. Ürün koduna konuya özgü sözcük girmez; fikstürler SYNTHETIC ve en az iki alandan.
- Testlerde ağ yok. Canlı model çağrısı, kuru çalıştırma, süre ölçümü **yok**.
- Başlamadan kontrol et: son karar `D83`, son migration `0045`. Bu dilim `D84` alır, migration almaz.

## Dosya yapısı

Yeni: `backend/deixis/workflow/criterion_passages.py`, `tests/test_criterion_passages.py` (saf), `tests/test_criterion_passage_flow.py` (`create_app` ile).

Değişecek: `workflow/flow.py` (`_answer`, `_retrieve`), `workflow/store.py` (`STEP_OUTPUT_KINDS`), `workflow/protocol.py`, `tests/determinism_stages.py`, `apps/web/src/labels.ts`, `i18n.ts`, `Transcript.tsx`, `docs/decisions.md`, SW belgesi (SW12 ve SW15 durum satırları), `sw-status.md`.

## Task 1: derleme ve puan (saf)

`criterion_passages.py`:

- `THRESHOLDS = {"min_phrase_chars": 3, "criterion_room_divisor": 4, "criterion_pages_per_source": 1}` ve aynı adlarla sabitler.
- `compile_phrases(cue_phrases) -> {"patterns": [(phrase, Pattern)], "dropped": [{"phrase", "reason"}]}`. Girdi protokoldeki liste (`{"phrase", "part", "runs"}`). Her ifade `criterion.norm` ile yazılır (ikinci bir normalleştirici yok); `min_phrase_chars`'tan kısa olan `too_short`, yinelenen `duplicate` ile düşer. Desen, ölçümde kullanılan biçimdir (`.local/generalized-criterion-2026-09-20/run.py::pat`): `(?<!\w)` + sözcükler `re.escape` ile, aralarında `\s+` + `s?(?!\w)`, `re.IGNORECASE`. Sıra ifadenin kendisine göre (alfabetik), böylece iki hash tohumunda aynı.
- `score(text, patterns) -> (distinct, total)`: metin `unicodedata.normalize("NFKC", …)` ile okunur (OCR metninde kalan bitişik harfler için; PyMuPDF metni zaten ayrık); `distinct` en az bir kez geçen ifade sayısı, `total` bütün geçişlerin toplamı. Ölçülen sıralayıcının puanıdır; sembol sayımı (`FORMULATION_SYMBOLS`) **yok** — SW12'nin elle yazılmış sıralayıcısı sayıyordu, SW15'in ölçtüğü ifade sıralayıcısı saymıyordu ve işaretler konuya özgüdür.
- `criterion_order(passages, patterns) -> [pasaj]`: `distinct > 0` olan pasajlar, `(-distinct, -total, physical_page ya da ∞, id)` sırasıyla. Çağıran hangi pasajları verdiğine kendi karar verir (yanıt: bir kaynağın `pdf_page` pasajları; dilim 12: bir işin pasajları). Eşik yok: tek ifade geçen pasaj da listeye girer, sonda. **Ölçülmedi:** her makalede geçen ifadelerin ("we propose" türü; SW15 eki) sırayı ne kadar bulandırdığı.

- [ ] **Tests first** (`tests/test_criterion_passages.py`): çok sözcüklü ifade satır sonuyla bölünmüşken bulunur; çoğul `s` bulunur, sözcüğün içinde geçen bulunmaz; büyük / küçük harf; düzenli ifade imi taşıyan ifade (`s.t.`, `c++`, `(a|b)`) düz metin olarak aranır ve derleme hata vermez; kısa ve yinelenen ifade nedeniyle düşer; boş liste boş desen verir; puan çifti ve sıranın her anahtarı; sıfır puanlı pasaj listede yok; iki alandan SYNTHETIC pasajlarla sıra iki hash tohumunda aynı.

## Task 2: ifadeler ve koşunun kaydı

`flow._criterion_phrases(run, scope) -> list[(phrase, Pattern)]`, yalnızca `scope.get("search_workflow") == "sw"` iken `_answer`'dan çağrılır (`_inspect` ve `_read_equations`'tan sonra, `_retrieve`'den önce).

- Adım: `store.step(run_id, "criterion_phrases", "code:criterion_phrases")`. `succeeded` ise saklı çıktının `phrases` listesi yeniden derlenir ve döner (protokol okunmaz). Değilse `store.frozen_criterion(rid, scope["question"], scope.get("steering"))` okunur, `compile_phrases` koşar, adım kapanır.
- Çıktı: `{"source": "protocol" | "none", "reason": null | "no_criterion" | "no_phrases", "protocol_revision": n | null, "phrases": [yazıldığı gibi, sıralı], "dropped": […]}`. `no_criterion`: eşleşen protokol satırı yok ya da ölçütü `null`. `no_phrases`: ölçüt var, derlenen ifade yok (boş liste ya da hepsi düştü).
- Adım başarısız olamaz: okuma ve derleme ağ ya da model içermez; beklenmeyen istisna koşunun bugünkü hata yolundan geçer.
- `store.STEP_OUTPUT_KINDS`'e `code:criterion_phrases` eklenir (koşu görünümü çıktıyı taşısın). Yeni uç nokta ve `views.py`'de yeni alan yok.

- [ ] **Tests first** (`tests/test_criterion_passage_flow.py`): Ders A'nın beş durumu, her biri adıyla — soru revize edilince eski ifadeler kullanılmaz; ölçütü `null` protokolün ardında aynı sorunun dolu protokolü varsa o kullanılır; onay bekleyen öneri okunmaz; onaylanmış boş liste `no_phrases`; ikinci keşif koşusunun değiştirdiği ölçüt sonraki yanıt koşusunda okunur. Ayrıca: adımdan sonra duraklatılıp sürdürülen koşu saklı ifadeleri kullanır, araya giren yeni protokol onu değiştirmez ve adım iki kez açılmaz; ikinci bir yanıt koşusu kendi adımını açar; `legacy` yanıt koşusu, `pdf_collection` ve `fulltext_fetch` koşuları bu adımı **açmaz** ve koşu görünümünü okumak hiçbir koşuda `pending` bir `criterion_phrases` adımı bırakmaz (Ders C).

## Task 3: iki kota (`_retrieve`, `sw` dalı)

`_retrieve` yeni bir isteğe bağlı argüman alır: `patterns: list | None = None`. `None` iken (her `legacy` çağrı) işlev **bayt bayt** bugünkü yoldan geçer. `sw` araştırmasında `_answer` her zaman liste verir (boş olabilir) ve şu değişir; gerisi (tek ekli kısa PDF kısayolu, konu terimleri, FTS, RRF, `answer_source_order`, `MAX_PASSAGES_PER_SOURCE`, sınır) aynıdır:

1. **Kalabalık durum** (`len(with_text) + PDF_PAGES_PER_SOURCE * len(with_pdf) > limit`, D55): kaynak yine özetini ve `PDF_PAGES_PER_SOURCE` (2) sayfasını verir, ama sayfalar iki listeden gelir: önce konu sırasının en iyi sayfası (bugünkü anahtar: `ranked`'deki yer → kaynağın kendi FTS eşleşmesi → sayfa sırası; üçüncü basamaktaki `formulation_score` düşer), sonra `criterion_order`'ın o kaynaktaki ilk `criterion_pages_per_source` (1) sayfası, zaten seçilmemişse. Ölçüt sayfası olmayan kaynak ikinci sayfasını konu sırasından verir. Kaynak başına pasaj sayısı bugünküyle aynıdır.
2. **Geniş durum:** her kaynak önce ilk pasajını verir (bugünkü gibi). Sonra ölçüt kotası: `limit // criterion_room_divisor` yer (bugünkü `formulation_room` ile aynı sayı), **turlarla** dolar — tur *r*, `order` sırasıyla her kaynağın `criterion_order`'ındaki *r*'inci `pdf_page` pasajını alır; seçilmiş pasaj atlanır, `MAX_PASSAGES_PER_SOURCE` tutulur. Böylece kota tek bir kaynağın sayfalarıyla dolmaz ve ölçüt sayfası olan her kaynak sıraya girer (bugünkü küresel puan sıralaması bunu sağlamıyordu). Kalan yer bugünkü gibi `ranked` ile dolar.
3. **İfade yoksa** (`patterns == []`) ölçüt adımı hiçbir şey eklemez ve bütün yer konu sırasıyla dolar (kabul koşulu). `sw` araştırmasında `FORMULATION_TERMS`'e **düşülmez**: konuya özgü liste `sw` kodunu yönlendirmez (§2 kural 6). Bu, ölçütü olmayan `sw` yanıtında bugünkü formülasyon kotasının kalkması demektir — adıyla davranış değişikliği, yalnızca `sw`.

Puanlama, `_retrieve`'in zaten yüklediği `passages_of` üzerinde çağrı başına bir kez koşar. 300 iş × 50 parçalık SYNTHETIC bir havuzda puanlama olay döngüsünü yaklaşık 1 sn'den uzun tutuyorsa saf puanlama `asyncio.to_thread`'e alınır (depo erişimi olmadan) ve son iletide söylenir; süre testi yazılmaz.

- [ ] **Tests first:** `legacy` araştırmada seçilen pasajlar bu dilimden önceki seçimle aynıdır (mevcut yanıt testleri dokunulmadan geçer + `FORMULATION_TERMS` sözcüğü taşıyan sayfanın `legacy`'de hâlâ yer aldığını gösteren bir test); `sw`'de onaylı ifadeyi taşıyan, soru sözcüklerini taşımayan sayfa girdiye girer; aynı sayfa ifade yokken girmez ve girdi konu sırasıdır; `FORMULATION_TERMS` sözcüğü taşıyan ama onaylı ifade taşımayan sayfa `sw`'de ölçüt kotasından girmez; geniş durumda kota turlarla dolar (iki kaynak, biri çok ölçüt sayfalı: ikisi de temsil edilir) ve `limit // 4`'ü aşmaz; `MAX_PASSAGES_PER_SOURCE` aşılmaz; kalabalık durumda kaynak bir konu + bir ölçüt sayfası verir, ölçüt sayfası yoksa iki konu sayfası; seçilen pasajlar yalnızca dahil edilmiş işlerin okunan sürümlerindendir (başka araştırmanın aynı kütüphanedeki PDF'i girmez); seçim iki hash tohumunda aynı; model adımına giden pasaj sayısı `max_answer_passages`'ı aşmaz ve model oturumu sayısı bu dilimden öncekiyle aynıdır (Ders D).

## Task 4: protokol ve tekrar aşaması

`protocol.py`: `sw` gövdesinde `thresholds.criterion_passages = criterion_passages.THRESHOLDS`; `sw` gövdesinden `formulation_score_threshold` **çıkar** (artık uygulanmayan bir eşiği kayıt diye taşımasın). `legacy` gövdesi bayt bayt aynı. `tests/determinism_stages.py`'ye `criterion_passages` aşaması: sabit SYNTHETIC pasaj havuzu (iki alan) + ifadeler → derlenen ifadeler, puanlar ve sıra tek özet; iki hash tohumu.

## Task 5: arayüz (en az)

Önce [.impeccable.md](../../.impeccable.md). `labels.ts` + `i18n.ts` (EN + TR): adım "Criterion phrases (code)" / "Ölçüt ifadeleri (kod)". `Transcript.tsx`: `code:criterion_phrases` → yanıtın fazı (`phaseOf`'ta `grounded_answer`'ın düştüğü faz); plan cümlesi değişmez. İfadelerin, düşenlerin ve "ifade yok" nedeninin ekranı bu dilimde **yok** (dilim 18 / 20). Yeni Playwright senaryosu yok; A–H geçer.

## Task 6: dilimi kapat

- [ ] `PYTHONPATH=backend:. uv run pytest` tamamı (bilinen tek başarısızlık aynı). `cd apps/web && npm run build && npm run lint`, sonra Playwright A–H. `git diff --check`. Canlı çağrı, kuru çalıştırma **yok**.
- [ ] `docs/decisions.md` en üste `## D84 — In an sw research, fill the answer input's criterion quota from the approved cue phrases, in rounds across sources, and fall back to the topic order when there are none`. Limits adıyla söylemeli: yalnızca `sw`; `legacy` hâlâ elle yazılmış listeyi kullanır (dilim 24'e kadar); **iki kotanın çok kaynaklı 48 pasajlık girdideki etkisi, kota payı (`limit // 4`), kalabalık durumda 1 + 1 bölüşümü ve eşiksiz liste ölçülmedi** (dilim 24); eldeki tek sayı tek konudan ve tek makale içinden: dilim 06'nın istemiyle üretilen ifadeler doğrulanmış alıntıyı 53 makalenin 37'sinde ilk 6 parçaya koydu (elle liste 49, BM25 + gömme 20), hedef alıntılar ipucuyla seçilmiş pasajlardan geldiği için döngüsellik notu geçerli; yanlış ya da eksik ifade listesinin bedeli ölçüt pasajlarının şansa yakın konu sırasına düşmesidir; sembol sayımı yok; geriye örtüşme kurulmadı (ortak pasajların yeniden kesilmesi gerekirdi); ifade puanı saklanmaz; SW12.4'ün üç tüketicisi (tam metin okuması, kuyruk ipuçları, Marker sayfaları) kurulmadı, ilk ikisi aynı işlevi çağıracak; tablo hücrelerinin pasaj seçimi değişmedi; ölçütü olmayan `sw` yanıtı formülasyon kotasını yitirdi.
- [ ] SW belgesinde SW12 ve SW15 **Status** satırlarına birer cümle. `sw-status.md` satır 11: `uygulandı, inceleme bekliyor` + açık kalanlar. Tek commit, `git push origin main`.

## Güncellenecek mevcut testler (adıyla izinli)

- `test_only_an_sw_protocol_carries_the_record_identity_thresholds`: `sw` gövdesi `thresholds.criterion_passages` kazanır ve `formulation_score_threshold`'u yitirir (`legacy` beklentisi aynı).
- Bir **`sw`** yanıt koşusunun adımlarını tam liste olarak sayan test varsa, listeye `code:criterion_phrases` eklenir; başka beklenti değişmez. `legacy` koşunun adım listesi değişirse değişiklik yanlıştır.
- Bunların dışında bir mevcut test kırılırsa (özellikle bir `sw` yanıt testinin pasaj beklentisi) dur ve bildir.

## Son ileti

Eklenen ve değişen dosyalar; temel ve son test sayıları, komut, Playwright sonucu; `skill_package_hash` önce / sonra (beklenen: aynı); "`legacy` seçimi aynı", "ifade yoksa konu sırası", "eski sorunun ifadeleri kullanılmaz", "sürdürülen koşu saklı ifadeleri kullanır", "okuma adım açmaz" ve "model oturumu sayısı aynı" testlerinin adları; puanlamanın olay döngüsünde mi `to_thread`'de mi koştuğu; yazıldığı gibi yapılamayan her şey ve her sapma; yapılmayanlar ve "ölçülmedi" diye kalan her şey; dokunulan kanıt sınırları (beklenen: `sw` yanıtında modelin gördüğü pasajların bir bölümü artık modelin önerip kullanıcının onayladığı ifadelerle seçiliyor — seçim sıralar, karar vermez; ölçütü olmayan `sw` yanıtı formülasyon kotasını yitiriyor); canlı servise ve ürün veritabanına dokunulmadığı; commit özeti.

## Açık noktalar

- **Sahip görmeli:** ifadeleri model önerdi, kullanıcı onayladı; bu dilimden sonra `sw` yanıtının gördüğü pasajların dörtte birine kadarı o ifadelerle seçilir. Kötü bir ifade listesi yanıtı sessizce zayıflatır (pasaj silinmez ama yer sınırlıdır) ve bunu gösteren ekran yok (dilim 18 / 20).
- **Dilim 12'ye not:** tam metin modelinin okuyacağı pasajlar `criterion_order`'ı iş başına çağırır; ifadeleri aynı `frozen_criterion` yolundan ve kendi koşusunda dondurarak okumalıdır (Ders A). İfade yoksa ne okuyacağı dilim 12'nin kararıdır.
- **Her makalede geçen ifadeler:** SW15 eki, 2 / 3 oyunu en kolay kazananların her makalede geçen ifadeler olduğunu söylüyor. Eşik ya da ters belge sıklığı ağırlığı bu dilimde yok; ölçülmeden eklenmez (dilim 24).
- **Türkçe ve başka diller:** desen `s?` ile yalnızca İngilizce çoğulu yakalar; ekli dillerde ifade yalnızca yazıldığı biçimde bulunur. Ölçülmedi.
- **Tablo hücreleri:** `_cell_passages` sütun adı ve talimatıyla sıralar; ölçüt ifadeleri oraya girmez. İstenirse ayrı karar.
