# Lead–Lag Feasibility Screen — 2026-11-12

Read-only offline screen per MERID_LEAD_LAG_SHADOW_LANE_DESIGN_2026-11-12.md.

## 1. Data provenance

- RTI archive span: {'2026-11-05': 7360, '2026-11-06': 13500, '2026-11-08': 1055, '2026-11-10': 1485, '2026-11-12': 75825, '2026-11-13': 9682}
- Decision screen window (UTC): ['2026-11-12T19:40:00+00:00', '2026-11-13T00:35:00+00:00']
- Decisions in window: 44953 across 96 tickers
- Research-eligible production rows: see provenance.json
- Rows with snapshot probs: 44953; with settled outcome: 44451
- Route-dedup probability mismatches: 3071
- Outcome conflict tickers: 0

### RTI per-day coverage

| day | ticks |
|---|---|
| 2026-11-05 | 7360 |
| 2026-11-06 | 13500 |
| 2026-11-08 | 1055 |
| 2026-11-10 | 1485 |
| 2026-11-12 | 75825 |
| 2026-11-13 | 9682 |

### Decisions per day

| day | decisions |
|---|---|
| 2026-11-12 | 38874 |
| 2026-11-13 | 6079 |

## 2. Dataset

- Candidate rows after route dedup: 12214
- Forecast dataset rows: see dataset.jsonl
- Coverage: `{"emitted|h120": 66, "emitted|h300": 71, "emitted|h60": 50, "emitted|h600": 72, "miss_no_prior|h600": 4, "miss_stale_or_none|h120": 10, "miss_stale_or_none|h300": 5, "miss_stale_or_none|h60": 26}`

## 3. Evaluation coverage

- `src|A_mechanistic_raw`: {'n_rows': 259, 'n_settlement_active': 259, 'n_with_p0': 259, 'n_feature_complete': 255, 'n_days': 2, 'n_tickers': 72}
- `src|B_production_cal`: {'n_rows': 259, 'n_settlement_active': None, 'n_with_p0': 259, 'n_feature_complete': 255, 'n_days': 2, 'n_tickers': 72}
- `recv|A_mechanistic_raw`: {'n_rows': 259, 'n_settlement_active': 259, 'n_with_p0': 259, 'n_feature_complete': 255, 'n_days': 2, 'n_tickers': 72}
- `recv|B_production_cal`: {'n_rows': 259, 'n_settlement_active': None, 'n_with_p0': 259, 'n_feature_complete': 255, 'n_days': 2, 'n_tickers': 72}
- `recv_p500|A_mechanistic_raw`: {'n_rows': 259, 'n_settlement_active': 259, 'n_with_p0': 259, 'n_feature_complete': 255, 'n_days': 2, 'n_tickers': 72}
- `recv_p500|B_production_cal`: {'n_rows': 259, 'n_settlement_active': None, 'n_with_p0': 259, 'n_feature_complete': 255, 'n_days': 2, 'n_tickers': 72}
- `recv_p1000|A_mechanistic_raw`: {'n_rows': 259, 'n_settlement_active': 259, 'n_with_p0': 259, 'n_feature_complete': 255, 'n_days': 2, 'n_tickers': 72}
- `recv_p1000|B_production_cal`: {'n_rows': 259, 'n_settlement_active': None, 'n_with_p0': 259, 'n_feature_complete': 255, 'n_days': 2, 'n_tickers': 72}

## 4. Fold metrics (test-fold log-loss / Brier)

### A_mechanistic_raw / src / pre_2026-11-13__post (n_test=28)
- P0: ll=0.46956892609368334 brier=0.1607739694920383 n=None base=None
- P0_cal: ll=0.46928348848172047 brier=0.16440790211453377 n=None base=None
- P1: ll=0.7301550032875372 brier=0.21509831129869053 n=28 base=0.1429
- P1_noBTC: ll=0.6724600846004598 brier=0.2214184721133726 n=28 base=0.1429
- P1_noMkt: ll=0.6208498494922684 brier=0.18605948162453276 n=28 base=0.1429
- P1_min: ll=0.5105659430541939 brier=0.18148975906022338 n=28 base=0.1429
- P1_future: ll=0.6362800659635177 brier=0.22168893381469892 n=19 base=0.1579

