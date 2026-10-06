# Streaming input retains duplicate object keys, unlike ordinary jq parsing.
def strict_document:
  reduce inputs as $event ({active: [], seen: {}, events: []};
    .events += [$event]
    | if ($event | length) == 2 then
        $event[0] as $path
        | reduce range(1; ($path | length) + 1) as $depth (.;
            ($path[:$depth] | tojson) as $key
            | if (.active | index($key)) == null then
                if .seen[$key] then error("duplicate JSON key") else .seen[$key] = true end
              else . end)
        | .active = [range(1; ($path | length)) as $depth | $path[:$depth] | tojson]
      else
        .active = .active[:([0, (($event[0] | length) - 2)] | max)]
      end)
  | [fromstream(.events[])]
  | if length == 1 then .[0] else error("expected one JSON document") end;

def fields($required; $optional):
  if type != "object" then error("missing required configuration fields")
  elif ($required - keys | length) > 0 then error("missing required configuration fields")
  elif (keys - $required - $optional | length) > 0 then error("unknown configuration fields")
  else . end;

def identifier:
  if type == "string" and test("^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$") and (test("[\\r\\n]") | not)
  then . else error("invalid identifier in execution route") end;

def server_url:
  if type == "string" and test("^https://[A-Za-z0-9.-]+(:[0-9]+)?(/[^\\s?#@]*)?$")
     and (test("[\\r\\n]") | not)
  then sub("/+$"; "") else error("invalid target server URL") end;

def catalog:
  # The repository catalog uses one physical line per row. Accept quoted cells
  # and escaped quotes; reject unsupported encodings instead of guessing.
  def row:
    if test("^(\"([^\"]|\"\")*\"|[^\",]*)(,(\"([^\"]|\"\")*\"|[^\",]*))*$") then
      [match("(?:^|,)(\"(?:[^\"]|\"\")*\"|[^\",]*)"; "g").captures[0].string
       | if startswith("\"") then .[1:-1] | gsub("\"\""; "\"") else . end]
    else error("invalid system catalog") end;
  if $systems_json != "" then $systems_json | fromjson
  else
    $systems_csv | split("\n") | map(sub("\r$"; "")) | map(select(length > 0) | row)
    | .[0] as $header
    | ($header | index("system")) as $name
    | ($header | index("mode")) as $mode
    | if $name == null or $mode == null then error("invalid system catalog") else
        reduce .[1:][] as $row ({};
          if ($row | length) != ($header | length) or has($row[$name]) then
            error("invalid system catalog")
          else .[$row[$name]] = $row[$mode] end)
      end
  end;

def resolve($systems):
  fields(["version", "target", "routes"]; [])
  | if .version != 1 then error("unsupported execution route version") else . end
  | .target |= fields(["server_url", "project_path"]; [])
  | (.target.server_url | server_url) as $server
  | .target.project_path as $project
  | if ($project | type) != "string" or
       ($project | test("^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)+$") | not) or
       ($project | test("[\\r\\n]")) then error("invalid target project path") else . end
  | if $server != (($ENV.CI_SERVER_URL // "") | sub("/+$"; "")) or
       $project != $ENV.CI_PROJECT_PATH then error("execution routes do not match this GitLab server/project") else . end
  | if (.routes | type) != "array" or (.routes | length) == 0 then error("routes must be a nonempty list") else . end
  | reduce .routes[] as $raw ({ids: {}, routes: {}};
      ($raw | fields(["id", "systems", "run_tag", "allocation_project_id"];
                     ["build_tag", "id_token_audience"])) as $route
      | ($route.id | identifier) as $id
      | if .ids[$id] then error("duplicate execution route id") else .ids[$id] = true end
      | ($route.run_tag | identifier) as $run
      | ($route.allocation_project_id | if . == "" then . else identifier end) as $allocation
      | ($route | if has("build_tag") then .build_tag else "" end
         | if . == "" then . else identifier end) as $build
      | ($route | if has("id_token_audience") then .id_token_audience else $server end) as $audience
      | if ($audience | type) != "string" or
           ($audience | test("^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,511}$") | not) or
           ($audience | test("[\\r\\n]")) then error("invalid ID token audience") else . end
      | if ($route.systems | type) != "array" or ($route.systems | length) == 0
        then error("route systems must be a nonempty list") else . end
      | reduce $route.systems[] as $raw_name (.;
          ($raw_name | identifier) as $name
          | if ($systems | has($name) | not) then error("route references an unknown system")
            elif .routes | has($name) then error("multiple routes configured for one system")
            elif $systems[$name] != "cross" and $systems[$name] != "native" then error("unsupported system mode")
            elif $systems[$name] == "cross" and $build == "" then error("cross-mode execution route requires a build tag")
            else .routes[$name] = {id: $id, build_tag: $build, run_tag: $run,
                                  allocation_project_id: $allocation, id_token_audience: $audience}
            end))
  | .routes;

def snapshot:
  fields(["version", "registry_revision", "budget_id", "destination_id", "target", "route"]; [])
  | if (.registry_revision | type) != "number" then error("invalid registry revision")
    elif .registry_revision < 0 or (.registry_revision | floor) != .registry_revision then error("invalid registry revision")
    else . end
  | (.budget_id | identifier) as $budget
  | (.destination_id | identifier) as $destination
  | if (.route | type) != "object" or .route.id != $destination or .route.systems != [$selected]
    then error("snapshot requires exactly its selected destination and system") else . end
  | {version, target, routes: [.route]};

try (catalog as $systems | strict_document
     | if $source == "snapshot" then snapshot else . end
     | resolve($systems) | {resolved: .})
catch {error: (if . == "duplicate JSON key" or . == "duplicate execution route id" or
                 . == "unknown configuration fields" or
                 . == "execution routes do not match this GitLab server/project"
              then . else "Execution route configuration is invalid" end)}
