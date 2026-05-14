-- Episodic memory schema. Append-only, parameterized writes.
-- Tables carry schema_version on each row so old data stays parseable.

CREATE TABLE IF NOT EXISTS runs (
    id              TEXT PRIMARY KEY,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    company         TEXT NOT NULL,
    market          TEXT NOT NULL,
    status          TEXT NOT NULL,         -- 'in_progress' | 'completed' | 'failed' | 'aborted_cost' | 'aborted_retries'
    total_cost_usd  REAL NOT NULL DEFAULT 0.0,
    brief_path      TEXT,
    schema_version  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS skill_invocations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    skill_name          TEXT NOT NULL,
    attempt             INTEGER NOT NULL,
    model               TEXT NOT NULL,
    input_json          TEXT NOT NULL,
    output_json         TEXT,
    eval_passed         INTEGER,           -- nullable: chunks 1-5 don't run evals
    eval_details_json   TEXT,
    input_tokens        INTEGER NOT NULL DEFAULT 0,
    output_tokens       INTEGER NOT NULL DEFAULT 0,
    cost_usd            REAL NOT NULL DEFAULT 0.0,
    duration_ms         INTEGER,
    started_at          TEXT NOT NULL,
    schema_version      INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_skill_inv_run_id ON skill_invocations(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at);

-- Outer-loop feedback table (populated by `geoquery feedback`, chunk 14).
CREATE TABLE IF NOT EXISTS human_edits (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                  TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    original_brief_path     TEXT NOT NULL,
    edited_brief_path       TEXT NOT NULL,
    diff_summary            TEXT NOT NULL,
    captured_at             TEXT NOT NULL,
    schema_version          INTEGER NOT NULL DEFAULT 1
);

-- Production sample stream (v2 chunk 7). A small % of completed runs get
-- flagged for human review. The reviewer's rating is compared against the
-- judges' verdicts at run-time to surface judge-vs-human divergence (chunk 8
-- dashboard banner). reviewed_at IS NULL means "pending".
CREATE TABLE IF NOT EXISTS human_reviews (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                   TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    sampled_at               TEXT NOT NULL,
    reviewed_at              TEXT,
    reviewer_rating_overall  INTEGER,                -- 1-5; NULL = pending
    reviewer_ratings_by_dim  TEXT,                   -- JSON: {brand_voice: 5, ...}
    reviewer_notes           TEXT,
    schema_version           INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_human_reviews_run_id ON human_reviews(run_id);
CREATE INDEX IF NOT EXISTS idx_human_reviews_pending ON human_reviews(reviewed_at);

-- Meta-agent proposals (v3 chunk 2). One row per change the meta-agent
-- proposes. `target_pattern` is the stable signal_id from meta/analyze.py;
-- analyze() reads this table to skip patterns it already proposed and got
-- rejected/inconclusive on within the cooldown window. The baseline_* columns
-- are populated post-merge by meta/measure.py (chunk 9).
CREATE TABLE IF NOT EXISTS meta_proposals (
    id                             INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at                     TEXT NOT NULL,
    target_pattern                 TEXT NOT NULL,   -- analyze() signal_id
    change_type                    TEXT NOT NULL,   -- 'prompt'|'rubric'|'eval'|'fewshot'
    hypothesis                     TEXT NOT NULL,
    branch                         TEXT,
    pr_number                      INTEGER,
    status                         TEXT NOT NULL DEFAULT 'proposed',
        -- 'proposed'|'rejected'|'inconclusive'|'merged'|'measured'|'reverted'
    merged_at                      TEXT,
    baseline_regression_pass_rate  REAL,
    baseline_window_json           TEXT,
    schema_version                 INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_meta_proposals_pattern ON meta_proposals(target_pattern);

-- Winning patterns (v3 chunk 5). Each row is one periodic extraction:
-- structural patterns common to the top-N highest-scoring briefs ("high-
-- scorers name a specific persona pain in the angle; 5-6 sections; ..."),
-- distilled by an LLM call. Append-only; the drafter reads the most recent
-- row and injects it as guidance. Populated by `geoquery extract-patterns`.
CREATE TABLE IF NOT EXISTS winning_patterns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    extracted_at    TEXT NOT NULL,
    briefs_analyzed INTEGER NOT NULL,
    min_eval_score  REAL NOT NULL,      -- score floor of the analyzed set
    patterns_json   TEXT NOT NULL,      -- JSON list[str] of structural patterns
    schema_version  INTEGER NOT NULL DEFAULT 1
);
