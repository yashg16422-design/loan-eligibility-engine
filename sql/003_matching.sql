-- 003_matching.sql: Workflow B, the Optimization Treasure Hunt (PLAN.md §11).
--
-- The LLM no longer judges (user-class x product) pairs. It COMPILES each product's free-
-- text criteria once into structured rules (cached by text hash), and SQL then evaluates
-- every pair. LLM cost scales with the number of distinct criteria texts, not with users.

-- Replaced by criteria_rules (pair-level cache -> criteria-level cache).
DROP TABLE llm_decisions;

-- Compiled residual criteria, one row per distinct other_criteria_text (+ prompt version).
CREATE TABLE criteria_rules (
    criteria_text_hash text NOT NULL,          -- sha256 of products.other_criteria_text
    prompt_version     text NOT NULL,
    -- [{"field": "credit_score"|"monthly_income"|"age", "op": ">="|"<=", "value": n,
    --   "applies_to": "any"|"salaried"|"self_employed"|"business", "quote": "..."}]
    rules              jsonb NOT NULL DEFAULT '[]',
    -- conditions our 5 CSV fields cannot check, shown to the user ("2 years experience")
    requirements       jsonb NOT NULL DEFAULT '[]',
    model_id           text NOT NULL,
    llm_input_tokens   int,
    llm_output_tokens  int,
    created_at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (criteria_text_hash, prompt_version)
);

-- Evidence of each run, kept for the README funnel and the correctness proof.
-- A class = users whose income, credit score and age fall in the same interval between
-- consecutive cut points, with the same employment type: they get identical decisions.
CREATE TABLE match_classes (
    run_id            uuid NOT NULL REFERENCES pipeline_runs (run_id) ON DELETE CASCADE,
    class_id          int  NOT NULL,
    income_floor      int  NOT NULL,   -- lower bound of the class's income interval
    score_floor       int  NOT NULL,
    age_floor         int  NOT NULL,
    employment_status text NOT NULL,
    users             int  NOT NULL,
    PRIMARY KEY (run_id, class_id)
);

CREATE TABLE match_pairs (
    run_id       uuid NOT NULL,
    class_id     int  NOT NULL,
    product_id   uuid NOT NULL REFERENCES loan_products (product_id),
    tier         text NOT NULL CHECK (tier IN ('eligible', 'conditional', 'not_eligible')),
    stage        text NOT NULL CHECK (stage IN ('sql', 'rules', 'llm_rules')),
    requirements text,
    PRIMARY KEY (run_id, class_id, product_id),
    -- Deferred: Stage 1 writes classes and pairs in ONE statement; checked at commit.
    FOREIGN KEY (run_id, class_id) REFERENCES match_classes (run_id, class_id)
        ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
);

-- Transparent fit score for ranking (best pick / top picks), and the reasons behind it.
ALTER TABLE matches
    ADD COLUMN fit_score   numeric(5, 1),
    ADD COLUMN fit_reasons jsonb;

ALTER TABLE pipeline_runs
    ADD COLUMN scope_product_ids uuid[],  -- product mode: only these products are re-matched
    ADD COLUMN cuts            jsonb,     -- {income:[..], score:[..], age:[..]}: the class boundaries
    ADD COLUMN residual_texts  int,   -- distinct free-text criteria among in-scope products
    ADD COLUMN rules_compiled  int,   -- of which compiled by the LLM in THIS run (cache misses)
    ADD COLUMN not_eligible_pairs int,
    ADD COLUMN correctness_ok  boolean,  -- brute-force check result
    ADD COLUMN error           text;
