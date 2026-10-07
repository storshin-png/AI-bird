FROM postgis/postgis:16-3.4

# Образ PostGIS 3.4 собран на Debian 11. Его репозитории и PGDG для bullseye
# отдаются из архивов: прежние адреса отвечают 404.
# Загрузчик TimescaleDB ставим той же версии, что и расширение: иначе
# CREATE EXTENSION ищет скрипты более новой версии и падает.
RUN set -eux; \
    sed -i \
        -e 's|http://deb.debian.org/debian-security|http://archive.debian.org/debian-security|g' \
        -e 's|http://deb.debian.org/debian|http://archive.debian.org/debian|g' \
        -e 's|http://security.debian.org/debian-security|http://archive.debian.org/debian-security|g' \
        /etc/apt/sources.list; \
    sed -i 's|http://apt.postgresql.org/pub/repos/apt|https://apt-archive.postgresql.org/pub/repos/apt|g' /etc/apt/sources.list.d/pgdg.list; \
    printf 'Acquire::Check-Valid-Until "false";\n' > /etc/apt/apt.conf.d/99no-check-valid; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg; \
    curl -fsSL https://packagecloud.io/timescale/timescaledb/gpgkey \
        | gpg --dearmor -o /etc/apt/trusted.gpg.d/timescaledb.gpg; \
    echo "deb https://packagecloud.io/timescale/timescaledb/debian/ bullseye main" \
        > /etc/apt/sources.list.d/timescaledb.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        postgresql-16=16.15-1.pgdg11+2 \
        timescaledb-2-loader-postgresql-16=2.17.2~debian11 \
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
