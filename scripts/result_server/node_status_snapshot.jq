# Interpret captured values on the sender, not on the allocated hosts.
def number: try tonumber catch null;
def trim: sub("^[[:space:]]+"; "") | sub("[[:space:]]+$"; "");
def worker:
  if type != "object" or (.hostname | type) != "string"
    or (.host_fields | type) != "object" or (.gpu_fields | type) != "object"
  then error("invalid worker capture") else . end
  | .host_fields as $h | .gpu_fields as $g
  | .host_state = {
      cpu_logical_count: ($h.cpu_logical_count | number),
      memory_total_mib: ($h.memory_total_kib | number | if . == null then null else . / 1024 end),
      memory_available_mib: ($h.memory_available_kib | number | if . == null then null else . / 1024 end),
      load_average: {one_minute: ($h.load1 | number), five_minutes: ($h.load5 | number),
        fifteen_minutes: ($h.load15 | number)}
    }
  | .gpu_state = {
      available: ($g.query_status == "ok"), query_status: $g.query_status,
      gpus: ($g.csv | split("\n") | map(select(length > 0)) | map(
        split(",") | map(trim) | {
          index: (.[0] // ""), name: (.[1] // ""),
          memory_used_mib: (.[2] | number), memory_total_mib: (.[3] | number),
          utilization_gpu_percent: (.[4] | number), temperature_c: (.[5] | number),
          clocks_sm_mhz: (.[6] | number), clocks_mem_mhz: (.[7] | number), pstate: (.[8] // "")
        })),
      process_summary: {compute_process_count: ($g.compute_process_count | number),
        memory_used_mib: ($g.memory_used_mib | number)}
    }
  | del(.host_fields, .gpu_fields);

if length != 1 then error("expected one node capture") else .[0] end
| if type != "object" or .record_format != "node-status-capture-v1"
  then error("unsupported node capture") else . end
| (.local_worker | fromjson | worker) as $local
| (try (.remote_workers | split("\n") | map(select(test("^[[:space:]]*\\{")))
    | map(fromjson | worker) | unique_by(.hostname)) catch null) as $remote
| if $remote == null or
    (.scheduler.slurm.remote_collection_status == "ok" and ($remote | length) == 0) then
    .collection_status = "partial"
    | .collection_warnings += ["worker_output_parse_failed"]
    | .observed.hosts = [$local]
  elif ($remote | length) > 0 then .observed.hosts = $remote
  else .observed.hosts = [$local] end
| .allocation.scheduler_hosts as $scheduler_hosts
| .observed.hosts as $hosts
| ($hosts | map(.gpu_state.gpus // []) | add // []) as $gpus
| ($hosts | map(.gpu_state.process_summary.compute_process_count // 0) | add // 0) as $process_count
| ($hosts | map(.gpu_state.process_summary.memory_used_mib // 0) | add // 0) as $process_memory
| ($gpus | map(.memory_used_mib // 0) | add // 0) as $gpu_memory
| ($hosts | map(.host_state.cpu_logical_count) | map(select(. != null)) | unique) as $cpu_counts
| ($hosts | map(.host_state.memory_total_mib) | map(select(. != null)) | unique) as $memory_totals
| ($hosts | map(.host_state.memory_available_mib) | map(select(. != null))) as $memory_available
| ($hosts | map(.host_state.load_average.one_minute) | map(select(. != null))) as $load_1m
| ($hosts | map(.host_state.load_average.five_minutes) | map(select(. != null))) as $load_5m
| .summary = {
    scheduler_host_count: ($scheduler_hosts | length), observed_host_count: ($hosts | length),
    cpu_logical_counts: $cpu_counts,
    memory_total_mib_min: ($memory_totals | min), memory_total_mib_max: ($memory_totals | max),
    memory_available_mib_min: ($memory_available | min),
    load_average_1m_max: ($load_1m | max), load_average_5m_max: ($load_5m | max),
    observed_gpu_count: ($gpus | length), gpu_memory_used_total_mib: $gpu_memory,
    gpu_compute_process_count: $process_count, gpu_compute_memory_used_mib: $process_memory,
    gpu_query_statuses: ($hosts | map(.gpu_state.query_status // "unknown") | unique),
    warnings: ([]
      + (if (($scheduler_hosts | length) > 0 and ($hosts | length) != ($scheduler_hosts | length))
         then ["observed_host_count_differs_from_scheduler_host_count"] else [] end)
      + (if ($cpu_counts | length) > 1 then ["cpu_count_differs_across_observed_hosts"] else [] end)
      + (if ($memory_totals | length) > 1 then ["memory_total_differs_across_observed_hosts"] else [] end)
      + (if $process_count > 0 then ["gpu_compute_processes_present_before_run"] else [] end))
  }
| del(.record_format, .local_worker, .remote_workers)
