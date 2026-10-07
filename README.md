# Daily Brief market times

Stock analysis uses these regional display zones:

| Tab | IANA zone | Display |
| --- | --- | --- |
| India | Asia/Kolkata | IST (UTC+05:30) |
| United States | America/New_York | EDT or EST, automatically for the quote date |
| Asia / Global Chips | Asia/Singapore | GMT+8 (UTC+08:00) |

The backend adds `display_timezone` and an offset-aware `source_timestamp_local`
to each regional stock. Original UTC source timestamps and exchange time zones
remain unchanged for validation and trading-session calculations. GMT+8 is a
common display zone for the Asia tab: Samsung trades in Korea (UTC+9), while
the BABA and TSM symbols are US-listed ADRs; their sessions retain their actual
exchange zones. Failed fetches retain their original quote time and stale status.

The production Actions worker refreshes and commits sources every 300 seconds
for five hours, then dispatches a successor. Scheduled runs at :02, :07, ... :57
UTC are a recovery trigger. Production workers cannot overlap; PR checks use a
separate concurrency group. To stop the automation, disable the workflow and
cancel its running/pending runs in Actions.

The hosted dashboard checks the public GitHub raw data every 60 seconds and
when a hidden tab becomes visible. It does not wait for a Pages build for each
data commit. Pages still publishes changes to the dashboard code. Local copies
read their local data files.

The header shows the actual completed source-check time and warns after ten
minutes without a refresh. Every tab displays quote timestamps and stale status;
individual indicative/stale fields remain labelled; market-cap cells keep their
value-only appearance and expose status, source, quote time and FX provenance in
their tooltips. Daily gain/loss percentages round half up to two decimals while
the underlying source values remain unchanged. Equity tables identify BABA/TSM
as US-listed ADRs.
Source delays, market closures,
GitHub runner handoffs and outages can still delay quotes; five minutes is a
refresh target, not a real-time market-data guarantee. The worker uses standard
GitHub-hosted runners in this public repository. Review Actions billing before
making the repository private.

Refreshes retain a newer saved observation when a provider returns an older
quote, label the retained snapshot stale, and record the rejected source time.
The browser also retains its newer market snapshot if both endpoints lag.
Daily changes on corroborated rows are calculated from the same Google price
and previous close, with calculation inputs and timestamps in field metadata.
Market-cap cells show only formatted values, and GAIN/LOSS% cells show only signed
percentage values. Missing data remains explicitly unavailable. Verification, source-time and FX
metadata remain in the data, and row-level quote status remains visible.
If an edit advances main during publication, the worker discards only its own
unpushed generated snapshot and fetches the latest branch before regenerating
data. It retries up to three times, then leaves the checkout clean and resumes
at the next refresh slot. It never force-pushes or rebases old market snapshots.
Other worker failures exit nonzero and save `work/refresh-failure.json`; successor
dispatch still runs after a worker failure, except when the run was cancelled.

Checks: `python -m unittest discover -s tests -v` and `node tests/frontend.cjs`.

Tech & AI News also shows the 20 newest open-licence text-generation models
from selected official Hugging Face publishers. Every market/news cycle checks
the model API; dashboard polling remains every minute. The list is independent
of news time windows and the 15 AI / 5 other-tech news quota. Dates are Hub
repository creation dates, not edit dates or independently verified release
dates. Only publisher-declared Apache-2.0, MIT, BSD-2/3, ISC and CC0 weight
licences qualify; restricted/unknown licences, gated models, adapters and
GGUF/GGML uploads are excluded. Open training data and training code are not
certified by this list. Provider failures retain saved models with stale labels;
checks older than ten minutes show a stale warning.

Free-source additions: Shenzhen Component (399001.SZ) uses Eastmoney when its
identity/scale-validated quote is newer and under 30 minutes old. It is labelled
indicative. TSM remains the US-listed ADR: its Yahoo market cap is corroborated
against Nasdaq with matching regular-session date/price and 0.01% cap tolerance.
Other US-listed equities (including BABA) request Nasdaq's public quote and
summary when Yahoo/Google caps disagree beyond Google's rounding interval or
Google has no cap. Symbol, issuer, exchange, currency, date and quote age must
match. Two concurrent tasks bound the extra provider load. Each refresh checks
TSM plus up to four other candidates, rotating larger conflict sets across runs.
Metadata distinguishes an unrequested Nasdaq check from a successful request.
Near matches up to 0.1% in cap and price, and 0.05% in implied shares (cap/price),
may select Yahoo's figure but remain INDICATIVE, with no verification claim.
These thresholds are fallback policy, not an accuracy guarantee. Implied shares
are a diagnostic, not independently confirmed shares outstanding. Older cap
observations cannot replace newer verified or stale caps. A corroborated cap may
replace a later indicative Google quote snapshot only within the same New York
date and the existing 20-minute source-skew limit: neither provider supplies a
cap-specific timestamp. The replaced indicative snapshot time is retained in
metadata. Neither agreement nor near agreement
proves that providers use independent underlying data.
Raw Yahoo/Google cap comparisons and Nasdaq failures are retained in field
metadata. USD ADR rows discard obsolete native-cap/FX fields. Samsung's company
cap is an explicit estimate: common price times reported common shares plus
preferred price times reported preferred shares, then KRW-to-USD conversion.
Each refresh reads Samsung IR's latest dated share-count table and Google prices
for 005930 and 005935. The counts must total correctly and be no older than 180
days; both regular-session quotes must have the same Korean date and be within
20 minutes of each other, subject to the existing quote-age policy. The row
visibly labels common + preferred, estimate/stale status, and the share-report
date. Quarterly counts are not claimed to be live counts, so the cap remains
INDICATIVE even when prices agree. Failures retain only an existing company
estimate as STALE; an ambiguous provider cap is not a substitute. Class prices,
counts, report date, native cap and FX provenance are retained in metadata.
TSM records its NYSE ADS basis (one ADS represents five ordinary shares).
Official share-class references: [TSMC 20-F](https://investor.tsmc.com/sites/ir/sec-filings/2024%2020-F.pdf)
and [Samsung IR](https://www.samsung.com/global/ir/stock-information/listing-Info/).
HKEX/KRX/TWSE official live-cap feeds and paid APIs are not integrated.
Nasdaq supplies no separate cap timestamp. Failures preserve existing fallbacks;
per-run artifacts record free-source errors. Public endpoint availability is not
a guarantee of real-time data. Market-cap cells retain their numeric formatting.

Samsung class-price fallback: when the common quote uses Yahoo Finance, both explicitly identified KRX classes use Yahoo regular-session prices with the same freshness and timing checks. Market cap records its own class input timestamps; retained display prices are not substituted into the calculation.
