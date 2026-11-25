#!/usr/bin/env bash
# Закрывает только отчёты с указанием очереди в коммитах выпуска через рабочий API.
. "$(dirname "${BASH_SOURCE[0]}")/retry.sh"

qa_in_release() {
  local build=$1 released=$2 checkout=$3 private_repo=$4 commit
  [[ $build =~ ^[1-9][0-9]*$ && $released =~ ^[0-9a-f]{40}$ ]] || return 2
  if [[ -z $private_repo ]]; then
    commit=$(git -C "$checkout" rev-parse --verify "qa-$build^{commit}") || return 2
  else
    commit=$(GH_TOKEN="$QA_SOURCE_TOKEN" netcall read gh api "repos/$private_repo/commits/qa-$build" --jq .sha) || return 2
    commit=$(GH_TOKEN="$QA_SOURCE_TOKEN" netcall read gh api "repos/$private_repo/git/trees/$commit" --jq '.tree[] | select(.path == "backend" and .mode == "160000") | .sha') || return 2
  fi
  [[ $commit =~ ^[0-9a-f]{40}$ ]] || return 2
  git -C "$checkout" merge-base --is-ancestor "$commit" "$released"
}

queue_release_state() {
  local url=$1 test=$2 n=$3 label=$4 head
  head=$(netcall read curl -sS --fail -G -H "Authorization: Bearer $REPORTS_WORK_TOKEN" --data "number=$n" "$url/get") || return 1
  printf '%s' "$head" | python3 -I -c '
import json, sys
detail = json.load(sys.stdin)["data"]
s = detail["summary"]
if s.get("test", False) != (sys.argv[1] == "true") or s["number"] != int(sys.argv[2]):
    sys.exit(1)
state = s.get("state", "open")
labels = set(s.get("labels", []))
if state == "closed" and s.get("stateReason") == "completed" and sys.argv[3] in labels:
    print("done")
elif state == "closed":
    print("kept")
elif state != "open":
    sys.exit(1)
elif labels & {"disputed", "in-progress"} or s.get("workId") or detail.get("authorReplyAfterVerificationAt", 0) > 0:
    print("waiting")
elif not s.get("test", False) and "ready" not in labels:
    print("waiting")
else:
    print(int(s["revision"]), int(s.get("readyBuild", 0)))
' "$test" "$n" "$label"
}

release_state_unchanged() {
  local state=$1 n=$2 test=$3
  case $state in
    done|kept) echo "#$n ($test): $state" ;;
    waiting) echo "#$n ($test): work or author response is pending, keeping the report open" ;;
    *) return 1 ;;
  esac
}

queue_close() {
  local url=$1 test=$2 n=$3 label=$4 released=$5 checkout=$6 private_repo=$7 state revision ready_build body reply code
  state=$(queue_release_state "$url" "$test" "$n" "$label") || return 1
  if release_state_unchanged "$state" "$n" "$test"; then return 0; fi
  read -r revision ready_build <<<"$state"
  if [[ $test == true ]]; then
    code=0
    qa_in_release "$ready_build" "$released" "$checkout" "$private_repo" || code=$?
    if [[ $code == 1 ]]; then
      echo "#$n: QA $ready_build is outside this release, keeping the report open"
      return 0
    fi
    [[ $code == 0 ]] || return 1
  fi
  body=$(python3 -I -c 'import json, sys; print(json.dumps({"number": int(sys.argv[1]), "revision": int(sys.argv[2]), "test": sys.argv[3] == "true", "label": sys.argv[4], "readyBuild": int(sys.argv[5])}))' "$n" "$revision" "$test" "$label" "$ready_build") || return 1
  if reply=$(netcall idem curl -sS --fail -X POST -H "Authorization: Bearer $REPORTS_WORK_TOKEN" -H 'Content-Type: application/json' --data-binary "$body" "$url/release-close") && printf '%s' "$reply" | python3 -I -c '
import json, sys
s = json.load(sys.stdin)["data"]
sys.exit(0 if s["number"] == int(sys.argv[1]) and s.get("state") == "closed" and s.get("stateReason") == "completed" and sys.argv[2] in s.get("labels", []) else 1)
' "$n" "$label"; then
    echo "#$n ($test): closed in $label"
    return 0
  fi
  state=$(queue_release_state "$url" "$test" "$n" "$label") || return 1
  release_state_unchanged "$state" "$n" "$test"
}

close_issues() {
  local url=$1 test=$2 label=$3 numbers=$4 released=${5:-} checkout=${6:-} private_repo=${7:-} n failed=0
  [ -n "$numbers" ] || return 0
  if [ -z "$url" ] || [ -z "${REPORTS_WORK_TOKEN:-}" ]; then
    echo "::error::report queue URL or work token is missing" >&2
    return 1
  fi
  for n in $numbers; do
    if ! queue_close "${url%/}/api/v1/reports-work" "$test" "$n" "$label" "$released" "$checkout" "$private_repo"; then
      echo "::error::could not verify release closure for #$n (test=$test)" >&2
      failed=1
    fi
  done
  return "$failed"
}
