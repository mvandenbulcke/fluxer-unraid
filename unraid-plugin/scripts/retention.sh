#!/bin/bash

retention_days_file="$upgrade_dir/retention-days"
retention_marker=.fluxer-retention.json

retention_array_available() {
  [[ "$project_dir" != /mnt/user/appdata/fluxer ]] || mountpoint -q /mnt/user
}

retention_private_file() {
  [[ -f "$1" && ! -L "$1" && -O "$1" ]] && [[ -n $(find "$1" -prune -perm 0600 -print) ]]
}

retention_private_directory() {
  [[ -d "$1" && ! -L "$1" && -O "$1" ]] && [[ -n $(find "$1" -prune -perm 0700 -print) ]]
}

valid_retention_days() { [[ "$1" =~ ^(0|[1-9][0-9]{0,3})$ ]] && (( $1 <= 3650 )); }

retention_get_days() {
  local days=''
  if upgrade_dir_is_private && retention_private_file "$retention_days_file"; then
    days=$(< "$retention_days_file")
  fi
  if valid_retention_days "$days"; then printf '%s\n' "$days"; else printf '0\n'; fi
}

retention_info() { printf '{"days":%s}\n' "$(retention_get_days)"; }

retention_set() {
  local days=$1 temporary
  valid_retention_days "$days" || fail 'Enter a retention period from 0 to 3650 days.'
  retention_array_available || fail 'Start the Unraid array before you save retention settings.'
  if [[ ! -e "$upgrade_dir" && ! -L "$upgrade_dir" ]]; then mkdir -m 700 -- "$upgrade_dir"; fi
  upgrade_dir_is_private || fail 'The backup directory must belong to the administrator and use mode 700.'
  [[ ! -L "$retention_days_file" && ( ! -e "$retention_days_file" || -f "$retention_days_file" ) ]] ||
    fail 'The retention settings path must be a regular file.'
  temporary=$(mktemp "$upgrade_dir/.retention-days-XXXXXX") || fail 'Cannot create the retention settings file.'
  if ! printf '%s\n' "$days" > "$temporary" || ! mv -f -- "$temporary" "$retention_days_file"; then
    rm -f -- "$temporary"
    fail 'Cannot save the retention settings.'
  fi
  retention_info
}

