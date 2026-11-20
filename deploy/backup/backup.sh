#!/bin/sh
# Nightly backup at 02:00 Asia/Manila; keeps the newest 14 files (NFR-REL-03).
# Runs inside the backup container (mysql:8.4 image).
set -eu
keep=14
while true; do
  now=$(TZ=Asia/Manila date +%H%M)
  if [ "$now" = "0200" ]; then
    f="/backups/gardekalinga-$(TZ=Asia/Manila date +%Y%m%d-%H%M).sql.gz"
    mysqldump -h mysql -u root -p"$MYSQL_ROOT_PASSWORD" --single-transaction --routines --triggers gardekalinga | gzip > "$f.tmp"
    mv "$f.tmp" "$f"
    echo "backup written: $f"
    # Retention: delete the oldest backups beyond the newest $keep.
    count=$(ls -1 /backups/gardekalinga-*.sql.gz | wc -l)
    for old in $(ls -1t /backups/gardekalinga-*.sql.gz | tail -n +$((keep + 1))); do
      rm -- "$old"
    done
    echo "backups kept: $((count > keep ? keep : count))"
    sleep 61
  fi
  sleep 30
done
