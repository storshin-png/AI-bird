FROM postgis/postgis:16-3.4

# Образ PostGIS 3.4 — это PostgreSQL 16.4 на Debian 11.
# TimescaleDB новее 2.17.2 требует PostgreSQL >= 16.6 и утащил бы другой сервер.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg; \
    curl -fsSL https://packagecloud.io/timescale/timescaledb/gpgkey \
        | gpg --dearmor -o /etc/apt/trusted.gpg.d/timescaledb.gpg; \
    echo "deb https://packagecloud.io/timescale/timescaledb/debian/ bullseye main" \
        > /etc/apt/sources.list.d/timescaledb.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        timescaledb-2-2.17.2-postgresql-16=2.17.2~debian11; \
    if grep -Eq '^#?shared_preload_libraries' /usr/share/postgresql/postgresql.conf.sample; then \
        sed -ri "s/^#?shared_preload_libraries\s*=.*/shared_preload_libraries = 'timescaledb'/" \
            /usr/share/postgresql/postgresql.conf.sample; \
    else \
        echo "shared_preload_libraries = 'timescaledb'" >> /usr/share/postgresql/postgresql.conf.sample; \
    fi; \
    apt-get purge -y curl gnupg; \
    rm -rf /var/lib/apt/lists/*

COPY init/20_timescaledb.sql /docker-entrypoint-initdb.d/20_timescaledb.sql
