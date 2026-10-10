// Shapes returned by the api Lambda (loan_engine/api/repository.py). Numeric columns that
// Postgres returns as NUMERIC arrive as numbers; dates as ISO strings.

export type Employment = "salaried" | "self_employed" | "business";
export type Channel = "direct" | "bankbazaar" | "paisabazaar";
export type Tier = "eligible" | "conditional";
export type SimTier = Tier | "not_eligible";

export interface Product {
  product_id: string;
  lender: string;
  lender_key: string;
  channel: Channel;
  product_name: string;
  product_url: string | null;
  interest_rate_min: number | null;
  interest_rate_max: number | null;
  rate_type: string | null;
  loan_amount_min: number | null;
  loan_amount_max: number | null;
  tenure_months_max: number | null;
  min_monthly_income: number | null;
  min_credit_score: number | null;
  max_credit_score: number | null;
  min_age: number | null;
  max_age: number | null;
  employment_types: Employment[] | null;
  other_criteria_text: string | null;
  verification: "ok" | "ambiguous" | "unverified" | null;
  last_seen_at: string | null;
}

export interface CompiledRule {
  field: "monthly_income" | "credit_score" | "age";
  op: ">=" | "<=";
  value: number;
  applies_to: "any" | Employment;
  quote?: string;
}

/** GET /products: a product plus its AI-compiled free-text rules (null = never compiled). */
export interface CatalogProduct extends Product {
  compiled_rules: CompiledRule[] | null;
  compiled_requirements: string[] | null;
}

export interface FitReasons {
  income_multiple?: number;
  credit_margin?: number;
  rate_from?: number;
  has_conditions?: boolean;
}

/** GET /me/matches: one active match joined with its product. */
export interface Match extends Product {
  match_id: number;
  tier: Tier;
  fit_score: number;
  fit_reasons: FitReasons;
  requirements: string | null;
  matched_at: string;
}

export interface Me {
  user_id: string;
  name: string | null;
  monthly_income: number;
  credit_score: number;
  employment_status: Employment;
  age: number;
  source: "csv" | "instant_check" | null;
  matching: "running" | "done" | "failed";
  matches: number;
  eligible: number;
  lenders: number;
  best_rate: number | null;
  max_amount: number | null;
}

export interface Preferences {
  shortlist: string[];
  top3: string[];
  hidden: string[];
  alerts: boolean;
  updated_at: string | null;
}

export interface Profile {
  monthly_income: number;
  credit_score: number;
  age: number;
  employment_status: Employment;
}

export interface Run {
  run_id: string;
  mode: "upload" | "products";
  job_id: string | null;
  status: "running" | "done" | "failed";
  started_at: string;
  finished_at: string | null;
  seconds: number | null;
  users_in: number | null;
  products_in: number | null;
  naive_pairs: number | null;
  pairs_after_sql: number | null;
  classes: number | null;
  class_product_pairs: number | null;
  rule_decided: number | null;
  llm_candidates: number | null;
  llm_cache_hits: number | null;
  llm_calls: number | null;
  llm_input_tokens: number | null;
  llm_output_tokens: number | null;
  llm_cost_usd_est: number | null;
  matches_new: number | null;
  matches_superseded: number | null;
  matches_unchanged: number | null;
  correctness_ok: boolean | null;
  emails_sent: number | null;
  emails_failed: number | null;
  emails_skipped_demo: number | null;
  purged: boolean | null; // an admin deleted this upload's users (the run history stays)
  reference: boolean; // the largest completed upload run, always listed (the measured funnel)
}

export interface CrawlHealth {
  latest_run: { run_id: string; started_at: string; finished_at: string | null } | null;
  pages: { channel: Channel; status: string; pages: number; llm_tokens: number }[];
  products: { channel: Channel; products: number; verified: number; lenders: number }[];
}

export interface WorkflowError {
  id: number;
  workflow: string;
  node: string | null;
  message: string;
  created_at: string;
}

export interface UploadProgress {
  job: {
    job_id: string;
    status: "AWAITING_UPLOAD" | "PROCESSING" | "COMPLETED" | "FAILED" | "EXPIRED" | "RETRYING";
    total_rows: number | null;
    inserted: number | null;
    updated: number | null;
    unchanged: number | null;
    rejected: number | null;
    error: string | null;
    match_status: "RUNNING" | "DONE" | "FAILED" | null;
  };
  rejects: { row_number: number; reason: string; raw_line: string }[];
  match_run: Partial<Run> | null;
  notifications: Record<string, number>;
}

export interface Band {
  ord: number;
  n: number;
}

export interface Analytics {
  users: number;
  matches: number;
  users_with_eligible: number;
  users_without_matches: number;
  income_bands: Band[];
  score_bands: Band[];
  age_bands: Band[];
  employment: { key: Employment; n: number }[];
  matches_per_user: Band[];
  tiers: { key: Tier; n: number }[];
  channels: { key: Channel; n: number }[];
  top_lenders: { lender: string; users: number; eligible_users: number }[];
}

export interface SavedProfile extends Profile {
  user_id: string;
  name: string | null;
  saved_at: string;
  matches: number;
  eligible: number;
  source: "csv" | "instant_check";
}

export interface Account {
  account_id: string;
  email: string;
  daily_picks: boolean;
  created_at: string;
  profiles: SavedProfile[];
  is_admin: boolean; // in the Cognito `admin` group: may delete uploaded data
}

/** One bulk upload as a record (GET /uploads): counts only, no personal data. */
export interface UploadRecord {
  job_id: string;
  original_filename: string | null;
  status: "AWAITING_UPLOAD" | "PROCESSING" | "COMPLETED" | "FAILED";
  created_at: string;
  completed_at: string | null;
  total_rows: number | null;
  inserted: number | null;
  updated: number | null;
  unchanged: number | null;
  rejected: number | null;
  match_status: "RUNNING" | "DONE" | "FAILED" | null;
  matched_at: string | null;
  purged_at: string | null;
  users_now: number;
  matches: number;
  emails_sent: number;
}
