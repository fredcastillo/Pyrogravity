"""Provide Supabase prerequisites in the isolated GitHub Actions database."""

import os

import psycopg
from psycopg.conninfo import conninfo_to_dict


def main() -> None:
    dsn = os.environ["PYRO_TEST_DATABASE_URL"]
    target = conninfo_to_dict(dsn)
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or target.get("host") not in {"127.0.0.1", "localhost"}
        or target.get("hostaddr") not in {None, "", "127.0.0.1", "::1"}
        or target.get("dbname") != "postgres"
        or target.get("user") != "postgres"
    ):
        raise SystemExit("Se requiere la base desechable local de GitHub Actions.")

    with psycopg.connect(dsn) as database:
        if database.execute("SELECT to_regnamespace('scientific')").fetchone()[0]:
            raise SystemExit("Se esperaba una base sin el esquema scientific.")
        database.execute("CREATE SCHEMA extensions")
        database.execute("CREATE EXTENSION vector WITH SCHEMA extensions")
        database.execute("CREATE ROLE anon NOLOGIN")
        database.execute("CREATE ROLE authenticated NOLOGIN")
        database.execute("CREATE ROLE service_role NOLOGIN")


if __name__ == "__main__":
    main()
