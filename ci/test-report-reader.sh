#!/usr/bin/env bash
set -euo pipefail

ci=$(dirname "$0")
base=${1%/}/api/v1/reports-work
token=${REPORTS_READ_TOKEN:-}
if [[ -z $token || $token == - ]]; then
    echo 'Test report reader key is not configured'
    exit 0
fi

request() {
    bash "$ci/retry.sh" read curl -fsS --max-time 15 -H "Authorization: Bearer $token" "$@"
}

status=$(bash "$ci/retry.sh" read curl -sS --max-time 15 -o /dev/null -w '%{http_code}' "$base/list?limit=1")
[[ $status == 401 ]] || { echo "::error::Report list without a key returned HTTP $status"; exit 1; }

request "$base/statuses?state=open" |
    jq -e '.success == true and (.data | type == "object") and ((.data.open // 0) | type == "number")' >/dev/null
echo 'Report status counts verified'
page=$(request "$base/list?state=open&sort=updated&order=desc&limit=1")
jq -e '.success == true and ((.data.items // []) | type == "array" and length <= 1 and all((.state // "open") == "open"))' <<<"$page" >/dev/null

echo 'Report list filters verified'

number=$(jq -r '.data.items[0].number // empty' <<<"$page")
if [[ -n $number ]]; then
    request --get "$base/get" --data-urlencode "number=$number" |
        jq -e --argjson number "$number" '.success == true and .data.summary.number == $number' >/dev/null
fi

if jq -e '.data.nextUpdated != null' <<<"$page" >/dev/null; then
    jq -e '.data.nextUpdated.number == .data.items[0].number and .data.nextUpdated.updatedAt == (.data.items[0].updatedAt // 0)' <<<"$page" >/dev/null
    updated=$(jq -r '.data.nextUpdated.updatedAt' <<<"$page")
    request --get "$base/list" --data-urlencode state=open --data-urlencode sort=updated --data-urlencode order=desc \
        --data-urlencode limit=1 --data-urlencode "after=$number" --data-urlencode "afterUpdated=$updated" |
        jq -e --argjson number "$number" --argjson updated "$updated" '
          .success == true and ((.data.items // []) | type == "array" and length <= 1 and
          all((.state // "open") == "open" and ((.updatedAt // 0) < $updated or ((.updatedAt // 0) == $updated and .number < $number))))
        ' >/dev/null
    echo 'Next report page verified'
fi

echo 'Test report reader authorization, filters and cursor checks passed'
