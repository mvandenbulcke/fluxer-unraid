#!/bin/bash

upgrade_dir="$project_dir-upgrades"
upgrade_pending_file="$upgrade_dir/pending"
upgrade_status_file="$upgrade_dir/status.json"
upgrade_manifest="$plugin_dir/upgrade.tsv"
upgrade_bundle="$plugin_dir/bundle"
upgrade_compose_files=(
  docker-compose.yml docker-compose.proxy.yml compose.unraid.yml
  compose.ingress.yml compose.voice-direct.yml
)

upgrade_pending() { [[ -e "$upgrade_pending_file" || -L "$upgrade_pending_file" ]]; }
check_upgrade_pending() {
  if upgrade_pending; then
    fail 'An upgrade needs recovery. See the upgrade status before you start Fluxer.'
  fi
}

release_version() {
  [[ -f "$1" && ! -L "$1" ]] || return 1
  jq -er '.release | strings | select(test("^[0-9]{4}\\.[0-9]{4}\\.[0-9]{6}$"))' "$1" 2>/dev/null
}

read_upgrade_manifest() {
  local path previous next extra seen=' '
  upgrade_paths=()
  upgrade_previous_hashes=()
  upgrade_next_hashes=()
  [[ -f "$upgrade_manifest" && ! -L "$upgrade_manifest" ]] || return 1
  {
    IFS=$'\t' read -r upgrade_source upgrade_target extra || return 1
    [[ -z "$extra" && "$upgrade_source" =~ ^[0-9]{4}\.[0-9]{4}\.[0-9]{6}$ &&
       "$upgrade_target" =~ ^[0-9]{4}\.[0-9]{4}\.[0-9]{6}$ && "$upgrade_source" < "$upgrade_target" ]] || return 1
    while IFS=$'\t' read -r path previous next extra || [[ -n "$path" ]]; do
      case "$path" in
        docker-compose.yml|docker-compose.proxy.yml|compose.unraid.yml|compose.ingress.yml|compose.voice-direct.yml|Caddyfile|.env.example|UPSTREAM.json) ;;
        *) return 1 ;;
      esac
      [[ "$seen" != *" $path "* && -z "$extra" &&
         "$previous" =~ ^[0-9a-f]{64}$ && "$next" =~ ^[0-9a-f]{64}$ ]] || return 1
      seen+="$path "
      upgrade_paths+=("$path")
      upgrade_previous_hashes+=("$previous")
      upgrade_next_hashes+=("$next")
    done
  } < "$upgrade_manifest"
  [[ ${#upgrade_paths[@]} == 8 ]]
}

upgrade_hash_matches() {
  local digest
  [[ -f "$1" && ! -L "$1" ]] || return 1
  digest=$(sha256sum < "$1") || return 1
  [[ "${digest%% *}" == "$2" ]]
}

upgrade_file_error() {
  local index path
  for index in "${!upgrade_paths[@]}"; do
    path=${upgrade_paths[$index]}
    if ! upgrade_hash_matches "$upgrade_bundle/$path" "${upgrade_next_hashes[$index]}"; then
      printf 'The bundled file %s does not match the upgrade manifest. Reinstall the Fluxer plugin.' "$path"
      return 0
    fi
    if ! upgrade_hash_matches "$project_dir/$path" "${upgrade_previous_hashes[$index]}"; then
      printf 'The project file %s differs from the supported source release. Use the manual upgrade guide.' "$path"
      return 0
    fi
  done
}

upgrade_layout_error() {
  local saved_files data root actual_data expected_files
  if [[ -L "$project_dir" || ! -f "$project_dir/.env" || -L "$project_dir/.env" ]]; then
    printf '%s' 'The automatic upgrade requires the standard project folder and .env file.'
    return
  fi
  saved_files=$(env_value COMPOSE_FILE) || saved_files=''
  expected_files=$(IFS=:; printf '%s' "${upgrade_compose_files[*]}")
  if [[ "$saved_files" != "$expected_files" ]]; then
    printf '%s' 'This project uses a custom Compose file list. Use the manual upgrade guide.'
    return
  fi
  data=$(env_value FLUXER_DATA_DIR) || data=''
  root=$(realpath "$project_dir" 2>/dev/null) || root=''
  actual_data=$(realpath "$data" 2>/dev/null) || actual_data=''
  if [[ -z "$root" || ! -d "$data" || -L "$project_dir/data" || "$actual_data" != "$root/data" ]]; then
    printf '%s' 'The automatic upgrade requires storage in the project data folder. Use the manual upgrade guide.'
  fi
}

upgrade_dir_is_private() {
  [[ -d "$upgrade_dir" && ! -L "$upgrade_dir" && -O "$upgrade_dir" ]] &&
    [[ -n $(find "$upgrade_dir" -prune -perm 0700 -print) ]]
}

upgrade_previous_status() {
  local status_file=${1:-$upgrade_status_file}
  if upgrade_dir_is_private && [[ -f "$status_file" && ! -L "$status_file" ]]; then
    jq -ce 'select(type == "object")' "$status_file" 2>/dev/null && return 0
  fi
  printf '{}'
}

upgrade_info() {
  local installed target previous state message available phase locked error
  if ! command -v jq >/dev/null; then
    printf '%s\n' '{"installed":null,"target":null,"available":false,"state":"unavailable","message":"The upgrade requires jq."}'
    return 0
  fi
  installed=$(release_version "$project_dir/UPSTREAM.json") || installed=''
  target=$(release_version "$upgrade_bundle/UPSTREAM.json") || target=''
  previous=$(upgrade_previous_status)
  state=$(jq -r '.state // ""' <<< "$previous")
  message=$(jq -r '.message // ""' <<< "$previous")
  phase=$(jq -r '.phase // ""' <<< "$previous")
  available=false
  locked=false
  if [[ -e "$lock_file" ]] && ! flock -n "$lock_file" true; then locked=true; fi
  if [[ "$locked" == false && "$state" == running ]]; then
    previous=$(upgrade_previous_status)
    state=$(jq -r '.state // ""' <<< "$previous")
    message=$(jq -r '.message // ""' <<< "$previous")
    phase=$(jq -r '.phase // ""' <<< "$previous")
    if [[ -e "$lock_file" ]] && ! flock -n "$lock_file" true; then locked=true; fi
  fi
  if [[ "$locked" == true && "$state" == running ]]; then
    :
  elif upgrade_pending; then
    if [[ "$locked" == true && "$state" == completed ]]; then
      state=running
      phase=finishing
      message='Saving the upgrade result.'
    elif [[ "$state" != failed || "$phase" != recovery ]]; then
      state=interrupted
      phase=recovery
      message='The upgrade was interrupted. Check the backup and follow the recovery guide before starting Fluxer.'
    fi
  elif [[ ! -f "$project_dir/.env" ]]; then
    state=idle
    message='Configure Fluxer before you upgrade it.'
  elif [[ -n "$installed" && "$installed" == "$target" ]]; then
    if [[ "$state" != completed ]]; then
      state=idle
      message='The project already uses the bundled Fluxer release.'
    fi
  elif ! read_upgrade_manifest || [[ "$installed" != "$upgrade_source" || "$target" != "$upgrade_target" ]]; then
    state=unavailable
    message='There is no supported automatic upgrade for this project. See the manual upgrade guide.'
  else
    error=$(upgrade_layout_error)
    if [[ -z "$error" ]]; then error=$(upgrade_file_error); fi
    if [[ -n "$error" ]]; then
      state=unavailable
      message=$error
    else
      available=true
      if [[ "$state" == running ]]; then
        state=failed
        message='The upgrade was interrupted before it replaced the project files. You can retry.'
      elif [[ "$state" != failed ]]; then
        state=ready
        message='The bundled upgrade is ready. Fluxer will stop for the backup and start after the update.'
      fi
    fi
  fi
  jq -n --argjson previous "$previous" --arg installed "$installed" --arg target "$target" \
    --arg state "$state" --arg message "$message" --arg phase "$phase" --argjson available "$available" '
    {installed: ($installed | select(length > 0) // null), target: ($target | select(length > 0) // null),
     available: $available, state: $state, message: $message, phase: ($phase | select(length > 0) // null),
     backup: ($previous.backup // null), request_id: ($previous.request_id // null)}'
}

check_backup_source() {
  local symlink
  symlink=$(find "$project_dir" -type l -print -quit 2>/dev/null) || upgrade_fail 'Cannot check the project backup paths.'
  [[ -z "$symlink" ]] || upgrade_fail 'The project contains a symbolic link. Back up the linked data and use the manual upgrade guide.'
}

sync_upgrade_storage() {
  if [[ "$OSTYPE" == linux* ]]; then
    sync -f "$@" >/dev/null 2>&1 || upgrade_fail 'Cannot flush the project files to storage.'
  else
    sync >/dev/null 2>&1 || upgrade_fail 'Cannot flush the project files to storage.'
  fi
}

check_container_compose_files() {
  local owner_files container file_list resolved path index
  local -a files
  resolved=$(project_real_path) || upgrade_fail 'Cannot check the project folder.'
  owner_files=$(docker ps -a --filter label=com.docker.compose.project=fluxer \
    --format '{{.ID}}|{{.Label "com.docker.compose.project.config_files"}}' 2>/dev/null) ||
    upgrade_fail 'Cannot check the Compose files used by the existing containers.'
  while IFS='|' read -r container file_list; do
    [[ -n "$container" ]] || continue
    IFS=, read -ra files <<< "$file_list"
    [[ -n "$file_list" && ${#files[@]} == ${#upgrade_compose_files[@]} ]] ||
      upgrade_fail 'The existing containers use a custom Compose file list. Use the manual upgrade guide.'
    for index in "${!upgrade_compose_files[@]}"; do
      path=${upgrade_compose_files[$index]}
      [[ "${files[$index]}" == "$project_dir/$path" || "${files[$index]}" == "$resolved/$path" ]] ||
        upgrade_fail 'The existing containers use different Compose files. Use the manual upgrade guide.'
    done
  done <<< "$owner_files"
}

write_upgrade_status() {
  local status_tmp
  if [[ "$1" == running ]]; then upgrade_phase=$2; fi
  status_tmp=$(mktemp "$upgrade_dir/.status-XXXXXX") || return 1
  if ! jq -n --arg state "$1" --arg phase "$2" --arg message "$3" \
    --arg backup "$upgrade_backup" --arg request_id "$upgrade_request_id" '
    {state: $state, phase: $phase, message: $message,
     backup: ($backup | select(length > 0) // null), request_id: ($request_id | select(length > 0) // null)}' > "$status_tmp" ||
    ! mv -f -- "$status_tmp" "$upgrade_status_file"; then
    rm -f -- "$status_tmp"
    return 1
  fi
}

upgrade_fail() {
  upgrade_failure=$1
  fail "$1"
}

cleanup_upgrade() {
  local code=$1
  trap - EXIT
  set +e
  if (( code != 0 )); then
    if [[ "$upgrade_files_started" == true ]]; then
      if [[ "$upgrade_launch_started" == true ]]; then docker compose stop >/dev/null 2>&1; fi
      write_upgrade_status failed recovery "$upgrade_failure Restore the matching backup before starting Fluxer."
    else
      if [[ "$upgrade_created_pending" == true ]]; then
        rm -f -- "$upgrade_pending_file"
        upgrade_failure="$upgrade_failure Select Start Fluxer to resume the original release."
      fi
      write_upgrade_status failed "$upgrade_phase" "$upgrade_failure"
    fi
  fi
  if [[ -n "$upgrade_stage" ]]; then rm -rf -- "$upgrade_stage"; fi
  if [[ -n "$upgrade_backup_dir" && -z "$upgrade_backup" ]]; then rm -rf -- "$upgrade_backup_dir"; fi
  exit "$code"
}

check_local_upgrade_storage() {
  local config=$1 backing_root=${2:-$project_dir} volume device backing_device actual volume_names
  local storage_keys='["edge-config","edge-data","media-proxy-tmp","meilisearch-data","nats-data","postgres-data","seaweedfs-data","valkey-data"]'
  if ! jq -e --arg root "$project_dir" --argjson keys "$storage_keys" '
    .name == "fluxer" and (.services | has("api")) and (.volumes | keys == $keys) and
    (all(.volumes | to_entries[]; .key as $key | .value |
      .name == ("fluxer_" + $key) and .driver == "local" and (.external // false) == false and
      .driver_opts == {device: ($root + "/data/" + $key), type: "none", o: "bind"})) and
    (all(.services[].volumes[]?; .type != "bind" or .source == "/var/run/docker.sock" or
      (.source | startswith($root + "/")))) and
    (.services.api.environment |
      (.FLUXER_POSTGRES_HOST // "postgres") == "postgres" and (.FLUXER_POSTGRES_URL // "") == "" and
      ((.FLUXER_POSTGRES_PORT // "") as $port | ($port == "" or $port == "5432")) and
      (.FLUXER_KV_URL // "redis://valkey:6379/0") == "redis://valkey:6379/0" and
      (.FLUXER_NATS_URL // "nats://nats:4222") == "nats://nats:4222" and
      (.FLUXER_NATS_JETSTREAM_URL // "nats://nats:4222") == "nats://nats:4222" and
      (.FLUXER_SVC_NATS_URL // "nats://nats:4222") == "nats://nats:4222" and
      (.FLUXER_SEARCH_URL // "http://meilisearch:7700") == "http://meilisearch:7700" and
      (.FLUXER_S3_ENDPOINT // "http://seaweedfs:8333") == "http://seaweedfs:8333")' "$config" >/dev/null 2>&1; then
    upgrade_fail 'The effective Compose configuration uses unsupported storage settings. Use the manual upgrade guide.'
  fi
  volume_names=$(docker volume ls --format '{{.Name}}' 2>/dev/null) || upgrade_fail 'Cannot check the existing Docker volumes.'
  while IFS=$'\t' read -r volume device; do
    backing_device="$backing_root/data/${device##*/}"
    [[ -d "$backing_device" && ! -L "$backing_device" ]] || upgrade_fail 'A required data folder is missing or uses a symbolic link.'
    if [[ $'\n'"$volume_names"$'\n' == *$'\n'"$volume"$'\n'* ]]; then
      actual=$(docker volume inspect "$volume" --format '{{json .Options}}' 2>/dev/null) || upgrade_fail 'Cannot read the existing Docker volume settings.'
      if ! jq -e --arg device "$device" '. == {device: $device, type: "none", o: "bind"}' <<< "$actual" >/dev/null 2>&1; then
        upgrade_fail 'An existing Docker volume uses another data folder. Use the manual upgrade guide.'
      fi
    fi
  done < <(jq -r '.volumes[] | [.name, .driver_opts.device] | @tsv' "$config")
}

install_upgrade_file() {
  local path=$1 temporary
  temporary=$(mktemp "$project_dir/.fluxer-upgrade-file-XXXXXX") || return 1
  if ! cat -- "$upgrade_stage/$path" > "$temporary" || ! mv -f -- "$temporary" "$project_dir/$path"; then
    rm -f -- "$temporary"
    return 1
  fi
}

run_upgrade() {
  local expected=$1 index path error running env_digest backup_final
  local candidate_args=(--project-directory "$project_dir" --env-file "$project_dir/.env")
  upgrade_request_id=${2:-}
  [[ "$expected" =~ ^[0-9]{4}\.[0-9]{4}\.[0-9]{6}$ ]] || fail 'Select a valid bundled Fluxer release.'
  [[ -z "$upgrade_request_id" || "$upgrade_request_id" =~ ^[0-9a-f]{32}$ ]] || fail 'The upgrade request ID is invalid.'
  command -v jq >/dev/null || fail 'The upgrade requires jq.'
  [[ -f "$project_dir/.env" ]] || fail 'Configure Fluxer before you upgrade it.'
  check_upgrade_pending
  if [[ ! -e "$upgrade_dir" && ! -L "$upgrade_dir" ]]; then mkdir -m 700 -- "$upgrade_dir"; fi
  upgrade_dir_is_private || fail 'The upgrade folder must belong to the administrator and use mode 700.'
  [[ ! -L "$upgrade_status_file" && ( ! -e "$upgrade_status_file" || -f "$upgrade_status_file" ) ]] ||
    fail 'The upgrade status path must be a regular file.'
  upgrade_backup=''
  upgrade_backup_dir=''
  upgrade_stage=''
  upgrade_failure='The upgrade stopped because an operation failed.'
  upgrade_phase=checking
  upgrade_created_pending=false
  upgrade_files_started=false
  upgrade_launch_started=false
  trap 'cleanup_upgrade "$?"' EXIT
  trap 'exit 130' INT
  trap 'exit 143' HUP TERM
  write_upgrade_status running checking 'Checking the bundled release and project files.'
  read_upgrade_manifest || upgrade_fail 'The plugin does not have a valid upgrade manifest.'
  [[ "$upgrade_target" == "$expected" && $(release_version "$upgrade_bundle/UPSTREAM.json") == "$expected" ]] ||
    upgrade_fail 'The bundled release changed. Refresh the upgrade details.'
  [[ $(release_version "$project_dir/UPSTREAM.json") == "$upgrade_source" ]] ||
    upgrade_fail 'The installed release is outside this upgrade path. Use the manual upgrade guide.'
  error=$(upgrade_layout_error)
  [[ -z "$error" ]] || upgrade_fail "$error"
  error=$(upgrade_file_error)
  [[ -z "$error" ]] || upgrade_fail "$error"
  check_backup_source
  check_runtime
  check_project_ownership
  check_container_compose_files
  for path in cloudflare-dns-token cloudflare-tunnel-token; do
    [[ -s "$project_dir/secrets/$path" ]] || upgrade_fail 'Save both Cloudflare tokens before you upgrade Fluxer.'
  done
  [[ ! -e "$project_dir/.cloudflare-tokens-changed" ]] ||
    upgrade_fail 'Select Start Fluxer to apply the saved Cloudflare tokens before you upgrade.'
  env_digest=$(sha256sum < "$project_dir/.env") || upgrade_fail 'Cannot check the saved instance settings.'
  env_digest=${env_digest%% *}

  upgrade_stage=$(mktemp -d "$upgrade_dir/stage-XXXXXX") || upgrade_fail 'Cannot create the upgrade staging folder.'
  for index in "${!upgrade_paths[@]}"; do
    path=${upgrade_paths[$index]}
    cp -- "$upgrade_bundle/$path" "$upgrade_stage/$path" || upgrade_fail 'Cannot stage the bundled release files.'
    upgrade_hash_matches "$upgrade_stage/$path" "${upgrade_next_hashes[$index]}" ||
      upgrade_fail 'A staged release file does not match the upgrade manifest. Refresh the upgrade details.'
  done
  for path in "${upgrade_compose_files[@]}"; do candidate_args+=(-f "$upgrade_stage/$path"); done
  cd "$project_dir"
  docker compose config --format json > "$upgrade_stage/current.json" 2>/dev/null ||
    upgrade_fail 'The current Compose configuration failed validation.'
  docker compose "${candidate_args[@]}" config --format json > "$upgrade_stage/candidate.json" 2>/dev/null ||
    upgrade_fail 'The bundled Compose configuration failed validation with the saved settings.'
  check_local_upgrade_storage "$upgrade_stage/current.json"
  check_local_upgrade_storage "$upgrade_stage/candidate.json"
  if ! jq -es 'def layout: {name, services: (.services | keys), volumes, networks,
    mounts: (.services | map_values({volumes, ports}))}; (.[0] | layout) == (.[1] | layout)' \
    "$upgrade_stage/current.json" "$upgrade_stage/candidate.json" >/dev/null 2>&1; then
    upgrade_fail 'The bundled upgrade changes the Compose layout. Use the manual upgrade guide.'
  fi

  write_upgrade_status running pulling 'Downloading the bundled images. The current stack can still run.'
  docker compose "${candidate_args[@]}" pull --policy missing >/dev/null 2>&1 ||
    upgrade_fail 'Cannot download all images for the bundled release.'
  error=$(upgrade_file_error)
  [[ -z "$error" ]] || upgrade_fail "$error"
  upgrade_hash_matches "$project_dir/.env" "$env_digest" || upgrade_fail 'The instance settings changed during preflight. Retry the upgrade.'
  if [[ "$action" == auto_upgrade_run ]] && ! auto_upgrade_stack_running; then
    upgrade_fail 'The project stopped while the scheduled upgrade downloaded images.'
  fi
  upgrade_backup_dir=$(mktemp -d "$upgrade_dir/.backup-XXXXXX") || upgrade_fail 'Cannot create the backup folder.'
  write_upgrade_status running stopping 'Stopping Fluxer for a consistent backup.'
  (set -o noclobber; : > "$upgrade_pending_file") || upgrade_fail 'Cannot reserve the upgrade recovery marker.'
  upgrade_created_pending=true
  sync_upgrade_storage "$upgrade_dir"
  docker compose stop >/dev/null 2>&1 || upgrade_fail 'Cannot stop all Fluxer services for the backup.'
  running=$(docker ps --filter label=com.docker.compose.project=fluxer --format '{{.ID}}' 2>/dev/null) ||
    upgrade_fail 'Cannot check if the Fluxer stack stopped.'
  [[ -z "$running" ]] || upgrade_fail 'Some Fluxer containers still run. Check them before you retry.'
  check_backup_source
  write_upgrade_status running backing_up 'Copying the stopped project and its data.'
  cp -a -- "$project_dir" "$upgrade_backup_dir/project" >/dev/null 2>&1 ||
    upgrade_fail 'Cannot copy the full project. Check available space before you retry.'
  backup_final="$upgrade_dir/${upgrade_backup_dir##*/.}"
  if ! retention_record_backup "$upgrade_backup_dir" "${backup_final##*/}"; then
    rm -f -- "$upgrade_backup_dir/$retention_marker"
    printf '%s\n' 'The backup will be kept because the retention record could not be saved.' >&2
  fi
  sync_upgrade_storage "$upgrade_dir"
  move_project_directory "$upgrade_backup_dir" "$backup_final" || upgrade_fail 'Cannot publish the completed project backup.'
  upgrade_backup_dir=$backup_final
  upgrade_backup="$upgrade_backup_dir/project"
  write_upgrade_status running applying 'Applying the bundled release files.'
  sync_upgrade_storage "$upgrade_dir"

  upgrade_files_started=true
  for index in "${!upgrade_paths[@]}"; do
    path=${upgrade_paths[$index]}
    if [[ "$path" != UPSTREAM.json && "${upgrade_previous_hashes[$index]}" != "${upgrade_next_hashes[$index]}" ]]; then
      install_upgrade_file "$path" || upgrade_fail 'Cannot replace a managed release file.'
    fi
  done
  write_upgrade_status running starting 'Starting the new Fluxer release and waiting for container health checks.'
  sync_upgrade_storage "$project_dir" "$upgrade_dir"
  upgrade_launch_started=true
  docker compose up -d --pull never --wait --wait-timeout 300 >/dev/null 2>&1 ||
    upgrade_fail 'The new release did not start and pass its container health checks.'
  : > .unraid-autostart
  chmod 600 .unraid-autostart
  install_upgrade_file UPSTREAM.json || upgrade_fail 'Cannot record the upgraded Fluxer release.'
  write_upgrade_status completed complete 'Fluxer started, passed container health checks, and recorded the upgraded release.'
  sync_upgrade_storage "$project_dir" "$upgrade_dir"
  rm -f -- "$upgrade_pending_file"
  printf '%s\n' 'The Fluxer upgrade completed.'
}
