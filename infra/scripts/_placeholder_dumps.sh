#!/usr/bin/env bash
#
# Sourced helper: swap every committed `infra/v*/dump.sql.gz` for an empty
# gzip placeholder so a stack boots on a Flyway-bootstrapped database, and
# restore the committed dumps (and stop the stack) on exit.
#
# The caller sets INFRA_DIR before sourcing, then calls
# `placeholder_dumps_install`, which also installs the EXIT/INT/TERM trap.

placeholder_dumps_restore() {
  echo
  echo ">>> Cleaning up: stopping stack + restoring committed dumps"
  make -C "$INFRA_DIR" down >/dev/null 2>&1 || true
  for backup in "$INFRA_DIR"/v*/dump.sql.gz.codegen-backup; do
    [ -f "$backup" ] || continue
    mv -f "$backup" "${backup%.codegen-backup}"
    echo "    restored ${backup%.codegen-backup}"
  done
}

placeholder_dumps_install() {
  trap placeholder_dumps_restore EXIT INT TERM
  for dump in "$INFRA_DIR"/v*/dump.sql.gz; do
    [ -f "$dump" ] || continue
    backup="$dump.codegen-backup"
    if [ ! -f "$backup" ]; then
      mv "$dump" "$backup"
      echo ">>> Backed up $dump -> $backup"
    fi
    printf '' | gzip -9 > "$dump"
  done
}