retention_unmounted() {
  local path mount
  [[ "$OSTYPE" == linux* ]] || return 0
  path=$(realpath -- "$1") || return 1
  [[ -r /proc/self/mountinfo ]] || return 1
  while IFS=' ' read -r _ _ _ _ mount _; do
    mount=${mount//\\040/ }
    mount=${mount//\\011/$'\t'}
    mount=${mount//\\012/$'\n'}
    mount=${mount//\\134/\\}
    if [[ "$mount" == "$path" || "$mount" == "$path/"* ]]; then return 1; fi
  done < /proc/self/mountinfo
}

retention_tree_safe() {
  local path=$1 device
  if [[ "$OSTYPE" == linux* ]]; then
    retention_unmounted "$path" || return 1
    device=$(stat -c '%d' -- "$path") || return 1
    find "$path" -xdev -printf '%D %y\n' | awk -v device="$device" '$1 != device || $2 !~ /^[df]$/ { invalid=1 } END { exit invalid }'
  else
    device=$(stat -f '%d' -- "$path") || return 1
    find -x "$path" -exec stat -f '%d %HT' -- {} + |
      awk -v device="$device" '$1 != device || ($2 != "Directory" && $2 != "Regular") { invalid=1 } END { exit invalid }'
  fi
}

retention_inventory() {
  local backup=$1 digest
  retention_tree_safe "$backup" || return 1
  digest=$(
    export LC_ALL=C
    cd -- "$backup" || exit 1
    {
      if [[ "$OSTYPE" == linux* ]]; then
        find . -xdev -printf '%P\t%y\t%s\t%T@\t%C@\t%m\t%U\t%G\0' | LC_ALL=C sort -z || exit 1
      else
        find -x . -exec stat -f '%N\t%HT\t%z\t%m\t%c\t%Lp\t%u\t%g' -- {} + | LC_ALL=C sort || exit 1
      fi
      sha256sum -- .env UPSTREAM.json Caddyfile .env.example start.sh "${upgrade_compose_files[@]}" \
        secrets/cloudflare-dns-token secrets/cloudflare-tunnel-token
    } | sha256sum
  ) || return 1
  printf '%s\n' "${digest%% *}"
}

retention_record_backup() {
  local directory=$1 id=$2 backup="$1/project" release inventory timestamp marker="$1/$retention_marker"
  valid_restore_id "$id" || return 1
  release=$(release_version "$backup/UPSTREAM.json") || return 1
  inventory=$(retention_inventory "$backup") || return 1
  (set -o noclobber; : > "$marker") || return 1
  timestamp=$(restore_path_timestamp "$directory") || return 1
  jq -nc --arg id "$id" --arg release "$release" --argjson created_at "$timestamp" --arg inventory "$inventory" \
    '{schema: 1, id: $id, release: $release, created_at: $created_at, inventory: $inventory}' > "$marker"
}

retention_eligible_project() {
  local backup=$1 expected saved data canonical volume
  expected=$(IFS=:; printf '%s' "${upgrade_compose_files[*]}")
  saved=$(env_value COMPOSE_FILE "$backup/.env") || return 1
  [[ "$saved" == "$expected" ]] || return 1
  data=$(env_value FLUXER_DATA_DIR "$backup/.env") || return 1
  canonical=$(project_real_path) || return 1
  [[ "$data" == "$project_dir/data" || "$data" == "$canonical/data" ]] || return 1
  for volume in edge-config edge-data media-proxy-tmp meilisearch-data nats-data postgres-data seaweedfs-data traefik-acme valkey-data; do
    [[ -d "$backup/data/$volume" && ! -L "$backup/data/$volume" ]] || return 1
  done
  retention_tree_safe "$backup"
}

retention_certified_timestamp() {
  local backup=$1 id=$2 directory=${1%/project} release timestamp inventory entries
  local marker="$directory/$retention_marker"
  retention_private_file "$marker" || return 1
  entries=$(find "$directory" -maxdepth 1 ! -name "${directory##*/}" ! -name project ! -name "$retention_marker" -print -quit) || return 1
  [[ -z "$entries" ]] || return 1
  release=$(release_version "$backup/UPSTREAM.json") || return 1
  timestamp=$(restore_path_timestamp "$directory") || return 1
  [[ "$timestamp" =~ ^[0-9]+$ ]] || return 1
  inventory=$(jq -er --arg id "$id" --arg release "$release" --argjson timestamp "$timestamp" '
    select(.schema == 1 and .id == $id and .release == $release and .created_at == $timestamp) |
    .inventory | strings | select(test("^[0-9a-f]{64}$"))' "$marker" 2>/dev/null) || return 1
  [[ $(retention_inventory "$backup") == "$inventory" ]] || return 1
  printf '%s\n' "$timestamp"
}

retention_prune_detached() {
  local detached=$1 cutoff=$2 selection="$1/.selection.json" backup="$1/backup"
  [[ ${detached##*/} =~ ^\.retention-delete-[A-Za-z0-9]{6}$ ]] || return 0
  retention_private_directory "$detached" && retention_private_file "$selection" || return 0
  jq -e --argjson cutoff "$cutoff" '
    .schema == 1 and (.id | strings | test("^backup-[A-Za-z0-9]{6}$")) and
    (.created_at | numbers) < $cutoff' "$selection" >/dev/null 2>&1 || return 0
  if [[ -e "$backup" || -L "$backup" ]]; then
    retention_private_directory "$backup" || return 0
    if [[ "$OSTYPE" == linux* ]]; then
      retention_unmounted "$backup" || return 0
      rm -rf --one-file-system -- "$backup" || return 0
    else
      rm -rf -- "$backup" || return 0
    fi
  fi
  rm -f -- "$selection"
  rmdir -- "$detached" 2>/dev/null || true
}

retention_detach() {
  local directory=$1 id=$2 created=$3 cutoff=$4 detached
  detached=$(mktemp -d "$upgrade_dir/.retention-delete-XXXXXX") || return 1
  if ! jq -nc --arg id "$id" --argjson created_at "$created" \
    '{schema: 1, id: $id, created_at: $created_at}' > "$detached/.selection.json"; then
    return 1
  fi
  sync_upgrade_storage "$upgrade_dir"
  if move_project_directory "$directory" "$detached/backup"; then
    sync_upgrade_storage "$upgrade_dir"
    retention_prune_detached "$detached" "$cutoff"
  else
    retention_prune_detached "$detached" "$cutoff"
    return 1
  fi
}

retention_cleanup() {
  local days now cutoff rows id backup timestamp directory marker detached newest=''
  retention_array_available && upgrade_dir_is_private || return 0
  if upgrade_pending; then return 0; fi
  command -v jq >/dev/null || return 0
  days=$(retention_get_days)
  (( days > 0 )) || return 0
  now=$(date +%s) || return 0
  cutoff=$((now - days * 86400))
  rows=$(restore_backup_records | jq -sr 'sort_by(.created_at, .id) | reverse | .[].id') || return 0
  while IFS= read -r id; do
    valid_restore_id "$id" || continue
    backup=$(restore_backup_project "$id") || continue
    if ! retention_eligible_project "$backup"; then continue; fi
    marker="${backup%/project}/$retention_marker"
    if [[ -e "$marker" || -L "$marker" ]] && ! retention_certified_timestamp "$backup" "$id" >/dev/null; then continue; fi
    newest=$id
    break
  done <<< "$rows"
  [[ -n "$newest" ]] || return 0

  for detached in "$upgrade_dir"/.retention-delete-*; do retention_prune_detached "$detached" "$cutoff"; done
  while IFS= read -r id; do
    valid_restore_id "$id" && [[ "$id" != "$newest" ]] || continue
    backup=$(restore_backup_project "$id") || continue
    directory=${backup%/project}
    timestamp=$(restore_path_timestamp "$directory") || continue
    [[ "$timestamp" =~ ^[0-9]+$ ]] && (( timestamp < cutoff )) || continue
    timestamp=$(retention_certified_timestamp "$backup" "$id") || continue
    (( timestamp < cutoff )) || continue
    retention_detach "$directory" "$id" "$timestamp" "$cutoff" || fail 'Cannot detach an expired Fluxer backup.'
  done <<< "$rows"
}
