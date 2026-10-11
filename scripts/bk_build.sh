#!/bin/bash
# Build entrypoint: source provenance and profiler configuration.
# shellcheck source=scripts/common/bootstrap.sh
source "${BASH_SOURCE[0]%/*}/common/bootstrap.sh"
# shellcheck source=scripts/common/source.sh
source "${BK_BENCHKIT_ROOT}/scripts/common/source.sh"
# shellcheck source=scripts/common/profile_config.sh
source "${BK_BENCHKIT_ROOT}/scripts/common/profile_config.sh"
