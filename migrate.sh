#!/bin/sh
set -e

echo "=== MODE MIGRATION ==="

# override DB user
export POSTGRES_USER=$POSTGRES_MIGRATION_USER
export POSTGRES_PASSWORD=$POSTGRES_MIGRATION_PASSWORD

echo "User migration: $POSTGRES_USER"

python manage.py migrate --noinput

echo "=== MIGRATION OK ==="