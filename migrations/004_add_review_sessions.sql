-- SPEC-38: Session persistence for Gen3 review recovery
-- Apply in CONTRACT business database (same project as upload_jobs).

CREATE TABLE IF NOT EXISTS review_sessions (
  task_id TEXT PRIMARY KEY,
  status TEXT NOT NULL DEFAULT 'created',
  domain_id TEXT NOT NULL,
  domain_subtype TEXT DEFAULT '',
  our_party TEXT DEFAULT '',
  language TEXT DEFAULT 'zh-CN',

  current_clause_index INTEGER DEFAULT 0,
  current_clause_id TEXT DEFAULT '',
  total_clauses INTEGER DEFAULT 0,
  is_complete BOOLEAN DEFAULT FALSE,
  is_interrupted BOOLEAN DEFAULT FALSE,
  error TEXT,

  graph_state JSONB,

  graph_run_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_review_sessions_status ON review_sessions(status);

ALTER TABLE review_sessions
  DROP CONSTRAINT IF EXISTS review_sessions_status_check;

ALTER TABLE review_sessions
  ADD CONSTRAINT review_sessions_status_check
  CHECK (status IN ('created','uploading','reviewing','interrupted','completed','failed'));
