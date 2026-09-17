# P6 dilim 1 — yürütme devir kaydı

Tarih: 17 Eylül 2026. Bu dosya yeni bir tasarım getirmez; satır düzeyindeki plan
[p6-slice1-report-run.md](p6-slice1-report-run.md)'dedir ve tek doğru kaynak odur. Buradaki iş, o planın
**neresinde olduğumuzu**, hangi sırayla devam edeceğimizi ve nelerin bilerek ertelendiğini kaydetmektir.

Yürütme biçimi: kodu `gpt-5.6-sol` (Codex) yazar, denetleyen oturum planla karşılaştırır, `pytest`'i koşar,
commit'ler ve push'lar. Codex'in kum havuzu `.git/index.lock`'a yazamıyor, bu yüzden commit'i her zaman
denetleyen atar.

## Nerede duruyoruz

`main` üzerinde, `5d6189b`'den sonraki 17 commit dilim 1'e aittir. Uygulanmış olanlar:

| Plan | Ne geldi | Durum |
|---|---|---|
| 1a | Dört sözleşme, `report_target`, yöntem paketi, fake'ler, fixture'lar | Tam |
| 1b | Migration 0035, `ReportStore`, `build_snapshot`, `report_ready` | Tam |
| 1c Task 1–2 | `selection.py`, `plan.py` | Tam |
| 1d Task 1–2 | Phrasebank bölüm süzgeci, `nearest_frames` | Tam |
| 1d Task 3 (yarım) | `flagged_sentences` | `repair_section` ertelendi |
| — | `report_target` tesisatı: `flow._step_input`/`_model_step` + izin listesi anahtarları | Tam (plan dışı, zorunluydu) |
| 1e Task 0 | Migration 0036: `report_sections` artık `'II'` kabul ediyor | Tam (plan dışı, zorunluydu) |
| 1e Task 1 | `review_methodology.py` — II. bölüm, model çağrısı yok | Tam |
| 1e Task 3 | `gaps.py` — `corpus_absence` adayları | Tam |
| 1e Task 4 (yarım) | `assembly.py`, kural 1, 2, 3, 4, 7, 10 | Bu turda |

Tam backend takımı son ölçümde **636 geçti, 1 kaldı**. Kalan test
`tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`; `main` üzerinde bu işle
ilgisiz bir nedenle bozuk ("extraction timed out" diyor) ve bırakılmasına izin verilen tek başarısızlıktır.

**Bu kodun hiçbiri hiç çalışmadı.** Ne sahte modelle ne gerçek modelle bir rapor koşusu yapılmadı. Testler
sentetik veriyle yapısal davranışı gösterir; rapor kalitesi hakkında hiçbir şey söylemez.

## Sıra neden değişti

Planın kendi sırası (1a → 1n) yürütülebilir değil: 1c Task 3'ün `run_report`'u 1d, 1e ve 1f'in işlevlerini
çağırıyor, 1d Task 3 `_model_step`'in `report_target` taşımasını bekliyordu, 1e Task 4 ise rapor hiç koşmadan
14 kuralı denetliyor. Bu yüzden **model çağırmayan saf parçalar önce**, orkestrasyon sonra yazıldı.

Bundan sonraki sıranın tek ölçütü şu: **en kısa yoldan çalışan bir rapora ulaşmak.** Arayüz, dışa aktarma ve
kalan denetimler, çıkan ilk gerçek rapora bakılarak önceliklendirilecek; şu an hangisinin önemli olduğu
tahmin edilerek yazılıyor.

## Partiler

Her parti bir Codex turu. Ön koşulu olmayan partiler sıradan bağımsız yapılabilir.

**P1 — Montaj kuralları, ilk yarı.** `assembly.py`, kural 1, 2, 3, 4, 7, 10. *(Bu turda çalışıyor.)*

**P2 — Orkestrasyon.** 1c Task 3: `report/sections.py::run_report` ve `_run_section`, `flow.py::execute`'a
`report` dalı, `Store.create_run`'ın stage eşlemesine `{"report": "synthesis"}`. 1f'in `run_report_review`'ı ve
1d'nin `repair_section`'ı **hiçbir şey yapmayan çağrı** olarak bırakılır; montaj yalnız P1'in altı kuralını
koşar. Ön koşul: P1.

**P3 — API ve görünüm modelleri.** 1g: `POST /api/researches/{id}/reports`, rapor okuma rotası,
`views.py` rapor görünümü. `ResearchView.tsx`'teki mevcut `reports` değişkeninin ne saydığı önce okunmalı
(planın "Açık noktalar"ında not düşülü). Ön koşul: P2.

**P4 — Sahte modelle uçtan uca koşu.** Planın `tests/test_report_flow.py::test_report_run_completes_with_fake_adapter_and_produces_a_valid_report`
testi. İlk kez bütün zincir koşar. Ön koşul: P3.

**P5 — Gerçek modelle bir koşu.** `gpt-5.6-luna`, küçük bir araştırma, kütüphanenin **kopyası** üzerinde,
8799 portunda; canlı 8765 servisine asla dokunulmaz. Sahibin onayı gerekir. Aynı koşuda dilim 0'ın hiç
yapılmamış süre ölçümü (`scripts/p6_eval/measure_fill.py`) de halledilir.

**Buradan sonrası P5'in çıktısına bakılarak sıralanır.** Bugünkü tahmini sıra:

