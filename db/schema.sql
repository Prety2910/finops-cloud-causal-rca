-- Minimum schema from technical_plan.md §3.1 (+ agent_log, feedback)
CREATE EXTENSION IF NOT EXISTS timescaledb;  -- remove this line if using plain Postgres

CREATE TABLE IF NOT EXISTS metrics (ts TIMESTAMPTZ NOT NULL, case_id TEXT, service TEXT, metric TEXT, value DOUBLE PRECISION);
CREATE INDEX IF NOT EXISTS metrics_idx ON metrics (case_id, service, metric, ts);
CREATE TABLE IF NOT EXISTS logs (ts TIMESTAMPTZ NOT NULL, case_id TEXT, service TEXT, level TEXT, message TEXT);
CREATE INDEX IF NOT EXISTS logs_idx ON logs (case_id, service, ts);
CREATE TABLE IF NOT EXISTS spans (ts TIMESTAMPTZ NOT NULL, case_id TEXT, trace_id TEXT, span_id TEXT, parent_id TEXT,
                      service TEXT, operation TEXT, duration_ms DOUBLE PRECISION, status INT);
CREATE TABLE IF NOT EXISTS change_events (event_id TEXT PRIMARY KEY, case_id TEXT, ts TIMESTAMPTZ, service TEXT,
                      type TEXT CHECK (type IN ('deploy','config')), detail JSONB, is_decoy BOOL);
CREATE TABLE IF NOT EXISTS cost (ts TIMESTAMPTZ NOT NULL, case_id TEXT, service TEXT, component TEXT, inr DOUBLE PRECISION);
CREATE TABLE IF NOT EXISTS incidents (incident_id TEXT PRIMARY KEY, case_id TEXT, t_anomaly TIMESTAMPTZ,
                      detected_by TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS rca_results (incident_id TEXT, rank INT, candidate TEXT, candidate_type TEXT,
                      score DOUBLE PRECISION, confidence DOUBLE PRECISION,
                      cost_share_inr DOUBLE PRECISION, causal_path JSONB, module_scores JSONB);
CREATE TABLE IF NOT EXISTS explanations (incident_id TEXT, tier INT, model TEXT, input_tokens INT,
                      output_tokens INT, cost_inr DOUBLE PRECISION, latency_ms INT,
                      reused_from TEXT, body JSONB, ts TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS ig_nodes (node_id TEXT PRIMARY KEY, kind TEXT, attrs JSONB);
CREATE TABLE IF NOT EXISTS ig_edges (src TEXT, dst TEXT, kind TEXT, attrs JSONB);
CREATE TABLE IF NOT EXISTS agent_log (ts TIMESTAMPTZ DEFAULT now(), session_id TEXT, tool TEXT, args JSONB, n_rows INT);
CREATE TABLE IF NOT EXISTS feedback (incident_id TEXT, ts TIMESTAMPTZ DEFAULT now(), thumbs INT, note TEXT);

-- Read-only role for the agent (§3.1). Change the password outside dev.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rca_ro') THEN
    CREATE ROLE rca_ro LOGIN PASSWORD 'rca_ro';
  END IF;
END $$;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO rca_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO rca_ro;
