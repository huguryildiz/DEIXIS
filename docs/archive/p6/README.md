# P6 kapanış kayıtları

P6; eş zamanlı tablo doldurma, bölümlü rapor, gelişim çizgileri, iddiaya özgü
kill-search, düzenleme denetimi ve LaTeX dışa aktarımını kapsadı. Bu dizin
tamamlanan dilim planlarını, beklentileri, devir kaydını ve eski ölçüm
sonuçlarını tutar. [Rapor tasarımı](../../product/p6-report-design.md),
test girdisi olan `docs/product/p6-slice2-chain.json` ve dondurulmuş L9
girdisinin satırlarını andığı
[Chain of Ideas tasarımı](../../product/p6-slice2-chain-of-ideas.md) yerinde kaldı.

Rapor ölçümünün üç denemesi tamamlanmış rapor üretmedi:
[ilk deneme](p6-slice1-report-results.md) tabloda,
[ikinci](p6-slice1-report-results-run2.md) ve
[son deneme](p6-slice1-report-results-run3.md) IV. bölümde durdu
([D124](../../decisions.md#d124--the-p16-report-measurement-stopped-at-the-table-no-report-was-started-r1-to-r11-not-measured),
[D126](../../decisions.md#d126--the-second-p16-report-run-stopped-at-section-iv-after-7-sessions-only-r1-and-r7-measured-the-three-failed-rows-stayed-out-of-the-written-sections),
[D128](../../decisions.md#d128--the-third-and-last-p16-report-run-stopped-at-section-iv-after-8-sessions-on-a-quote-anchor-failure-only-r1-and-r7-measured-the-series-ends-without-a-completed-report)).
[L9 hazırlığı](p6-slice2-results.md) korpus kapılarını geçemedi;
lineage çalışmadı, R12–R15 ölçülmedi. [D142](../../decisions.md#d142--p6-slice-2-closed-as-implemented-usefulness-of-link-production-on-a-real-corpus-not-shown-two-medium-findings-of-the-cross-batch-review-fixed-restore-cannot-re-activate-a-cycle-whitespace-what_changed-goes-to-repair)
dilim 2'yi uygulanmış olarak kapattı; gerçek korpusta yarar gösterilmedi.

[D61](../../decisions.md#d61--send-table-fill-cell-extraction-calls-concurrently-under-a-shared-adjustable-limit)
eş zamanlı doldurmayı kaydeder.
[D154](../../decisions.md#d154--p6-slice-3-k5-the-candidate-tasks-were-run-once-on-seven-synthetic-cases-and-once-end-to-end-on-a-development-claim-with-a-real-model-slice-3-is-closed-as-implemented-the-independent-measurement-k6-moves-to-p9)
kill-search'ü geliştirme vakalarıyla kapattı; bağımsız K6 ölçümü P9'a taşındı.
[D157](../../decisions.md#d157--p6-slice-4-e4-a-scripted-sequence-runs-edit-citation-removal-cell-change-source-removal-check-restore-backup-and-purge-in-one-order-on-synthetic-rows-slice-4-is-closed-as-implemented-the-real-report-measurement-moves-to-p9)
düzenleme yolunu sentetik dizide kapattı; gerçek rapor ölçümü P9'a taşındı.
[D160](../../decisions.md#d160--p6-slice-5-x5-the-report-screen-has-a-download-latex-button-that-saves-the-zip-and-reports-the-export-note-count-in-one-toast-slice-5-is-implemented-with-no-real-model-measurement) LaTeX ekranını uygulanmış olarak kaydeder;
gerçek model ölçümü yoktur. Sonraki ölçümler ve kalan borçlar
[P9 kabul kaydındadır](../../product/p9-acceptance-record.md#open-debts-carried-past-p9).
