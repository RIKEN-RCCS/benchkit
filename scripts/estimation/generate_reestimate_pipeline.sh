#!/bin/bash
# generate_reestimate_pipeline.sh — UUID-based estimation pipeline YAML generator
#
# Generates a child pipeline YAML (.gitlab-ci.estimate.yml) for re-estimation
# of a specific benchmark result identified by UUID.
#
# Required CI variables:
#   result_uuid          - UUID of the benchmark result to re-estimate directly
#   estimate_result_uuid - UUID of the estimate result to re-estimate from
#   estimate_uuid        - legacy alias for result_uuid
#   code           - Program code name (e.g., "qws")
#
# Output: .gitlab-ci.estimate.yml with fetch → estimate → send_estimate stages

set -euo pipefail

# Validate required variables
if [[ -z "${result_uuid:-}" && -z "${estimate_result_uuid:-}" && -z "${estimate_uuid:-}" ]]; then
  echo "ERROR: result_uuid or estimate_result_uuid must be specified" >&2
  exit 1
fi

if [[ -z "${code:-}" ]]; then
  echo "ERROR: code must be specified" >&2
  exit 1
fi

OUTPUT_FILE=".gitlab-ci.estimate.yml"

echo "Generating estimate pipeline YAML for code: $code"

cat > "$OUTPUT_FILE" <<YAML
stages:
  - fetch
  - estimate
  - send_estimate

fetch_result:
  stage: fetch
  tags: [fncx-curl-jq]
  script:
    - echo "Fetching re-estimation input"
    - bash scripts/result_server/fetch_result_by_uuid.sh
  artifacts:
    paths:
      - results/
    expire_in: 1 week

estimate_${code}:
  stage: estimate
  needs: ["fetch_result"]
  tags: ["general"]
  script:
    - echo "Running estimation for ${code}"
    - bash scripts/estimation/run.sh ${code}
  artifacts:
    paths:
      - results/
    expire_in: 1 week

send_estimate_${code}:
  stage: send_estimate
  needs: ["estimate_${code}"]
  tags: [fncx-curl-jq]
  environment:
    name: \$CI_COMMIT_BRANCH
  script:
    - bash scripts/result_server/send_estimate.sh
YAML

echo "Generated $OUTPUT_FILE"
