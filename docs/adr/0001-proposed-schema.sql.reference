-- sources: una por investigación PSI
CREATE TABLE sources (id text PRIMARY KEY, psi_code text NOT NULL, title text, nasa_psi_url text, doi text, nasa_version text);
-- datasets: una por CSV
CREATE TABLE datasets (id text PRIMARY KEY, psi_code text, table_name text, source_filename text, sha256 text UNIQUE, encoding text, row_count int, informative_row_count int, data_scope text, quantitative_status text, observations text, version text);
-- trials: una por fila no vacía
CREATE TABLE trials (id text PRIMARY KEY, dataset_id text REFERENCES datasets(id), source_record int, label text, is_empty bool DEFAULT false, anomalies text[], quantitative_candidate bool, attributes jsonb);
CREATE UNIQUE INDEX uq_trial ON trials(dataset_id, source_record);
-- variables: por (dataset, column)
CREATE TABLE variables (id text PRIMARY KEY, dataset_id text REFERENCES datasets(id), column_name text, source_header text, unit text, unit_known bool DEFAULT false, canonical_variable text);
-- measurements (formato largo)
CREATE TABLE measurements (id bigserial PRIMARY KEY, trial_id text REFERENCES trials(id), variable_id text REFERENCES variables(id), value numeric, raw_value text, status text CHECK (status IN ('exact','approximate','range','bound','multiple_values','ambiguous','source_error','annotation','missing_marker')), unit text, t_seconds double precision);
CREATE UNIQUE INDEX uq_meas ON measurements(trial_id, variable_id);
-- experiment_stats, documents, document_passages, ai_analyses
CREATE TABLE experiment_stats (id bigserial PRIMARY KEY, experiment_id text, variable text, metric text, value numeric, unit text, dataset_version text);
CREATE TABLE documents (id text PRIMARY KEY, version text NOT NULL, source_id text);
CREATE TABLE document_passages (id text PRIMARY KEY, document_id text REFERENCES documents(id), document_version text, passage text, source_id text);
CREATE TABLE ai_analyses (id text PRIMARY KEY, status text, answer text, claims jsonb, chart jsonb, limitations jsonb, confidence text, model text, data_version text, corpus_version text, validation_report jsonb, created_at timestamptz DEFAULT now());

CREATE INDEX idx_var_value ON measurements(variable_id, value);
CREATE INDEX idx_dataset ON measurements(trial_id);

ALTER TABLE sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE datasets ENABLE ROW LEVEL SECURITY;
ALTER TABLE trials ENABLE ROW LEVEL SECURITY;
ALTER TABLE variables ENABLE ROW LEVEL SECURITY;
ALTER TABLE measurements ENABLE ROW LEVEL SECURITY;
ALTER TABLE experiment_stats ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_passages ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_analyses ENABLE ROW LEVEL SECURITY;
