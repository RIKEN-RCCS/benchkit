# Reject duplicate keys before ordinary JSON parsing loses them.
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
      else .active = .active[:([0, (($event[0] | length) - 2)] | max)] end)
  | [fromstream(.events[])]
  | if length == 1 then .[0] else error("expected one document") end;

def manifest:
  if type != "object" or keys != ["files","kind","schema_version"] then error("invalid manifest") else . end |
  if .schema_version != 1 or (.kind != "file" and .kind != "directory") then error("invalid kind") else . end |
  if (.files | type) != "array" or (.files | length) < 1 or (.files | length) > 10000 then error("invalid files") else . end |
  .files |= map(
    if type != "object" or keys != ["path","sha256","size_bytes"] then error("invalid entry") else . end |
    if (.path | type) != "string" or (.path | split("/") | any(. == "" or . == "." or . == "..")) then error("invalid name") else . end |
    if (.sha256 | type) != "string" or (.sha256 | test("^[0-9a-f]{64}$") | not) then error("invalid hash") else . end |
    if (.size_bytes | type) != "number" then error("invalid size") else . end |
    if .size_bytes < 0 or .size_bytes != (.size_bytes | floor) then error("invalid size") else . end
  ) |
  if ([.files[].path] | length) != ([.files[].path] | unique | length) then error("duplicate path") else . end |
  if .kind == "file" and [.files[].path] != ["input"] then error("invalid file manifest") else . end |
  .files |= sort_by(.path);
