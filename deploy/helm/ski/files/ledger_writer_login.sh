# shellcheck shell=sh
# ============================================================================
# SKI Framework v3.2.0 — set the ski_ledger_writer login password
# ============================================================================
# Runs on FIRST init only, from /docker-entrypoint-initdb.d/ (mounted as
# 04-ledger-writer-login.sh by docker-compose and the Helm chart), after
# append_only.sql has created the role. The official postgres image SOURCES
# non-executable *.sh init files, so this file sets no shell options and
# exits nowhere; it only runs one psql command.
#
# The password comes from $SKI_LEDGER_WRITER_PASSWORD. It is passed to psql
# as a variable and quoted by psql (:'var'), never spliced into SQL text.
# If the variable is empty the role keeps NO password, so the runtime cannot
# log in at all (fail closed) — set one later as the owner with
#   ALTER ROLE ski_ledger_writer PASSWORD '<secret>';
#
# Existing ledgers (created before v3.2.0) never re-run init scripts: apply
# append_only.sql as the owner, then the ALTER ROLE above. See the CHANGELOG.
# ============================================================================

if [ -n "${SKI_LEDGER_WRITER_PASSWORD:-}" ]; then
    printf '%s\n' "ledger_writer_login.sh: setting the ski_ledger_writer password."
    PGHOST='' PGHOSTADDR='' psql -v ON_ERROR_STOP=1 --no-psqlrc --no-password \
        --username "$POSTGRES_USER" --dbname "${POSTGRES_DB:-$POSTGRES_USER}" \
        --set=ski_writer_pw="$SKI_LEDGER_WRITER_PASSWORD" <<'EOSQL'
ALTER ROLE ski_ledger_writer WITH LOGIN PASSWORD :'ski_writer_pw';
EOSQL
else
    printf '%s\n' "ledger_writer_login.sh: WARNING: SKI_LEDGER_WRITER_PASSWORD is empty;" \
        "ski_ledger_writer has no password and the SKI Model cannot connect until the owner sets one." >&2
fi
