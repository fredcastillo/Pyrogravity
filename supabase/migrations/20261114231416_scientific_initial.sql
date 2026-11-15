-- Supabase CLI applies this DDL and records its version in one transaction.
-- Existing tables cause the migration to fail.

CREATE SCHEMA IF NOT EXISTS scientific;

CREATE TABLE scientific.investigations (
    psi_code text PRIMARY KEY CHECK (psi_code ~ '^PSI-[0-9]+$'),
    investigation_name text NOT NULL CHECK (btrim(investigation_name) <> ''),
    nasa_psi_url text NOT NULL CHECK (btrim(nasa_psi_url) <> '')
);

-- A dataset represents one version of a source CSV at its manifest path.
CREATE TABLE scientific.datasets (
    dataset_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    psi_code text NOT NULL REFERENCES scientific.investigations (psi_code),
    relative_path text NOT NULL CHECK (btrim(relative_path) <> ''),
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    encoding text NOT NULL CHECK (btrim(encoding) <> ''),
    delimiter text NOT NULL CHECK (char_length(delimiter) = 1),
    row_count integer NOT NULL CHECK (row_count >= 0),
    column_count integer NOT NULL CHECK (column_count > 0),
    data_scope text NOT NULL CHECK (data_scope IN (
        'experimental_summary', 'conditions_and_counts', 'conditions_only', 'metadata_only'
    )),
    quantitative_criteria jsonb NOT NULL CHECK (jsonb_typeof(quantitative_criteria) = 'object'),
    source_observations text NOT NULL,
    quality_reference text,
    UNIQUE (psi_code, relative_path, sha256)
);

-- Ordinal starts at one and follows the original CSV header order.
CREATE TABLE scientific.dataset_columns (
    dataset_id bigint NOT NULL REFERENCES scientific.datasets (dataset_id),
    column_ordinal integer NOT NULL CHECK (column_ordinal > 0),
    column_name text NOT NULL CHECK (btrim(column_name) <> ''),
    source_header text NOT NULL,
    source_unit text,
    value_kind text NOT NULL CHECK (value_kind IN ('text', 'integer', 'decimal')),
    PRIMARY KEY (dataset_id, column_ordinal),
    UNIQUE (dataset_id, column_name),
    UNIQUE (dataset_id, column_ordinal, value_kind)
);

-- Source records are CSV rows, including blank rows, notes and partial summaries.
-- Original values are an ordered JSON array of strings, including empty strings.
-- Text statuses use column_name keys. Numeric statuses are stored in measurements.
CREATE TABLE scientific.records (
    dataset_id bigint NOT NULL REFERENCES scientific.datasets (dataset_id),
    source_record integer NOT NULL CHECK (source_record > 0),
    original_values jsonb NOT NULL CHECK (
        jsonb_typeof(original_values) = 'array'
        AND NOT jsonb_path_exists(original_values, '$[*] ? (@.type() != "string")')
    ),
    text_cell_statuses jsonb NOT NULL CHECK (jsonb_typeof(text_cell_statuses) = 'object'),
    source_row_empty boolean NOT NULL,
    quantitative_candidate boolean NOT NULL,
    quality_flags text[] NOT NULL,
    PRIMARY KEY (dataset_id, source_record),
    CHECK (NOT (source_row_empty AND quantitative_candidate))
);

-- Each entry interprets one numeric source field. Read raw text from original_values
-- at JSON index column_ordinal - 1 and the declared unit from dataset_columns.
CREATE TABLE scientific.measurements (
    dataset_id bigint NOT NULL,
    source_record integer NOT NULL,
    column_ordinal integer NOT NULL,
    value_kind text NOT NULL CHECK (value_kind IN ('integer', 'decimal')),
    interpretation_status text NOT NULL CHECK (interpretation_status IN (
        'exact', 'blank', 'missing_marker', 'approximate', 'bound', 'range',
        'multiple_values', 'annotation', 'ambiguous', 'source_error'
    )),
    numeric_value numeric,
    PRIMARY KEY (dataset_id, source_record, column_ordinal),
    FOREIGN KEY (dataset_id, source_record)
        REFERENCES scientific.records (dataset_id, source_record),
    FOREIGN KEY (dataset_id, column_ordinal, value_kind)
        REFERENCES scientific.dataset_columns (dataset_id, column_ordinal, value_kind),
    CHECK ((interpretation_status = 'exact') = (numeric_value IS NOT NULL)),
    CHECK (numeric_value NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)),
    CHECK (value_kind <> 'integer' OR numeric_value = trunc(numeric_value))
);

-- Support lookup by source column, including checks of the column foreign key.
CREATE INDEX measurements_by_source_column
    ON scientific.measurements (dataset_id, column_ordinal);

CREATE INDEX records_quantitative_candidates
    ON scientific.records (dataset_id, source_record)
    WHERE quantitative_candidate;

-- SQL-created tables require explicit RLS. Access policies are defined separately.
ALTER TABLE scientific.investigations ENABLE ROW LEVEL SECURITY;
ALTER TABLE scientific.datasets ENABLE ROW LEVEL SECURITY;
ALTER TABLE scientific.dataset_columns ENABLE ROW LEVEL SECURITY;
ALTER TABLE scientific.records ENABLE ROW LEVEL SECURITY;
ALTER TABLE scientific.measurements ENABLE ROW LEVEL SECURITY;
