#!/bin/bash
# Two database users (C-9): the app user has no DDL rights at runtime; the migrate
# user owns the schema and is used only by `make migrate`.
set -euo pipefail
mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" <<SQL
CREATE USER IF NOT EXISTS 'gk_app'@'%' IDENTIFIED BY '${MYSQL_PASSWORD}';
CREATE USER IF NOT EXISTS 'gk_migrate'@'%' IDENTIFIED BY '${MYSQL_MIGRATE_PASSWORD}';
GRANT SELECT, INSERT, UPDATE, DELETE ON gardekalinga.* TO 'gk_app'@'%';
GRANT ALL PRIVILEGES ON gardekalinga.* TO 'gk_migrate'@'%';
FLUSH PRIVILEGES;
SQL
