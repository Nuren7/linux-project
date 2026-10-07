
set -Eeuo pipefail

log_dir=${1:-/var/log/myapp}
backup_dir=${2:-/var/backups/myapp}

if [[ ! -d "$log_dir" ]]; then
    printf 'Error: log directory does not exist: %s\n' "$log_dir" >&2
    exit 1
fi

mkdir -p -- "$backup_dir"

timestamp=$(date '+%Y%m%d_%H%M%S')
archive="$backup_dir/logs_backup_${timestamp}.tar.gz"
file_list=$(mktemp "${TMPDIR:-/tmp}/log-rotator-files.XXXXXX")
archive_tmp=''

cleanup() {
    rm -f -- "$file_list"
    if [[ -n "$archive_tmp" ]]; then
        rm -f -- "$archive_tmp"
    fi
}
trap cleanup EXIT

if ! (cd -- "$log_dir" && find . -type f -name '*.log' -print0) > "$file_list"; then
    printf 'Error: could not enumerate log files in %s\n' "$log_dir" >&2
    exit 1
fi

mapfile -d '' -t log_files < "$file_list"
if ((${#log_files[@]} == 0)); then
    printf 'No .log files found in %s; nothing to rotate.\n' "$log_dir"
    exit 0
fi

archive_tmp=$(mktemp "$backup_dir/.logs_backup_${timestamp}.XXXXXX")
if ! tar -czf "$archive_tmp" -C "$log_dir" --null -T "$file_list"; then
    printf 'Error: failed to create log archive\n' >&2
    exit 1
fi


if ! ln -- "$archive_tmp" "$archive"; then
    printf 'Error: could not publish archive (it may already exist): %s\n' "$archive" >&2
    exit 1
fi
rm -f -- "$archive_tmp"
archive_tmp=''

for log_file in "${log_files[@]}"; do
    : > "$log_dir/$log_file"
done

printf 'Archived and truncated %d log file(s): %s\n' "${#log_files[@]}" "$archive"
