#!/bin/bash

restore_status_file="$upgrade_dir/restore-status.json"

valid_restore_id() { [[ "$1" =~ ^backup-[A-Za-z0-9]{6}$ ]]; }

restore_path_timestamp() {
  if [[ "$OSTYPE" == linux* ]]; then
    stat -c '%Y' -- "$1" 2>/dev/null
  else
    stat -f '%m' -- "$1" 2>/dev/null
  fi
}

restore_backup_shape() {
  local backup=$1 path
  for path in .env UPSTREAM.json Caddyfile "${upgrade_compose_files[@]}" \
    secrets/cloudflare-dns-token secrets/cloudflare-tunnel-token \
    data/postgres-data/PG_VERSION data/postgres-data/global/pg_control; do
    [[ -f "$backup/$path" && ! -L "$backup/$path" && -s "$backup/$path" ]] || return 1
  done
  for path in data data/postgres-data data/postgres-data/global data/seaweedfs-data secrets; do
    [[ -d "$backup/$path" && ! -L "$backup/$path" ]] || return 1
  done
}

restore_backup_project() {
  local directory="$upgrade_dir/$1" backup current stamp state_stamp
  valid_restore_id "$1" || return 1
  upgrade_dir_is_private || return 1
  [[ -d "$directory" && ! -L "$directory" && -O "$directory" ]] || return 1
  [[ -n $(find "$directory" -prune -perm 0700 -print) ]] || return 1
  backup="$directory/project"
  [[ -d "$backup" && ! -L "$backup" && -O "$backup" ]] || return 1
  [[ -n $(find "$backup" -prune ! -perm -0020 ! -perm -0002 -print) ]] || return 1
  restore_backup_shape "$backup" || return 1
  current=$(upgrade_previous_status)
  if jq -e '.state == "running" and .phase == "backing_up" and .backup == null' <<< "$current" >/dev/null; then
    # A legacy upgrade copied directly into backup-*/project. Skip copies that
    # could belong to the interrupted backup operation.
    stamp=$(restore_path_timestamp "$directory") || return 1
    state_stamp=$(restore_path_timestamp "$upgrade_status_file") || return 1
    [[ "$stamp" =~ ^[0-9]+$ && "$state_stamp" =~ ^[0-9]+$ ]] || return 1
    (( stamp < state_stamp )) || return 1
  fi
  printf '%s\n' "$backup"
}

