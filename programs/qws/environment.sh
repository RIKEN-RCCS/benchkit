#!/bin/bash

qws_init_modules() {
    if ! type module >/dev/null 2>&1; then
        if [[ -r /etc/profile.d/modules.sh ]]; then
            source /etc/profile.d/modules.sh
        else
            echo "qws: environment modules are not available" >&2
            return 1
        fi
    fi
}

qws_require_commands() {
    local command_name
    for command_name in "$@"; do
        if ! command -v "$command_name" >/dev/null 2>&1; then
            echo "qws: required command not found after module setup: $command_name" >&2
            return 1
        fi
    done
}

qws_load_rc_environment() {
    local system=$1

    case "$system" in
        RC_GH200)
            qws_init_modules
            module load nvhpc-hpcx/26.9
            qws_require_commands nvc++ mpicc mpic++ mpirun
            ;;
        RC_DGXSP)
            qws_init_modules
            module load nvhpc-hpcx/26.3
            qws_require_commands nvc++ mpicc mpic++ mpirun
            ;;
        RC_GENOA)
            qws_require_commands gcc g++ mpicc mpic++ mpirun
            ;;
        RC_FX700)
            qws_init_modules
            module load FJSVstclanga
            qws_require_commands mpifcc mpirun
            ;;
        *)
            echo "qws: unsupported RC system: $system" >&2
            return 1
            ;;
    esac
}
