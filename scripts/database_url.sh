#!/bin/sh

normalize_database_url() {
  case "${DATABASE_URL:-}" in
    postgresql+psycopg://*) ;;
    postgresql://*) DATABASE_URL="postgresql+psycopg://${DATABASE_URL#postgresql://}" ;;
    postgres://*) DATABASE_URL="postgresql+psycopg://${DATABASE_URL#postgres://}" ;;
    *) return 1 ;;
  esac
  export DATABASE_URL
  export COGNISECT_DATABASE_URL="${DATABASE_URL}"
}
