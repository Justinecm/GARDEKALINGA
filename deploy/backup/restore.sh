#!/bin/sh
# Restore a backup into the running stack:
#   make restore FILE=path/to/gardekalinga-YYYYMMDD-HHMM.sql.gz
# Copy a file out of the backups volume first, for example:
#   docker compose -f deploy/docker-compose.yml cp backup:/backups/<file> .
set -eu
FILE="${1:?usage: restore.sh <backup.sql.gz>}"
echo "Restoring $FILE into gardekalinga (current data will be replaced)..."
gunzip -c "$FILE" | docker compose -f deploy/docker-compose.yml --env-file .env exec -T mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" gardekalinga'
echo "Done. Check: curl -k https://\$GK_DOMAIN/api/ready"