### B_production_cal / src / pre_2026-11-13__post (n_test=28)
- P0: ll=0.47641754158772004 brier=0.16706604396273367 n=None base=None
- P0_cal: ll=0.4858064857187822 brier=0.17269455183956253 n=None base=None
- P1: ll=0.7329053605364881 brier=0.21694351391304492 n=28 base=0.1429
- P1_noBTC: ll=0.6726999411745841 brier=0.22126239135754375 n=28 base=0.1429
- P1_noMkt: ll=0.611894083192135 brier=0.18420390456217597 n=28 base=0.1429
- P1_min: ll=0.509693357209117 brier=0.18221639752293564 n=28 base=0.1429
- P1_future: ll=0.6541927882168123 brier=0.22922343456206673 n=19 base=0.1579

### A_mechanistic_raw / recv / pre_2026-11-13__post (n_test=28)
- P0: ll=0.46956892609368334 brier=0.1607739694920383 n=None base=None
- P0_cal: ll=0.46928348848172047 brier=0.16440790211453377 n=None base=None
- P1: ll=0.7490410980998102 brier=0.2172679874083761 n=28 base=0.1429
- P1_noBTC: ll=0.6591382955191062 brier=0.2174477114661493 n=28 base=0.1429
- P1_noMkt: ll=0.6427106625619993 brier=0.18740181574851217 n=28 base=0.1429
- P1_min: ll=0.49706464862724237 brier=0.17585972803147257 n=28 base=0.1429
- P1_future: ll=0.5984879496595931 brier=0.20549562785988415 n=19 base=0.1579

### B_production_cal / recv / pre_2026-11-13__post (n_test=28)
- P0: ll=0.47641754158772004 brier=0.16706604396273367 n=None base=None
- P0_cal: ll=0.4858064857187822 brier=0.17269455183956253 n=None base=None
- P1: ll=0.7460745339221196 brier=0.21751008988385184 n=28 base=0.1429
- P1_noBTC: ll=0.6593256798415955 brier=0.2173569812920337 n=28 base=0.1429
- P1_noMkt: ll=0.6364380533379836 brier=0.1868880154620893 n=28 base=0.1429
- P1_min: ll=0.5001515446158739 brier=0.17870581246169542 n=28 base=0.1429
- P1_future: ll=0.6130255562064744 brier=0.21185887536427486 n=19 base=0.1579

### A_mechanistic_raw / recv_p500 / pre_2026-11-13__post (n_test=28)
- P0: ll=0.46956892609368334 brier=0.1607739694920383 n=None base=None
- P0_cal: ll=0.46928348848172047 brier=0.16440790211453377 n=None base=None
- P1: ll=0.9700125507707504 brier=0.2784601940749883 n=28 base=0.1429
- P1_noBTC: ll=0.646156862964465 brier=0.21086070514530778 n=28 base=0.1429
- P1_noMkt: ll=0.7925501693643154 brier=0.24822815568579792 n=28 base=0.1429
- P1_min: ll=0.5345458001957699 brier=0.19389468257761114 n=28 base=0.1429
- P1_future: ll=0.5698182331037945 brier=0.17431810175246404 n=19 base=0.1579

### B_production_cal / recv_p500 / pre_2026-11-13__post (n_test=28)
- P0: ll=0.47641754158772004 brier=0.16706604396273367 n=None base=None
- P0_cal: ll=0.4858064857187822 brier=0.17269455183956253 n=None base=None
- P1: ll=0.9673731158661875 brier=0.2782271130714105 n=28 base=0.1429
- P1_noBTC: ll=0.6478366215189055 brier=0.21201231463593426 n=28 base=0.1429
- P1_noMkt: ll=0.7879181721853696 brier=0.24845138929381902 n=28 base=0.1429
- P1_min: ll=0.5452393425680252 brier=0.2000353655524396 n=28 base=0.1429
- P1_future: ll=0.5794293776012353 brier=0.1785361617027265 n=19 base=0.1579

