-- Separate read-only backend identity. Set credentials outside version control.
CREATE ROLE pyrogravity_api_reader LOGIN
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;
GRANT CONNECT ON DATABASE postgres TO pyrogravity_api_reader;
GRANT USAGE ON SCHEMA scientific TO pyrogravity_api_reader;
GRANT SELECT ON scientific.investigations, scientific.datasets,
    scientific.dataset_columns, scientific.records, scientific.measurements
TO pyrogravity_api_reader;

CREATE POLICY api_reader_select ON scientific.investigations FOR SELECT TO pyrogravity_api_reader USING (true);
CREATE POLICY api_reader_select ON scientific.datasets FOR SELECT TO pyrogravity_api_reader USING (true);
CREATE POLICY api_reader_select ON scientific.dataset_columns FOR SELECT TO pyrogravity_api_reader USING (true);
CREATE POLICY api_reader_select ON scientific.records FOR SELECT TO pyrogravity_api_reader USING (true);
CREATE POLICY api_reader_select ON scientific.measurements FOR SELECT TO pyrogravity_api_reader USING (true);
