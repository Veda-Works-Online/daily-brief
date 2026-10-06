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
Worker failures exit nonzero and save `work/refresh-failure.json`; successor
dispatch still runs after a worker failure, except when the run was cancelled.

Checks: `python -m unittest discover -s tests -v` and `node tests/frontend.cjs`.

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
metadata. USD ADR rows discard obsolete native-cap/FX fields. Samsung retains
KRW-to-USD provenance and an explicit note that preferred-class inclusion has
not been verified; quarterly share counts are not used as current live counts.
TSM records its NYSE ADS basis (one ADS represents five ordinary shares).
Official share-class references: [TSMC 20-F](https://investor.tsmc.com/sites/ir/sec-filings/2024%2020-F.pdf)
and [Samsung IR](https://www.samsung.com/global/ir/stock-information/listing-Info/).
HKEX/KRX/TWSE official live-cap feeds and paid APIs are not integrated.
Nasdaq supplies no separate cap timestamp. Failures preserve existing fallbacks;
per-run artifacts record free-source errors. Public endpoint availability is not
a guarantee of real-time data. Market-cap cells retain their numeric formatting.
