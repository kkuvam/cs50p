#!/bin/bash
# Nightly PostgreSQL backup with restore verification. Runs on macOS bash 3.2.
# Connects over the local Unix socket as the invoking OS user (no password).
set -euo pipefail
umask 077

PGDATABASE_NAME="${PGDATABASE_NAME:-exomiser}"
BACKUP_DIR="${BACKUP_DIR:-/Users/priya/Sites/backup/pg}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
OFFSITE_DIR="${OFFSITE_DIR:-}"

TABLES="users individuals analyses users_history individuals_history analyses_history"
EXPECTED_TRIGGERS=9
TMP_DB="exomiser_backupcheck_$$"
TMP_CREATED=0
PARTIAL=""
OFF_PARTIAL_DUMP=""
OFF_PARTIAL_SUM=""
RC=0
WORK=""
ERRF=""

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }
fail() { log "ERROR: $*"; exit 1; }

cleanup() {
  local rc=$?
  if [ "$TMP_CREATED" = 1 ]; then
    if dropdb --if-exists "$TMP_DB" 2>/dev/null; then
      log "dropped temporary database $TMP_DB"
    else
      log "ERROR: could not drop temporary database $TMP_DB"
      if [ "$rc" -eq 0 ]; then rc=1; fi
    fi
  fi
  if [ -n "$PARTIAL" ]; then rm -f "$PARTIAL"; fi
  if [ -n "$OFF_PARTIAL_DUMP" ]; then rm -f "$OFF_PARTIAL_DUMP"; fi
  if [ -n "$OFF_PARTIAL_SUM" ]; then rm -f "$OFF_PARTIAL_SUM"; fi
  if [ -n "$WORK" ]; then rm -rf "$WORK"; fi
  if [ "$rc" -ne 0 ]; then log "backup FAILED (exit $rc)"; fi
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT HUP

# Log the exit code of a failed tool and, only if stderr looks free of data,
# its first line. Tool stderr can quote table rows, so it is never logged raw.
log_tool_failure() { # $1 = tool name, $2 = exit code
  local line=""
  if [ -s "$ERRF" ] && ! grep -qiE 'COPY|CONTEXT|DETAIL|Command was' "$ERRF"; then
    line=$(head -n 1 "$ERRF" | cut -c1-120)
    case "$line" in
      "$1:"*) ;;
      *) line="" ;;
    esac
  fi
  if [ -n "$line" ]; then
    log "ERROR: $1 exit code $2: $line"
  else
    log "ERROR: $1 exit code $2 (see exit code; stderr withheld to keep patient data out of the log)"
  fi
}

# Delete our own exomiser-*.dump / .sha256 files older than RETENTION_DAYS in a
# directory, never the newest dump or its checksum.
prune_dir() {
  local dir="$1" newest f
  newest=$(ls -1 "$dir"/exomiser-*.dump 2>/dev/null | sort | tail -n 1 || true)
  [ -n "$newest" ] || return 0
  find "$dir" -maxdepth 1 -type f \( -name 'exomiser-*.dump' -o -name 'exomiser-*.dump.sha256' \) \
    -mtime +"$RETENTION_DAYS" | while IFS= read -r f; do
    if [ "$f" = "$newest" ] || [ "$f" = "$newest.sha256" ]; then continue; fi
    rm -f "$f" && log "pruned $(basename "$f") from $dir"
  done
}

# Copy dump + checksum to a directory via .partial names, verify, then rename.
# Returns non-zero (after removing partials) on any failure.
offsite_copy() { # $1 = dump, $2 = checksum file, $3 = destination dir
  local name sname want got
  name=$(basename "$1"); sname=$(basename "$2")
  OFF_PARTIAL_DUMP="$3/$name.partial"
  OFF_PARTIAL_SUM="$3/$sname.partial"
  if cp "$1" "$OFF_PARTIAL_DUMP" && cp "$2" "$OFF_PARTIAL_SUM"; then
    want=$(awk '{print $1}' "$2")
    got=$(shasum -a 256 "$OFF_PARTIAL_DUMP" | awk '{print $1}')
    if [ -n "$want" ] && [ "$want" = "$got" ] \
      && mv "$OFF_PARTIAL_DUMP" "$3/$name" && mv "$OFF_PARTIAL_SUM" "$3/$sname"; then
      OFF_PARTIAL_DUMP=""; OFF_PARTIAL_SUM=""
      return 0
    fi
  fi
  rm -f "$OFF_PARTIAL_DUMP" "$OFF_PARTIAL_SUM"
  OFF_PARTIAL_DUMP=""; OFF_PARTIAL_SUM=""
  return 1
}