restore_backup_records() {
  local directory backup id release stamp
  upgrade_dir_is_private || return 0
  for directory in "$upgrade_dir"/backup-*; do
    id=${directory##*/}
    backup=$(restore_backup_project "$id") || continue
    release=$(release_version "$backup/UPSTREAM.json") || continue
    stamp=$(restore_path_timestamp "$directory") || continue
    [[ "$stamp" =~ ^[0-9]+$ ]] || continue
    jq -nc --arg id "$id" --arg release "$release" --argjson stamp "$stamp" \
      '{id: $id, release: $release, created_at: ($stamp | todateiso8601)}'
  done
}

restore_info() {
  local previous state phase message backups available=false locked=false
  if ! command -v jq >/dev/null; then
    printf '%s\n' '{"backups":[],"available":false,"state":"unavailable","message":"Restore requires jq."}'
    return 0
  fi
  previous=$(upgrade_previous_status "$restore_status_file")
  state=$(jq -r '.state // ""' <<< "$previous")
  if [[ -e "$lock_file" ]] && ! flock -n "$lock_file" true; then locked=true; fi
  if [[ "$locked" == false && "$state" == running ]]; then
    previous=$(upgrade_previous_status "$restore_status_file")
    state=$(jq -r '.state // ""' <<< "$previous")
    if [[ -e "$lock_file" ]] && ! flock -n "$lock_file" true; then locked=true; fi
  fi
  phase=$(jq -r '.phase // ""' <<< "$previous")
  message=$(jq -r '.message // ""' <<< "$previous")
  backups=$(restore_backup_records | jq -cs 'sort_by(.created_at, .id) | reverse | .[:100]')

  if [[ "$locked" == true && "$state" == running ]]; then
    :
  elif [[ "$locked" == true && "$state" == completed ]] && upgrade_pending; then
    state=running
    phase=finishing
    message='Saving the restore result.'
  else
    if [[ "$backups" != '[]' ]]; then available=true; fi
    if [[ "$state" == running ]] && upgrade_pending; then
      state=interrupted
      phase=recovery
      message='The restore was interrupted. Review the preserved project and retry with a complete backup.'
    elif [[ "$state" == running ]]; then
      state=failed
      message='The restore was interrupted before it changed the project. You can retry.'
    elif [[ "$phase" == recovery ]] && ! upgrade_pending; then
      phase=''
    elif [[ "$state" != failed && "$state" != completed ]]; then
      if [[ "$available" == true ]]; then
        state=ready
        message='Select a backup to restore its Fluxer release and data.'
      else
        state=idle
        message='No local Fluxer deployment backups are available.'
      fi
    fi
  fi

  jq -n --argjson backups "$backups" --argjson available "$available" --argjson previous "$previous" \
    --arg state "$state" --arg phase "$phase" --arg message "$message" '
    {backups: $backups, available: $available, state: $state, message: $message,
     phase: ($phase | select(length > 0) // null), request_id: ($previous.request_id // null),
     preserved: ($previous.preserved // null), selected_id: ($previous.selected_id // null)}'
}

write_restore_status() {
  local status_tmp
  if [[ "$1" == running ]]; then restore_phase=$2; fi
  status_tmp=$(mktemp "$upgrade_dir/.restore-status-XXXXXX") || return 1
  if ! jq -n --arg state "$1" --arg phase "$2" --arg message "$3" --arg selected_id "$restore_id" \
    --arg preserved "$restore_preserved" --arg request_id "$restore_request_id" '
    {state: $state, phase: $phase, message: $message, selected_id: $selected_id,
     preserved: ($preserved | select(length > 0) // null),
     request_id: ($request_id | select(length > 0) // null)}' > "$status_tmp" ||
    ! mv -f -- "$status_tmp" "$restore_status_file"; then
    rm -f -- "$status_tmp"
    return 1
  fi
}

move_project_directory() {
  local from=$1 to=$2 from_device to_device
  [[ -d "$from" && ! -L "$from" && ! -e "$to" && ! -L "$to" ]] || return 1
  if [[ "$OSTYPE" == linux* ]]; then
    if [[ $(mv --help) == *--no-copy* ]]; then
      mv --no-copy -T -- "$from" "$to"
    else
      # PHP's file wrapper only falls back to a copy for regular files.
      php -r 'exit(is_dir($argv[1]) && @rename($argv[1], $argv[2]) ? 0 : 1);' -- "$from" "$to"
    fi
  else
    from_device=$(stat -f '%d' -- "$from") || return 1
    to_device=$(stat -f '%d' -- "$(dirname -- "$to")") || return 1
    [[ "$from_device" == "$to_device" ]] || return 1
    mv -n -- "$from" "$to"
    [[ ! -e "$from" && -d "$to" ]]
  fi
}

stop_restore_containers() {
  local running container working_dir resolved
  local format='{{.ID}}|{{.Label "com.docker.compose.project.working_dir"}}'
  local ids=()
  resolved=$(project_real_path) || return 1
  running=$(docker ps --filter label=com.docker.compose.project=fluxer --format "$format" 2>/dev/null) || return 1
  [[ -n "$running" ]] || return 0
  while IFS='|' read -r container working_dir; do
    [[ "$container" =~ ^[0-9a-f]{12,64}$ && ( "$working_dir" == "$project_dir" || "$working_dir" == "$resolved" ) ]] || return 1
    ids+=("$container")
  done <<< "$running"
  docker stop --time 60 "${ids[@]}" >/dev/null 2>&1 || return 1
  running=$(docker ps --filter label=com.docker.compose.project=fluxer --format "$format" 2>/dev/null) || return 1
  [[ -z "$running" ]]
}

cleanup_restore() {
  local code=$1
  trap - EXIT
  set +e
  if (( code != 0 )); then
    if [[ "$restore_swap_started" == true ]]; then
      if [[ "$restore_launch_started" == true ]]; then stop_restore_containers; fi
      if [[ ! -d "$restore_preserved" ]]; then restore_preserved=''; fi
      write_restore_status failed recovery "$upgrade_failure Check the preserved project and retry with a complete backup."
    else
      if [[ "$restore_created_pending" == true ]]; then
        rm -f -- "$upgrade_pending_file"
        upgrade_failure="$upgrade_failure Select Start Fluxer to resume the original project."
      fi
      write_restore_status failed "$restore_phase" "$upgrade_failure"
    fi
  fi
  if [[ -n "$restore_stage" ]]; then rm -rf -- "$restore_stage"; fi
  if [[ -n "$restore_displaced" && ! -e "$restore_displaced/project" ]]; then rmdir -- "$restore_displaced"; fi
  exit "$code"
}

check_staged_restore() {
  local stage=$1 expected actual path symlink root
  symlink=$(find "$stage" -type l -print -quit 2>/dev/null) || upgrade_fail 'Cannot check the copied backup files.'
  [[ -z "$symlink" ]] || upgrade_fail 'The selected backup contains a symbolic link. Use the manual restore guide.'
  [[ -f "$stage/.env" && -d "$stage/data" ]] || upgrade_fail 'The selected backup is missing settings or local data.'
  [[ -s "$stage/data/postgres-data/PG_VERSION" && -f "$stage/data/postgres-data/PG_VERSION" &&
    -s "$stage/data/postgres-data/global/pg_control" && -f "$stage/data/postgres-data/global/pg_control" ]] ||
    upgrade_fail 'The selected backup is missing PostgreSQL data.'
  for path in "${upgrade_compose_files[@]}" Caddyfile UPSTREAM.json; do
    [[ -f "$stage/$path" ]] || upgrade_fail 'The selected backup is missing required project files.'
  done
  release_version "$stage/UPSTREAM.json" >/dev/null || upgrade_fail 'Cannot identify the release in the selected backup.'
  expected=$(IFS=:; printf '%s' "${upgrade_compose_files[*]}")
  actual=$(env_value COMPOSE_FILE "$stage/.env") || actual=''
  [[ "$actual" == "$expected" ]] || upgrade_fail 'The selected backup uses a custom Compose file list. Use the manual restore guide.'
  root=$(project_real_path) || upgrade_fail 'Cannot check the live project location.'
  actual=$(env_value FLUXER_DATA_DIR "$stage/.env") || actual=''
  [[ "$actual" == "$project_dir/data" || "$actual" == "$root/data" ]] ||
    upgrade_fail 'The selected backup uses another data location. Use the manual restore guide.'
  for path in cloudflare-dns-token cloudflare-tunnel-token; do
    [[ -f "$stage/secrets/$path" && -s "$stage/secrets/$path" ]] ||
      upgrade_fail 'The selected backup is missing a Cloudflare token.'
  done
}

run_restore() {
  local backup stage path
  local candidate_args=(--project-directory "$project_dir")
  restore_id=$1
  restore_request_id=${2:-}
  valid_restore_id "$restore_id" || fail 'Select a valid Fluxer backup ID.'
  [[ -z "$restore_request_id" || "$restore_request_id" =~ ^[0-9a-f]{32}$ ]] || fail 'The restore request ID is invalid.'
  command -v jq >/dev/null || fail 'Restore requires jq.'
  upgrade_dir_is_private || fail 'The backup directory must belong to the administrator and use mode 700.'
  [[ ! -L "$restore_status_file" && ( ! -e "$restore_status_file" || -f "$restore_status_file" ) ]] ||
    fail 'The restore status path must be a regular file.'
  [[ ! -L "$project_dir" && ( ! -e "$project_dir" || -d "$project_dir" ) ]] ||
    fail 'The live project path must be a directory.'
  if upgrade_pending; then
    [[ -f "$upgrade_pending_file" && ! -L "$upgrade_pending_file" ]] || fail 'The recovery marker must be a regular file.'
  fi
  restore_stage=''
  restore_displaced=''
  restore_preserved=''
  restore_created_pending=false
  restore_swap_started=false
  restore_launch_started=false
  restore_phase=checking
  upgrade_failure='The restore stopped because an operation failed.'
  trap 'cleanup_restore "$?"' EXIT
  trap 'exit 130' INT
  trap 'exit 143' HUP TERM
  write_restore_status running checking 'Checking the selected backup.'
  backup=$(restore_backup_project "$restore_id") || upgrade_fail 'The selected backup is missing or does not have safe permissions.'
  restore_stage=$(mktemp -d "$upgrade_dir/.restore-stage-XXXXXX") || upgrade_fail 'Cannot create the restore staging folder.'
  stage="$restore_stage/project"
  write_restore_status running staging 'Copying the backup. The current Fluxer project can still run.'
  cp -a -- "$backup" "$stage" >/dev/null 2>&1 || upgrade_fail 'Cannot copy the selected backup. Check available storage space.'
  check_staged_restore "$stage"
  check_runtime "$stage/.env"
  check_project_ownership
  check_container_compose_files
  if [[ "$OSTYPE" == linux* && $(mv --help) != *--no-copy* ]]; then
    command -v php >/dev/null || upgrade_fail 'Cannot safely rename project folders on this host.'
  fi
  candidate_args+=(--env-file "$stage/.env")
  for path in "${upgrade_compose_files[@]}"; do candidate_args+=(-f "$stage/$path"); done
  docker compose "${candidate_args[@]}" config --format json > "$restore_stage/candidate.json" 2>/dev/null ||
    upgrade_fail 'The selected backup failed Compose validation.'
  check_local_upgrade_storage "$restore_stage/candidate.json" "$stage"

  write_restore_status running pulling 'Downloading any missing images for the selected backup.'
  docker compose "${candidate_args[@]}" pull --policy missing >/dev/null 2>&1 ||
    upgrade_fail 'Cannot download the images for the selected backup.'
  for path in .env UPSTREAM.json "${upgrade_compose_files[@]}" Caddyfile secrets/cloudflare-dns-token secrets/cloudflare-tunnel-token; do
    cmp -s -- "$backup/$path" "$stage/$path" || upgrade_fail 'The selected backup changed during staging. Retry the restore.'
  done
  check_project_ownership
  check_container_compose_files
  sync_upgrade_storage "$upgrade_dir"
  if [[ -d "$project_dir" ]]; then
    restore_displaced=$(mktemp -d "$upgrade_dir/displaced-XXXXXX") || upgrade_fail 'Cannot reserve a folder for the current project.'
  fi
  write_restore_status running stopping 'Stopping all Fluxer containers before restoring data.'
  if ! upgrade_pending; then
    (set -o noclobber; : > "$upgrade_pending_file") || upgrade_fail 'Cannot reserve the restore recovery marker.'
    restore_created_pending=true
  fi
  sync_upgrade_storage "$upgrade_dir"
  stop_restore_containers || upgrade_fail 'Cannot stop all Fluxer containers. Check their status before retrying.'
  auto_upgrade_disable_for_restore

  if [[ -n "$restore_displaced" ]]; then restore_preserved="$restore_displaced/project"; fi
  write_restore_status running swapping 'Restoring the selected release and its data.'
  sync_upgrade_storage "$upgrade_dir"
  restore_swap_started=true
  if [[ -n "$restore_preserved" ]]; then
    if ! move_project_directory "$project_dir" "$restore_preserved"; then
      if [[ -d "$project_dir" && ! -e "$restore_preserved" ]]; then
        restore_preserved=''
        restore_swap_started=false
      fi
      upgrade_fail 'Cannot move the current project to its preserved folder.'
    fi
  fi
  if ! move_project_directory "$stage" "$project_dir"; then
    if [[ -n "$restore_preserved" ]] && move_project_directory "$restore_preserved" "$project_dir"; then
      restore_preserved=''
      restore_swap_started=false
    fi
    upgrade_fail 'Cannot move the selected backup into the live project folder.'
  fi
  write_restore_status running starting 'Starting the restored release and waiting for container health checks.'
  sync_upgrade_storage "$project_dir" "$upgrade_dir"
  cd "$project_dir"
  docker compose config --format json > "$restore_stage/live.json" 2>/dev/null ||
    upgrade_fail 'The restored project failed Compose validation before startup.'
  jq -es '.[0] == .[1]' "$restore_stage/candidate.json" "$restore_stage/live.json" >/dev/null 2>&1 ||
    upgrade_fail 'The live Compose configuration differs from the checked backup configuration.'
  restore_launch_started=true
  docker compose up -d --pull never --wait --wait-timeout 300 --force-recreate >/dev/null 2>&1 ||
    upgrade_fail 'The restored release did not start and pass its container health checks.'
  : > .unraid-autostart
  chmod 600 .unraid-autostart
  rm -f -- "$upgrade_status_file"
  write_restore_status completed complete 'The restored Fluxer release started and passed its container health checks.'
  sync_upgrade_storage "$project_dir" "$upgrade_dir"
  rm -f -- "$upgrade_pending_file"
  printf '%s\n' 'The Fluxer restore completed.'
}
