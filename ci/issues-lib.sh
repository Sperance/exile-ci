#!/usr/bin/env bash
# Закрывает только отчёты с указанием очереди в коммитах выпуска через рабочий API.
. "$(dirname "${BASH_SOURCE[0]}")/retry.sh"

queue_close() {
  local url=$1 test=$2 n=$3 label=$4 head revision body reply
  head=$(netcall read curl -sS --fail -G -H "Authorization: Bearer $REPORTS_WORK_TOKEN" --data "number=$n" "$url/get") || return 1
  revision=$(printf '%s' "$head" | python3 -I -c '
import json, sys
s = json.load(sys.stdin)["data"]["summary"]
if s.get("test", False) != (sys.argv[1] == "true") or s["number"] != int(sys.argv[2]):
    sys.exit(1)
if s["state"] == "closed" and s.get("stateReason") == "completed" and sys.argv[3] in s.get("labels", []):
    print("done")
elif s["state"] == "closed":
    print("kept")
else:
    print(int(s["revision"]))
' "$test" "$n" "$label") || return 1
  if [[ $revision == done || $revision == kept ]]; then
    echo "#$n ($test): $revision"
    return 0
  fi
  body=$(python3 -I -c 'import json, sys; print(json.dumps({"number": int(sys.argv[1]), "revision": int(sys.argv[2]), "test": sys.argv[3] == "true", "label": sys.argv[4]}))' "$n" "$revision" "$test" "$label") || return 1
  reply=$(netcall idem curl -sS --fail -X POST -H "Authorization: Bearer $REPORTS_WORK_TOKEN" -H 'Content-Type: application/json' --data-binary "$body" "$url/release-close") || return 1
  printf '%s' "$reply" | python3 -I -c '
import json, sys
s = json.load(sys.stdin)["data"]
sys.exit(0 if s["number"] == int(sys.argv[1]) and s["state"] == "closed" and s.get("stateReason") == "completed" and sys.argv[2] in s.get("labels", []) else 1)
' "$n" "$label" || return 1
  echo "#$n ($test): closed in $label"
}

close_issues() {
  local url=$1 test=$2 label=$3 numbers=$4 n failed=0
  [ -n "$numbers" ] || return 0
  if [ -z "$url" ] || [ -z "${REPORTS_WORK_TOKEN:-}" ]; then
    echo "::error::report queue URL or work token is missing" >&2
    return 1
  fi
  for n in $numbers; do
    if ! queue_close "${url%/}/api/v1/reports-work" "$test" "$n" "$label"; then
      echo "::error::could not verify release closure for #$n (test=$test)" >&2
      failed=1
    fi
  done
  return "$failed"
}
