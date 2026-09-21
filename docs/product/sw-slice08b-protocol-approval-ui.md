# SW dilim 08b — Protokol onayı, arayüz: uygulama planı

**Tarih:** 21 Eylül 2026. **Durum:** yazıldı, uygulanmadı; **08a kapanmadan başlamaz**. **Ana dosya:** [sw-status.md](sw-status.md). **Ana plan:** [sw-implementation-plan.md](sw-implementation-plan.md) (§2 kuralları geçerlidir). **Spec:** [search-workflow-review-2026-09-18.md](search-workflow-review-2026-09-18.md): SW2 madde 1 (alan) ve 6, SW15 madde 3, SW14 madde 2. **Önkoşul:** 08a ([sw-slice08a-protocol-approval-backend.md](sw-slice08a-protocol-approval-backend.md)); görünümün `approval` alanı ve `POST /api/runs/{id}/protocol-approval` oradan gelir. **Tür:** Kur. **İnceleme:** toplu (08a ile). Önce [.impeccable.md](../../.impeccable.md) ve [AGENTS.md](../../AGENTS.md) "Frontend/UX".

**Goal:** 08a'dan sonra `ask` modundaki bir `sw` koşusu onay için durur ama ekranda yalnızca ham bir duraklatma nedeni görünür ve kullanıcı koşuyu sürdüremez. Bu dilim, koşunun zaman çizelgesi öğesinin içinde bir onay kartı kurar: kullanıcı aramanın hangi terimlerle, hangi bloklarla ve hangi ölçütle yapılacağını tek yerde görür, düzeltir ve onaylar. Aynı dilim `sw`'nin ekranı olmayan üç duraklamasına (`key_terms_needed`, `vocabulary_empty`, `vocabulary_too_broad`) metin ve çıkış yolu verir.

**Architecture:** Yeni `apps/web/src/ProtocolApproval.tsx`, `Transcript.tsx`'te koşu öğesinin içinde, `run.approval` doluyken çizilir. Durum yalnızca arka ucun kaydettiğidir: `waiting` (düzenlenebilir kart), `submitted` (salt okunur, "eklediğiniz terimler sınanıyor"), `approved` (katlanmış özet: ne önerildi, ne değişti). Taslak düzeltmeler bileşen durumunda tutulur; sunucuya yalnızca onay düğmesiyle gider. Yeni tasarım dili yok: mevcut belirteçler, `components/ui` (button, select, textarea, tooltip) ve `.chat-note` tonları kullanılır.

**Tech stack:** React 19, Tailwind 4, mevcut bileşenler. Yeni bağımlılık yok. Arka uçta izin verilen tek değişiklik aşağıda adıyla yazılan görünüm alanıdır.

## Global constraints

- **Kaydedilmiş durumu göster** (AGENTS.md): onay bekleyen koşu başarı gibi görünmez; duraklama kehribar (dikkat) tonundadır, faz simgesi "bekliyor" kesik çemberidir. `submitted` iken kart kilitlenir; `approved` yazısı ancak görünüm `approved` dediğinde çıkar. Koşu durumları kümesi değişmez: bu yeni bir koşu durumu değil, yeni bir duraklatma nedenidir.
- Onay bekleyen koşuda düz **Sürdür** düğmesi gösterilmez (arka uç 409 döner); yerine kartın kendi birincil eylemi vardır. Duraklat / iptal olduğu gibi kalır.
- Onay için `ConfirmDialog` açılmaz: kartın kendisi zaten açık bir karardır ve ikinci bir "emin misiniz" sormaz. Taslak düzeltmeler kart açık kaldığı sürece durur; sayfa yenilenirse kaybolur (kabul edildi, aşağıda).
- Bütün metinler `i18n.ts` / `labels.ts` üzerinden, İngilizce ve Türkçe; tonu mevcut duraklatma cümleleri gibi sakin ve olgusal. Alan terimi, sayı abartısı, güven verici tamamlanma dili yok.
- `legacy` araştırmada hiçbir şey değişmez; mevcut Playwright A–G senaryoları değişmeden geçer.
- Görsel iş ara onay istemeden yapılır: değişiklik yapılır, ekran görüntüsüyle (açık ve koyu tema, dar genişlik) **kendin** doğrularsın, son iletide yalnızca bitmiş hâl gösterilir.
- Başlamadan kontrol et: satır 08a `kapandı`; görünümde `approval` alanı var; son karar `D80`.

## Dosya yapısı

Yeni: `apps/web/src/ProtocolApproval.tsx`, `apps/web/e2e/protocol-approval.spec.ts`.

