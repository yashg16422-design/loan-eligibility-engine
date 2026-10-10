# Evidence: measured Treasure Hunt runs

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

`docs/extras/mock/*.json` are earlier exports used as sample data for the front ends; this
file is the evidence.
