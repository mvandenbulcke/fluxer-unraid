#!/bin/bash

auto_upgrade_file="$upgrade_dir/auto-upgrade.json"

auto_upgrade_info() {
  if command -v jq >/dev/null && upgrade_dir_is_private && retention_private_file "$auto_upgrade_file"; then
    jq -ces '
      select(length == 1) | .[0] |
      select(type == "object" and (.enabled | type == "boolean") and
        (.last_attempt == null or (.last_attempt | strings | test("^[0-9]{4}\\.[0-9]{4}\\.[0-9]{6}$")))) |
      {enabled,last_attempt}' "$auto_upgrade_file" 2>/dev/null && return 0
  fi
  printf '%s\n' '{"enabled":false,"last_attempt":null}'
}

write_auto_upgrade_settings() {
  local enabled=$1 last=$2 temporary
  if [[ ! -e "$upgrade_dir" && ! -L "$upgrade_dir" ]]; then mkdir -m 700 -- "$upgrade_dir" || return 1; fi
  upgrade_dir_is_private || return 1
  [[ ! -L "$auto_upgrade_file" && ( ! -e "$auto_upgrade_file" || -f "$auto_upgrade_file" ) ]] || return 1
  temporary=$(mktemp "$upgrade_dir/.auto-upgrade-XXXXXX") || return 1
  if ! jq -nc --argjson enabled "$enabled" --arg last "$last" \
    '{enabled: $enabled, last_attempt: ($last | select(length > 0) // null)}' > "$temporary" ||
    ! mv -f -- "$temporary" "$auto_upgrade_file"; then
    rm -f -- "$temporary"
    return 1
  fi
  sync_upgrade_storage "$upgrade_dir"
}

auto_upgrade_set() {
  local enabled last
  case "$1" in
    on) enabled=true ;;
    off) enabled=false ;;
    *) fail 'Use on or off to set automatic upgrades.' ;;
  esac
  retention_array_available || fail 'Start the Unraid array before you save automatic upgrade settings.'
  command -v jq >/dev/null || fail 'Automatic upgrades require jq.'
  last=$(auto_upgrade_info | jq -r '.last_attempt // ""')
  write_auto_upgrade_settings "$enabled" "$last" || fail 'Cannot save the automatic upgrade setting.'
  auto_upgrade_info
}

auto_upgrade_disable_for_restore() {
  local settings last
  settings=$(auto_upgrade_info)
  if ! jq -e '.enabled' <<< "$settings" >/dev/null; then return 0; fi
  last=$(jq -r '.last_attempt // ""' <<< "$settings")
  write_auto_upgrade_settings false "$last" || upgrade_fail 'Cannot disable automatic upgrades before the restore.'
}

auto_upgrade_stack_running() (
  local desired running service
  cd "$project_dir" || return 1
  desired=$(docker compose config --services 2>/dev/null) || return 1
  running=$(docker compose ps --status running --services 2>/dev/null) || return 1
  [[ $'\n'"$desired"$'\n' == *$'\napi\n'* ]] || return 1
  while IFS= read -r service; do
    [[ -n "$service" && "$service" != seaweedfs-init ]] || continue
    [[ $'\n'"$running"$'\n' == *$'\n'"$service"$'\n'* ]] || return 1
  done <<< "$desired"
)

auto_upgrade_run() {
  local settings last installed bundled status_file
  retention_array_available && command -v jq >/dev/null || return 0
  [[ -f "$project_dir/.env" && ! -L "$project_dir/.env" &&
    -f "$project_dir/.unraid-autostart" && ! -L "$project_dir/.unraid-autostart" ]] || return 0
  if upgrade_pending; then return 0; fi
  settings=$(auto_upgrade_info)
  jq -e '.enabled' <<< "$settings" >/dev/null || return 0
  for status_file in "$upgrade_status_file" "$restore_status_file"; do
    if upgrade_previous_status "$status_file" | jq -e '.phase == "recovery"' >/dev/null; then return 0; fi
  done
  read_upgrade_manifest || return 0
  last=$(jq -r '.last_attempt // ""' <<< "$settings")
  [[ "$last" != "$upgrade_target" ]] || return 0
  installed=$(release_version "$project_dir/UPSTREAM.json") || return 0
  bundled=$(release_version "$upgrade_bundle/UPSTREAM.json") || return 0
  [[ "$installed" == "$upgrade_source" && "$bundled" == "$upgrade_target" ]] || return 0
  [[ -z $(upgrade_layout_error) && -z $(upgrade_file_error) ]] || return 0
  (check_runtime && check_project_ownership && check_container_compose_files) >/dev/null 2>&1 || return 0
  auto_upgrade_stack_running || return 0
  write_auto_upgrade_settings true "$upgrade_target" || fail 'Cannot record the scheduled upgrade attempt.'
  run_upgrade "$upgrade_target"
}
