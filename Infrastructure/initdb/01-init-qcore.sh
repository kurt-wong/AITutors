#!/bin/sh
# AITutor PostgreSQL bootstrap (runs only on first start of an empty data
# volume). Creates the non-privileged application role and the two project
# databases. The bootstrap superuser ($POSTGRES_USER) is used for this
# initialisation only and is never the application account.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "postgres" <<-EOSQL
    CREATE ROLE qcore_app
        LOGIN
        PASSWORD '${QCORE_APP_PASSWORD}'
        NOSUPERUSER
        NOCREATEDB
        NOCREATEROLE
        NOINHERIT;

    CREATE DATABASE qcore_dev_test OWNER qcore_app;
    CREATE DATABASE qcore_dev_test_migrate OWNER qcore_app;
EOSQL