### A_mechanistic_raw / recv_p1000 / pre_2026-11-13__post (n_test=28)
- P0: ll=0.46956892609368334 brier=0.1607739694920383 n=None base=None
- P0_cal: ll=0.46928348848172047 brier=0.16440790211453377 n=None base=None
- P1: ll=1.0861782202517178 brier=0.2968375550874712 n=28 base=0.1429
- P1_noBTC: ll=0.7249360568993307 brier=0.23908433863672968 n=28 base=0.1429
- P1_noMkt: ll=0.8758168911188873 brier=0.2632666669750882 n=28 base=0.1429
- P1_min: ll=0.5619735503328486 brier=0.2014536323974339 n=28 base=0.1429
- P1_future: ll=0.6273484570177402 brier=0.19594487668487637 n=19 base=0.1579

### B_production_cal / recv_p1000 / pre_2026-11-13__post (n_test=28)
- P0: ll=0.47641754158772004 brier=0.16706604396273367 n=None base=None
- P0_cal: ll=0.4858064857187822 brier=0.17269455183956253 n=None base=None
- P1: ll=1.0869941147349924 brier=0.29654837558532937 n=28 base=0.1429
- P1_noBTC: ll=0.7268619205405006 brier=0.2400495570954308 n=28 base=0.1429
- P1_noMkt: ll=0.8920061656673764 brier=0.26670537639738945 n=28 base=0.1429
- P1_min: ll=0.5766183987266297 brier=0.20834474685501828 n=28 base=0.1429
- P1_future: ll=0.638037423070533 brier=0.2000711769162278 n=19 base=0.1579

## 5. Paired differences (challenger − P0_cal; >0 favors challenger)

### A_mechanistic_raw|src|pre_2026-11-13__post (n_obs=28)

### B_production_cal|src|pre_2026-11-13__post (n_obs=28)

### A_mechanistic_raw|recv|pre_2026-11-13__post (n_obs=28)

### B_production_cal|recv|pre_2026-11-13__post (n_obs=28)

### A_mechanistic_raw|recv_p500|pre_2026-11-13__post (n_obs=28)

### B_production_cal|recv_p500|pre_2026-11-13__post (n_obs=28)

### A_mechanistic_raw|recv_p1000|pre_2026-11-13__post (n_obs=28)

### B_production_cal|recv_p1000|pre_2026-11-13__post (n_obs=28)

## 6. Indicative economics (taker EV at snapshot asks, exact fee)

- By checkpoint (p_cal): {}

## 7. Interpretation notes (review corrections 2026-11-13)

- A failed future-information diagnostic does not identify the cause. Neither the deployable variants nor the future-shifted diagnostic improved the incumbent on this small test block. The screen cannot distinguish absence of incremental information, estimation error, model misspecification, distribution shift, or insufficient power. Future BTC returns are not an oracle for another asset's settlement outcome; they can remain unhelpful when the target's own price, banked samples, and baseline probability already explain most of the outcome. The diagnostic is retained as a pipeline check, not a required positive control.
- Negative average EV does not imply no tradable subset. The window provided no demonstrated incremental taker opportunity from lead-lag; it does not establish that a properly selected, deduplicated subset lacks opportunity, nor that value must be expressed through maker or settlement lanes. Because per-row shadow probabilities were not persisted, the key comparison — incremental opportunities under p_shadow vs p_incumbent — was not completed. (Repaired: the runner now persists per-row predictions.)
- Receipt-time reconstruction supports latency robustness, not full production deployability. Archiver receipt time establishes availability to the archiver, not to the production adapter; small average lag does not characterize all operational failure modes. Prospective capture must measure the production path directly.
- Bootstrap limitation is specific to this screen: with a single test day, day-block resampling is not meaningful. Shorter blocks could technically be resampled but would not create evidence about performance across days or regimes; descriptive paired losses are more useful than a fragile significance calculation here.
