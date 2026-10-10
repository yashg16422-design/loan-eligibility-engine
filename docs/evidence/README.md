# Evidence: measured Treasure Hunt runs

For the whole required path (upload, n8n workflows A/B/C/E executions, crawl results, emails,
credentials, CI) see [`REQUIRED_PATH.md`](REQUIRED_PATH.md). This page covers the Treasure Hunt numbers.

`pipeline_runs_2026-10-10.json` is a direct export of the `pipeline_runs` table from the live
RDS database (exported 2026-10-09 20:50 UTC, every completed run). Every number in README §8
traces to a field here; the headline run is `e7115e09-6bc3-4a23-ada2-f15f0de31d02` (the real
10,000-user `users.csv`, 2026-10-08):

| README figure | Field | Value |
|---|---|---|
| 590,000 naive pairs | `naive_pairs` | 590000 |
| 164 classes | `classes` | 164 |
| 9,676 class x product decisions | `class_product_pairs` | 9676 |
| 276,594 pairs passing the hard filter / matches written | `pairs_after_sql` / `matches_new` | 276594 / 276594 |
| 467 decided by SQL, 3,741 by compiled rules | `rule_decided` / `llm_candidates` | 467 / 3741 |
| 46 distinct criteria texts, all compiled | `residual_texts` / `rules_compiled` | 46 / 46 |
| 5 LLM calls, 7,008 in / 5,847 out tokens, about $0.024 | `llm_calls` / tokens / `llm_cost_usd_est` | 5 / 7008 / 5847 / 0.024317 |
| 0 mismatches | `correctness_ok` | true |
| 40.6 s | `seconds` | 40.6 |

Query used (run as the read-only-in-practice `n8n_workflows` role through the SSM tunnel):

```sql
SELECT run_id, mode, status, started_at, finished_at, round(extract(epoch FROM finished_at - started_at)::numeric, 1) AS seconds, users_in, products_in, naive_pairs, pairs_after_sql, classes, class_product_pairs, rule_decided, llm_candidates, not_eligible_pairs, residual_texts, rules_compiled, llm_cache_hits, llm_calls, llm_input_tokens, llm_output_tokens, llm_cost_usd_est, matches_new, matches_superseded, matches_unchanged, correctness_ok, emails_sent, emails_skipped_demo, cuts FROM pipeline_runs WHERE status = 'done' ORDER BY started_at;
```

## Re-run after a correctness fix (2026-10-10)

`pipeline_runs_full_file_2026-10-10.json` adds every completed run over 1,000 users, exported
2026-10-10 08:25 UTC (same columns). Run `80864307-cf27-4d34-947a-6eb492559918` re-matched the
same 10,000 users after a fix: a lender that publishes **no** criteria (our normalizer's note
"Eligibility criteria not published: confirm with the lender") had compiled to no rules and no
requirements, which Stage 1 reads as *eligible*; 7 products were affected (e.g. Federal Bank on
Paisabazaar showed 10,000 of 10,000 eligible). compile.js now keeps the note as a requirement and
migration `007_pipeline_notes.sql` applied the same rule to the cached compile results.

| Figure | Field | Value |
|---|---|---|
| 580,000 naive pairs (58 active products now) | `naive_pairs` | 580000 |
| 164 classes (same as the first run) | `classes` | 164 |
| 0 LLM calls: all 44 criteria answers reused from the cache | `llm_calls` / `llm_cache_hits` | 0 / 44 |
| 0 mismatches against the brute-force check of every pair | `correctness_ok` | true |
| 103.6 s (includes rewriting ~33,000 tiers in place) | `seconds` | 103.6 |

After the re-run, eligible users per lender were recomputed independently from `users.csv` and
each product's published criteria (a separate Python script, not the engine): all 10 lenders in
the analytics chart matched exactly (Axis Bank 10,000; IndusInd 6,429; YES Bank 6,755; IDFC FIRST
6,095; Federal Bank 0). Known quirk: early product-mode run `c6b74e76` recorded
`llm_cache_hits = -36`, a bad counter value from that run; it is not quoted anywhere.

`docs/extras/mock/*.json` are earlier exports used as sample data for the front ends; this
file is the evidence.
