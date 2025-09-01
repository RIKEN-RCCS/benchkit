#!/bin/bash
get_queue_template() {
    local system="$1"
	echo "[DEBUG] get_queue_template called for $system" >&2
    local queue_from_system
    local submit_cmd=""
    local template_raw=""
    local template=""

    queue_from_system=$(awk -F, -v s="$system" '$1==s && ($3=="run" || $3=="build_run") {print $4}' "$SYSTEM_FILE")
	echo "[DEBUG] system=$system -> queue_from_system=$queue_from_system" >&2

    if [[ -z "$queue_from_system" ]]; then
	    echo "[ERROR] queue not found for $system" >&2
		return 1
	fi

    while IFS=, read -r queue submit template_raw; do
        [[ -z "$queue" ]] && continue
        [[ "$queue" == \#* ]] && continue
        [[ "$queue" == "queue" ]] && continue

        if [[ "$queue_from_system" == "$queue" ]]; then
		    if [[ "$template_raw" == \"*\" ]]; then
              template="${template_raw%\"}"
              template="${template#\"}"
			else
              template="${template_raw}"
			fi
            echo "$submit $template"
            return 0
        fi
    done < "$QUEUE_FILE"
	 echo "[ERROR] No matching queue found for system=$system (queue=$queue_from_system)" >&2

    return 1
}

expand_template() {
    local template="$1"
	if command -v envsubst > /dev/null 2>&1; then
      echo "$template" | envsubst
    else
      echo "[WARN] envsubst not found; falling back to eval" >&2
      eval "echo \"$template\""
    fi
}

