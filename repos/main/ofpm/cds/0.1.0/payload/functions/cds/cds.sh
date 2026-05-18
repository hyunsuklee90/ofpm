#!/bin/bash

_cds_migrate() {
    local db_file="$CDS_DATAPATH/cds_db"
    local old_path="$CDS_DATAPATH/cds_path"
    local old_tag="$CDS_DATAPATH/cds_tag"
    local old_idx="$CDS_DATAPATH/cds_idx"
    local legacy_data_dir
    local legacy_db
    local legacy_path
    local legacy_tag
    local legacy_idx
    local profile_dir

    mkdir -p "$CDS_DATAPATH"

    if [[ -f "$old_path" && ! -f "$db_file" ]]; then
        paste -d '|' "$old_idx" "$old_tag" "$old_path" > "$db_file"
    fi

    if [[ ! -f "$db_file" ]]; then
        for profile_dir in "$CDS_ROOT"/config/*; do
            [ -d "$profile_dir/data" ] || continue
            legacy_data_dir="$profile_dir/data"
            legacy_db="$legacy_data_dir/cds_db"
            legacy_path="$legacy_data_dir/cds_path"
            legacy_tag="$legacy_data_dir/cds_tag"
            legacy_idx="$legacy_data_dir/cds_idx"
            if [[ -f "$legacy_db" ]]; then
                \cp "$legacy_db" "$db_file"
                break
            fi
            if [[ -f "$legacy_path" ]]; then
                paste -d '|' "$legacy_idx" "$legacy_tag" "$legacy_path" > "$db_file"
                break
            fi
        done
    fi

    [[ ! -f "$db_file" ]] && touch "$db_file"
}

_cds_init_session() {
    local db_file="$CDS_DATAPATH/cds_db"
    local mode="${CDS_MODE:-direct}"
    if [[ "$mode" == "memory" ]]; then
        export _CDS_SESSION_DB="/tmp/cds_db_${USER}_${$}"
        if [[ ! -f "$_CDS_SESSION_DB" ]]; then
            [[ -f "$db_file" ]] && \cp "$db_file" "$_CDS_SESSION_DB" || touch "$_CDS_SESSION_DB"
        fi
    fi
}

_cds_get_active_db() {
    local mode="${CDS_MODE:-direct}"
    if [[ "$mode" == "memory" && -f "$_CDS_SESSION_DB" ]]; then
        echo "$_CDS_SESSION_DB"
    else
        echo "$CDS_DATAPATH/cds_db"
    fi
}

_cds_backup() {
    local active_db=$(_cds_get_active_db)
    local backup_dir="$CDS_DATAPATH/backups"
    [[ ! -f "$active_db" ]] && return
    [[ ! -d "$backup_dir" ]] && mkdir -p "$backup_dir"
    for i in {10..2}; do
        local prev=$((i-1))
        [[ -f "$backup_dir/cds_db.$prev" ]] && \mv "$backup_dir/cds_db.$prev" "$backup_dir/cds_db.$i"
    done
    \cp "$active_db" "$backup_dir/cds_db.1"
}

_cds_undo() {
    local active_db=$(_cds_get_active_db)
    local backup_dir="$CDS_DATAPATH/backups"
    if [[ -f "$backup_dir/cds_db.1" ]]; then
        \mv "$backup_dir/cds_db.1" "$active_db"
        echo "Undo successful. Restored to previous state." >&2
        for i in {1..9}; do
            local next=$((i+1))
            [[ -f "$backup_dir/cds_db.$next" ]] && \mv "$backup_dir/cds_db.$next" "$backup_dir/cds_db.$i"
        done
        _cds_print_list
    else
        echo "No more backups found to undo." >&2
    fi
}

_cds_sort_db() {
    local active_db=$(_cds_get_active_db)
    [[ -f "$active_db" ]] && sort -t'|' -k1,1n "$active_db" -o "$active_db"
}

_cds_log() {
    local path="$1"
    local history_file="$CDS_DATAPATH/cds_history"
    [[ ! -d "$(dirname "$history_file")" ]] && mkdir -p "$(dirname "$history_file")"
    [[ "$path" == "$HOME" || "$path" == "/" ]] && return
    echo "$path" >> "$history_file"
    if (( $(wc -l < "$history_file") > 5000 )); then
        tail -n 4000 "$history_file" > "${history_file}.tmp" && \mv "${history_file}.tmp" "$history_file"
    fi
}

_cds_print_list() {
    local active_db=$(_cds_get_active_db)
    if [[ ! -s "$active_db" ]]; then
        echo "No shortcuts saved yet." >&2
        return
    fi
    # Keep command-substitution output clean.
    {
        printf "%-5s | %-10s | %s\n" "IDX" "TAG" "PATH"
        printf "%s\n" "------------------------------------"
        sort -t'|' -k1,1n "$active_db" | awk -F'|' '{ printf "%-5s | %-10s | %s\n", $1, $2, $3 }'
    } >&$( [[ -t 1 ]] && echo 1 || echo 2 )
}

_cds_get_path() {
    local query="$1"
    local active_db=$(_cds_get_active_db)
    awk -F'|' -v q="$query" '$1 == q || $2 == q { print $3; exit }' "$active_db"
}

_cds_smart_get_path() {
    local query="$1"
    local history_file="$CDS_DATAPATH/cds_history"
    [[ ! -f "$history_file" ]] && return
    grep -i -- "$query" "$history_file" | sort | uniq -c | sort -nr | awk '{$1=""; print substr($0,2); exit}'
}

_cds_swap() {
    local idx1="$1"
    local idx2="$2"
    local active_db=$(_cds_get_active_db)
    
    if [[ -z "$idx1" || -z "$idx2" ]]; then
        echo "Usage: cds -s [idx1] [idx2]" >&2
        return
    fi

    local line1=$(awk -F'|' -v idx="$idx1" '$1 == idx {print; exit}' "$active_db")
    local line2=$(awk -F'|' -v idx="$idx2" '$1 == idx {print; exit}' "$active_db")
    
    if [[ -z "$line1" && -z "$line2" ]]; then
        echo "Error: Neither index $idx1 nor $idx2 exists." >&2
        return
    fi
    
    _cds_backup
    
    sed -i "/^$idx1|/d; /^$idx2|/d" "$active_db"
    
    [[ -n "$line1" ]] && echo "$idx2|${line1#*|}" >> "$active_db"
    [[ -n "$line2" ]] && echo "$idx1|${line2#*|}" >> "$active_db"
    
    _cds_sort_db
    echo "Swapped/Moved indexes $idx1 and $idx2" >&2
}

cd() {
    if [[ $# -eq 0 ]]; then builtin cd "$HOME" || return; else builtin cd "$@" || return; fi
    _cds_log "$(pwd)"
}

cds() {
    local db_file="$CDS_DATAPATH/cds_db"
    local mode="${CDS_MODE:-direct}"
    _cds_migrate
    _cds_init_session
    
    local active_db=$(_cds_get_active_db)
    local cmd="${1:-"-l"}"

    case "$cmd" in
        "-h"|"-help"|"--help")
            echo "Usage: cds [option | idx | tag | query]" >&2
            echo "Options:" >&2
            echo "  -l               : List all shortcuts (default)" >&2
            echo "  -a [path] [idx]  : Add directory" >&2
            echo "  -an [idx] [tag]  : Assign/Update tag" >&2
            echo "  -r [idx|tag]     : Remove shortcut" >&2
            echo "  -s [idx1] [idx2] : Swap/Move indexes" >&2
            echo "  -undo            : Undo last change" >&2
            echo "  -z [query]       : Smart Jump" >&2
            echo "  [idx|tag]        : Jump (or print path if used in $())" >&2
            ;;

        "-save")
            if [[ "$mode" == "memory" ]]; then _cds_backup; \cp "$_CDS_SESSION_DB" "$db_file"; echo "Saved to disk." >&2; else echo "Direct mode active." >&2; fi
            ;;

        "-load")
            if [[ "$mode" == "memory" ]]; then \cp "$db_file" "$_CDS_SESSION_DB"; echo "Reloaded." >&2; _cds_print_list; else echo "Direct mode active." >&2; fi
            ;;

        "-l")
            if [[ -n "$2" ]]; then 
                local p=$(_cds_get_path "$2")
                [[ -n "$p" ]] && echo "$p" || echo "Not found." >&2
            else 
                _cds_print_list
            fi
            ;;

        "-a")
            _cds_backup
            local target_path="${2:-$(pwd)}"
            [[ "$target_path" == "." ]] && target_path=$(pwd)
            local target_idx="$3"
            if [[ -n "$target_idx" ]]; then sed -i "/^$target_idx|/d" "$active_db"; else
                target_idx=$(awk -F'|' '{a[$1]=1} END{i=1; while(a[i]) i++; print i}' "$active_db")
            fi
            echo "$target_idx|-|$target_path" >> "$active_db"
            _cds_sort_db
            echo "Added [$target_idx]: $target_path" >&2
            ;;

        "-an"|"-cn")
            _cds_backup
            local target="$2"; local new_tag="$3"
            sed -i "s/^\($target\)|[^|]*/\1|$new_tag/" "$active_db"
            echo "Updated tag for $target to '$new_tag'" >&2
            ;;

        "-s"|"-ci")
            _cds_swap "$2" "$3"
            ;;

        "-r"|"-rm")
            _cds_backup
            local target="$2"
            sed -i "/^$target|/d; /|${target}|/d" "$active_db"
            echo "Removed: $target" >&2
            ;;

        "-undo")
            _cds_undo
            ;;

        "-p")
            _cds_get_path "$2"
            ;;

        "-z")
            local query="$2"
            if [[ -z "$query" ]]; then
                sort "$CDS_DATAPATH/cds_history" | uniq -c | sort -nr | head -n 10 >&2
            else
                local target_path=$(_cds_smart_get_path "$query")
                if [[ -n "$target_path" ]]; then
                    if [[ -t 1 ]]; then echo "Smart jumping to: $target_path" >&2; cd "$target_path"; else printf "%s" "$target_path"; fi
                else
                    [[ -t 1 ]] && echo "No match found for '$query'." >&2
                fi
            fi
            ;;

        *)
            local target_path=$(_cds_get_path "$cmd")
            [[ -z "$target_path" ]] && target_path=$(_cds_smart_get_path "$cmd")

            if [[ -n "$target_path" ]]; then
                if [[ -d "$target_path" ]]; then
                    if [[ -t 1 ]]; then
                        cd "$target_path" 
                    else
                        printf "%s" "$target_path" 
                    fi
                else
                    [[ -t 1 ]] && echo "Error: Directory does not exist: $target_path" >&2
                fi
            else
                [[ -t 1 ]] && echo "Shortcut/History '$cmd' not found." >&2
            fi
            ;;
    esac
}
