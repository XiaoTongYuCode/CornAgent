#!/usr/bin/env bash
set -euo pipefail
umask 077

tls=/etc/cornagent
pgdata=/var/lib/pgsql/17/data
redisdata=/var/lib/cornagent-redis
backup=/var/backups/cornagent

if ! openssl x509 -checkend 2592000 -noout -in "$tls/server.crt"; then
    openssl x509 -req -in "$tls/server.csr" -CA "$tls/ca.crt" \
        -CAkey "$tls/ca.key" -CAserial "$tls/ca.srl" -days 365 \
        -extfile "$tls/server.ext" -out "$tls/server.next.crt"
    openssl verify -CAfile "$tls/ca.crt" "$tls/server.next.crt"
    mv "$tls/server.next.crt" "$tls/server.crt"
    install -o postgres -g postgres -m 600 "$tls/server.crt" "$pgdata/server.crt"
    install -o cornagent-redis -g cornagent-redis -m 600 \
        "$tls/server.crt" "$redisdata/server.crt"
    systemctl reload postgresql-17
    systemctl restart cornagent-redis
fi

mkdir -p "$backup"
dump="$backup/cornagent-$(date -u +%Y%m%dT%H%M%SZ).dump"
runuser -u postgres -- /usr/pgsql-17/bin/pg_dump -p 55432 -Fc cornagent > "$dump.partial"
mv "$dump.partial" "$dump"
find "$backup" -maxdepth 1 -type f -name 'cornagent-*.dump' -mtime +7 -delete