Değişecek: `apps/web/src/api.ts`, `Transcript.tsx`, `ResearchView.tsx` (sürdür düğmesi, revizyon formu), `labels.ts`, `i18n.ts`, `workspace.css` (yalnızca gerekirse, mevcut belirteçlerle), `apps/web/playwright.config.*` (ikinci sunucu), `backend/deixis/workflow/views.py` (yalnızca aşağıdaki alan), `docs/decisions.md` (D80'in Limits satırı), `docs/product/sw-status.md`.

## Task 1: istemci ve metinler

- `api.ts`: `RunApproval`, `ApprovalTerm`, `ApprovalCriterion`, `ProtocolEdits` tipleri (08a'nın görünüm ve rota biçimleri); `approveProtocol(runId, edits)`; 422 yanıtının hata listesi tipli döner. `reviseScope` isteğe bağlı `key_terms` alır (rota zaten kabul ediyor). Dilim 02'nin açığı da burada kapanır: `origin` tipi `code_rule`'u tanır.
- `labels.ts` + `i18n.ts`: `protocol_approval_needed`, `key_terms_needed`, `vocabulary_empty`, `vocabulary_too_broad` için tam cümleler; blok adları (`setting`, `task`, `outcome`, `claim`, `exclusion`) ve köken rozetleri (soru, anahtar terimler, siz; kural, model, siz) için kısa etiketler; `zero_results` gibi düşme nedenleri.

## Task 2: onay kartı

Kartın iki bölümü vardır, ikisi de tek ekranda (SW15.3):

**Arama terimleri.** Blok blok: önce sorguya giren iki blok (`setting`, `task`), sonra `outcome`, sonra "aranmayan" iki yan liste (`claim` — sınanan iddia sorguya girmez; `exclusion`). Her terim bir satır: ifade; sorguya hangi biçimde girdiği (kök ya da öbek, `in_query`); sayımı (yoksa "sayılamadı", asla 0 değil); terimin kökeni ve blok kökeni rozet olarak; `and_only` ise kısa not; düşmüş terim üstü çizili değil, soluk ve nedeniyle. Eylemler: kaldır, başka bloğa taşı (`select`), blok başına "terim ekle" alanı. Eklenen terim sayımsız görünür ve "onaydan sonra sınanacak" der. `too_broad` ya da boş geçit durumunda kartın başında tek cümlelik uyarı ve onay düğmesi yine açıktır (arka uç yeniden durdurur ve nedenini söyler).

**Dahil etme ölçütü.** Ölçüt cümlesi (`textarea`); parçalar (ad, tanım; ekle / kaldır, 2–5); ifadeler parçaya göre gruplanmış, parçasız olanlar ayrı grupta, her biri kaldırılabilir, grup başına ekleme alanı; dışlama başlık sözcükleri. `sought_term_in_criterion === false` ise uyarı: aranan şey ölçütte geçmiyor. `criterion_available === false` ise (model kapalıydı) bölüm boş hâlini söyler ve iki yol sunar: ölçütsüz sürdür, ya da kendin yaz. Ölçüt bu dilimde hiçbir şeyi sıralamadığı ve hiçbir kararı vermediği için kart bunu abartmaz: "tam metin aşamasında kullanılacak" der, fazlasını demez.

**Alt kısım.** İsteğe bağlı not alanı (protokol kaydına girer); değişiklik özeti ("3 terim değişti, ölçüt düzeltildi" ya da "değişiklik yok"); birincil düğme **Onayla ve ara**; ikincil **Değişiklikleri geri al**. 422 hataları ilgili satırın yanında, genel hata kartın altında gösterilir; hata olunca taslak korunur.

`approved` durumunda kart katlanır ve tek satır olur (kim onayladı: siz / ayar / önceki onay; düzeltildi mi); açılınca öneri ile onaylananın farkı salt okunur görünür, `skipped_edits` varsa adlarıyla. Bu, 04a, 04b ve 06'nın "hiçbir ekranda görünmüyor" açıklarını dağarcık ve ölçüt için kapatır; ikinci turun veri terimleri ve verim bu dilimde **gösterilmez** (dilim 20).

Erişilebilirlik: her eylem klavyeyle; taşıma `select` ile (sürükle-bırak yok); rozetler yalnızca renkle ayrılmaz; hata `aria-live` ile duyurulur.

## Task 3: üç duraklamanın çıkış yolu

- `key_terms_needed`: duraklatma notu nedeni söyler ve revizyon formunu açar. `RevisionForm` isteğe bağlı **İngilizce anahtar terimler** alanı kazanır; alan yalnızca `sw` araştırmasında görünür. Yardım metni sözdizimini bir cümleyle verir (bloklar `;`, eş anlamlılar `,`, `claim:` ve `not:` grupları). Görünüm kapsamın `search_workflow`'unu ve `key_terms`'ini taşımıyorsa `views.research_view`'a bu iki alan eklenir: **bu dilimin izinli tek arka uç değişikliği**, testi `tests/` altında bir satırla.
- `vocabulary_empty` / `vocabulary_too_broad`: not nedeni söyler; onay kartı bu durumda yeniden düzenlenebilir açılır (08a yeniden göndermeyi kabul ediyor).
- Yeni araştırma formuna alan **eklenmez**: araştırmanın hangi akışla açılacağını form bilmiyor; İngilizce olmayan soru zaten bu duraklamaya düşer.

## Task 4: Playwright

`apps/web/e2e/protocol-approval.spec.ts`, ayrı bir fikstür sunucusuna karşı (`DEIXIS_SEARCH_WORKFLOW=sw`, `DEIXIS_PROTOCOL_APPROVAL=ask`, ayrı port ve veri klasörü; `playwright.config`'e ikinci `webServer` girdisi ve bu dosyayı ona bağlayan proje). Mevcut sunucu ve A–G koşusu aynı kalır. Senaryo **H**:

1. Soru sorulur, keşif başlar; koşu onay için durur, kart görünür, kaynak listesi boştur ve zaman çizelgesinde arama adımı yoktur.
2. Düz "Sürdür" yoktur.
3. Bir terim kaldırılır, bir terim eklenir, bir terim `claim`'e taşınır, ölçüt cümlesi düzeltilir; özet satırı değişiklikleri sayar.
4. Geçersiz bir ekleme (var olan ifade) satır içi hata verir ve taslak korunur.
5. **Onayla ve ara**: kart kilitlenir, sonra `approved` olur; arama adımları görünür, kaynaklar gelir.
6. Katlanmış özet açılınca önerilen ile onaylanan arasındaki fark görünür.
7. İkinci senaryo: düzeltmesiz onay tek tıkla sürer.

Fikstür SYNTHETIC'tir ve geçen senaryo iş akışı davranışını gösterir. Ekran görüntüleri `DEIXIS_ACCEPTANCE_DIR`'e yazılır: bekleyen kart, hata durumu, onaylanmış özet; açık ve koyu tema, 390 px genişlik.

## Task 5: dilimi kapat

- [ ] `cd apps/web && npm run build && npm run lint`; `DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance npm run test:acceptance` (A–G + H). `PYTHONPATH=backend:. uv run pytest` tamamı (görünüm alanı için); bilinen tek başarısızlık aynı. `git diff --check`.
- [ ] Ekran görüntüleri `Read` ile açılıp bakılır: taşma, kesilen metin, koyu temada okunmayan rozet, dar genişlikte kırılan satır. Bulunan düzeltilir, yeniden bakılır.
- [ ] `docs/decisions.md`'de D80'in Limits bölümünden "ekran yok" cümlesi çıkarılır, yerine ekranın ölçülmeyenleri yazılır: kullanıcıların bu kartı nasıl karşıladığı, blok düzeltmesinin anlaşılırlığı ve 1–2 dakikalık bekleme sınanmadı; taslak sayfa yenilenince kaybolur. Yeni D numarası alınmaz.
- [ ] `sw-status.md` satır 08b: `uygulandı, inceleme bekliyor` + açık kalanlar. Tek commit, `git push origin main`.

## Son ileti

Eklenen ve değişen dosyalar; `npm run build`, `lint`, Playwright (A–G ve H ayrı ayrı) ve pytest sonuçları; bakılan ekran görüntülerinin yolları ve onlarda bulunup düzeltilenler; arka uçta dokunulan tek yer; yazıldığı gibi yapılamayan her şey ve seçilen her sapma; yapılmayanlar; canlı servise ve ürün veritabanına dokunulmadığı; commit özeti.

## Açık noktalar

- **Bekleme:** ölçüt adımı aramadan önce 1–2 dakika sürüyor. Bu dilim beklerken koşunun adımlarını olduğu gibi gösterir (dağarcık, etiketleme, ölçüt); ayrı bir "hazırlanıyor" ekranı kurmaz.
- **Taslağın kalıcılığı:** taslak düzeltmeler yalnızca bileşen durumundadır. Sayfa yenilenince kaybolur; tarayıcı deposu eklenmedi, çünkü taslak kanıt değildir ve ikinci bir doğruluk kaynağı olurdu.
- **Varsayılan akış hâlâ `legacy`:** bu ekranı gören tek kullanıcı `DEIXIS_SEARCH_WORKFLOW=sw` ile açan sahiptir (dilim 24'e kadar).
- **Koşullu model terim önerisi** (SW2.5, "model terim önersin" düğmesi) 08c'dedir; kartta yeri ayrılmaz.