count_rows() { # $1 = database, $2 = table
  psql -X -At -d "$1" -c "SELECT count(*) FROM public.$2"
}

main() {
  local s list name dump ents t live copy trig mismatch rc
  mkdir -p "$BACKUP_DIR"
  WORK=$(mktemp -d "${TMPDIR:-/tmp}/pg_backup.XXXXXX")
  ERRF="$WORK/stderr"
  log "tools: $(pg_dump --version)"

  # Drop leftovers from earlier killed runs.
  list=$(psql -X -At -d postgres -c "SELECT datname FROM pg_database WHERE datname LIKE 'exomiser\_backupcheck\_%'") \
    || fail "could not list leftover temp databases"
  while IFS= read -r s; do
    [ -n "$s" ] || continue
    if dropdb --if-exists "$s" 2>/dev/null; then
      log "dropped leftover temporary database $s"
    else
      log "ERROR: could not drop leftover temporary database $s"
      RC=1
    fi
  done <<< "$list"

  name="exomiser-$(date +%Y%m%d-%H%M%S).dump"
  dump="$BACKUP_DIR/$name"
  PARTIAL="$dump.partial"

  log "dumping $PGDATABASE_NAME to $name"
  rc=0
  pg_dump -Fc -d "$PGDATABASE_NAME" -f "$PARTIAL" 2>"$ERRF" || rc=$?
  if [ "$rc" -ne 0 ]; then log_tool_failure pg_dump "$rc"; exit 1; fi
  mv "$PARTIAL" "$dump"
  PARTIAL=""
  (cd "$BACKUP_DIR" && shasum -a 256 "$name" > "$name.sha256") || fail "checksum failed"
  log "dump written: $(stat -f %z "$dump") bytes"

  # Verify: table of contents, then a real restore into a throwaway database.
  ents=$(pg_restore --list "$dump" 2>"$ERRF" | grep -vc '^;' || true)
  [ "$ents" -gt 0 ] || fail "dump $name has no entries (kept for inspection)"
  log "pg_restore --list ok: $ents entries"

  createdb "$TMP_DB" 2>/dev/null || fail "could not create $TMP_DB"
  TMP_CREATED=1
  rc=0
  pg_restore --no-owner --exit-on-error -d "$TMP_DB" "$dump" 2>"$ERRF" || rc=$?
  if [ "$rc" -ne 0 ]; then log_tool_failure pg_restore "$rc"; fail "restore into $TMP_DB failed (dump kept)"; fi
  log "restored into $TMP_DB"

  mismatch=0
  for t in $TABLES; do
    live=$(count_rows "$PGDATABASE_NAME" "$t") || fail "count failed for $t (live)"
    copy=$(count_rows "$TMP_DB" "$t") || fail "count failed for $t (restored)"
    if [ "$live" = "$copy" ]; then
      log "rows $t: $copy ok"
    else
      log "ERROR: rows $t: live=$live restored=$copy"
      mismatch=1
    fi
  done
  trig=$(psql -X -At -d "$TMP_DB" -c "SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal") \
    || fail "trigger count failed (restored)"
  if [ "$trig" = "$EXPECTED_TRIGGERS" ]; then
    log "triggers: $trig ok"
  else
    log "ERROR: triggers: found $trig, expected $EXPECTED_TRIGGERS"
    mismatch=1
  fi
  [ "$mismatch" = 0 ] || fail "verification failed, dump $name kept (a write during the dump can cause a count difference; rerun to confirm)"
  log "verification passed"

  if [ -n "$OFFSITE_DIR" ]; then
    if [ -d "$OFFSITE_DIR" ]; then
      offsite_copy "$dump" "$dump.sha256" "$OFFSITE_DIR" || fail "offsite copy to $OFFSITE_DIR failed or checksum mismatch"
      log "offsite copy verified in $OFFSITE_DIR"
      prune_dir "$OFFSITE_DIR"
    else
      log "WARNING: OFFSITE_DIR $OFFSITE_DIR does not exist (drive not mounted?), no offsite copy made"
      RC=1
    fi
  fi

  prune_dir "$BACKUP_DIR"
  if [ "$RC" = 0 ]; then log "backup complete: $name"; fi
}

main
exit "$RC"
