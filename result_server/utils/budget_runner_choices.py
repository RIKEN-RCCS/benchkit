"""Project-scoped tag suggestions, not execution or allocation authorization."""

from .runner_observations import presentation


def runner_choices(connections, snapshot, *, now=None):
    observed = presentation(snapshot, now=now)
    result = {}
    for connection in connections:
        server = connection["server_url"].rstrip("/").lower()
        targets = [target for target in observed["targets"]
                   if connection["available"]
                   and target["server"] == server
                   and target["project"] == connection["project_path"]
                   and (not connection["target_id"] or target["id"] == connection["target_id"])]
        current = {target["id"] for target in targets if target["state"] == "current"}
        members = {target["id"] for target in targets}
        rows = []
        for runner in observed["runners"]:
            if runner["server"] != server or not members.intersection(runner["targets"]):
                continue
            record = runner["record"]
            fresh = bool(current.intersection(runner["targets"])) and runner["state"] == "current"
            rows.append({"id": runner["id"],
                         "label": record.get("description") or runner["summary"].get("description") or f"Runner #{runner['id']}",
                         "tags": record.get("tag_list", []), "fresh": fresh,
                         "heartbeat": runner["heartbeat"] if fresh else "unknown",
                         "paused": record.get("paused", False),
                         "protected": record.get("access_level") == "ref_protected",
                         "age": runner["last_success_age"]})
        state = "current" if current else "unavailable" if targets else "not_observed"
        result[connection["id"]] = {"state": state, "runners": rows, "targets": sorted(members)}
    return result