**P6 — Şema turu.** `report_plan`'a `limitations_column_id` ve `future_work_column_id`; `report_target`'a
VIII'in sayısal çekirdeği (1e Task 2). `contracts/research/*.schema.json`, `domain/contracts.py`, fixture'lar,
`tests/fakes.py` ve `methods/deixis-research/references/report.md` birlikte değişir; `skill_package_hash`
değişecektir, beklenen budur. Gerekçe: `selection.py`'nin VI/VII seçimi ve `gaps.py` sütun rollerini plandan
okuyor, alanlar henüz yok.

**P7** — kalan sekiz montaj kuralı (5, 6, 8, 9, 11, 12, 13, 14).
**P8** — 1d Task 3: `repair_section` ve istisna kayıtları.
**P9** — 1f: `report_review` ve destek-bozan onarımın geri alınması.
**P10** — 1h: hazırlık panelinin dördüncü durumu.
**P11** — 1i: okuma biçimli rapor görünümü, değişiklik bandı, zaman çizelgesi satırları.
**P12** — 1j: Markdown dışa aktarma ve numaralandırma.
**P13** — 1k: kesinti testleri (kota, çökme, iptal, kapsam değişimi, geç sonuç).
**P14** — 1l: scriptlenmiş modelle Playwright kabul testi.
**P15** — 1m: davranış vakaları ve R10 ekilmiş hata kümesi.
**P16** — 1n: beklenti dosyası (koşudan **önce** donar ve commit'lenir), ölçüm raporu, karar kaydı, tasarım
notunun durum güncellemesi.

Gerçekçi tahmin: P1–P5 bir oturumluk iş. Bütün dilim 1, arayüz ve ölçüm dahil, iki oturumda **ancak** tasarım
sürprizi çıkmazsa biter; üç daha olası.

## Sahibe sorulan açık kararlar

1. **D12 atıf tutamakları.** `with_citation_handles` yalnız `grounded_answer`, `answer_review` ve
   `cell_extraction` için uygulanıyor. Rapor bölümleri de pasaj ve hücre alıntılıyor. Eklenirse
   `with_citation_handles`, `citation_handles` ve `resolve_citation_handles` `report_target`, izin listesi ve
   çıktı alanlarını da çevirmeli. Dışarıda bırakmak doğruluğu bozmuyor ama raporu D12'nin kayda geçirdiği
   uzun-kimlik kopyalama hatalarına açık bırakıyor. Karar ölçümden önce mi sonra mı, sahibin.
2. **Gerçek model koşusu onayı** (P5).
3. **Dilim 2, 3, 4'ün tasarımı yok** — sırasıyla 10, 10 ve 9 açık soru. Dilim 2 öne alınmalı, çünkü raporun
   içeriğini değiştiriyor: VI'ya dördüncü aday türü, III'e alanın gelişimi alt başlığı. Dilim 1 buna yer
   bıraktı (`report_gaps.kind` kapalı liste değil, III alt bölüm kabul ediyor), ama karar ne kadar gecikirse
   dilim 1'in çıktısı o kadar çok yeniden yazılır.

## Bilerek ertelenenler

- **Kesilme kaydının tablosu yok.** §4.3 bütçeye sığmayan kayıtların saklanmasını ve VIII'de sayı olarak
  görünmesini istiyor; migration 0035'te yeri yok. Nereye yazılacağı P2'de kararlaştırılmalı
  (`report_sections.validation_json` en yakın aday).
- **Montaj kuralı 7 kırılgan.** II ve VIII'in sayılarının dondurulmuş korpusla aynı olduğunu, bölümün
  düzyazısında İngilizce/Türkçe etiket sözcüklerini (`found`/`bulunan`, `unique`/`tekil`, …) arayıp yanındaki
  sayıyı okuyarak denetliyor. Etiket başka türlü ifade edilirse denetim sessizce kaçırır. Sağlam tasarım,
  bölümün sayılarını yapılandırılmış olarak saklayıp düzyazıyı onlardan üretmektir; P7'de ya da ölçümden sonra
  karara bağlanmalı.
- `CAPABILITIES["supported_tasks"]` rapor görevlerini saymıyor.
- `report_phrase_repair` bölüm kalıplarını alıyor ama çalışma zamanı dosya listesinde `phrases.md` yok, yani
  şimdilik etkisiz.
- `tests/test_api_flow.py`'de ~35 test fonksiyonu iki kez tanımlı (kötü bir birleştirme); pytest yalnız
  ikincisini topluyor. Bu dilimin konusu değil, ayrı bir temizlik.

## Tur nasıl koşulur

```sh
codex exec -s workspace-write -m gpt-5.6-sol -c model_reasoning_effort="medium" - < <istem.md>
```

`/Applications/ChatGPT.app/Contents/Resources/codex` ikilisi doğrudan çağrılır; `~/.local/bin/codex` sembolik
bağı `code-mode-host`'u bulamadığı için Codex hiçbir komut çalıştıramaz. İstem stdin'den `-` ile verilir.

İstemin her turda taşıması gerekenler: okunacak dosyalar, dokunulmayacak dosyalar (**başka bir oturum
`apps/web/`, `api/app.py`, `workflow/store.py`, `docs/decisions.md` üzerinde çalışıyor olabilir**),
"durum değiştiren hiçbir git komutu yok", tur öncesi ve sonrası test sayıları, ve "uydurma, bulamadığını
bildir".

Test koşumu `PYTHONPATH=backend:.` ister; belgelenen `PYTHONPATH=backend` ile `tests/test_p4_eval.py`
`ModuleNotFoundError: No module named 'scripts'` veriyor. Codex'in kum havuzu varsayılan uv önbelleğine
erişemiyorsa `UV_CACHE_DIR=/tmp/deixis-uv-cache` gerekir.
