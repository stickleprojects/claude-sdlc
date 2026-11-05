#!/usr/bin/env bash
# Stands in for curl in the agent-identity tests: answers like GitHub's API.
# Each endpoint (app, installation, token, other) answers 2xx with a canned body, unless
#   $LOG/codes-<endpoint>  lists status codes to answer with, one per call; the last one
#                          sticks. "timeout" means curl fails as if GitHub never answered.
#   $LOG/body-<endpoint>   replaces the body.
# Logs each call to $LOG/curl and the JWT it was given to $LOG/jwt.
for a in "$@"; do
  [[ "$a" == "Authorization: Bearer "* ]] && echo "${a#*Bearer }" > "$LOG/jwt"
done
echo "$*" >> "$LOG/curl"
want_code=0
for a in "$@"; do [[ "$a" == *http_code* ]] && want_code=1; done
url="${*: -1}"
case "$url" in
  *access_tokens) name=token code=201 body='{"token":"ghs_test","expires_at":"2099-01-01T00:00:00Z"}' ;;
  */installation) name=installation code=200 body='{"id": 77}' ;;
  */app) name=app code=200 body='{"id": 123, "slug": "stickle-claude"}' ;;
  *) name=other code=200 body='{}' ;;
esac
[[ -f "$LOG/body-$name" ]] && body="$(cat "$LOG/body-$name")"
codes="$LOG/codes-$name"
if [[ -f "$codes" ]]; then
  code="$(head -1 "$codes")"
  if (($(wc -l < "$codes") > 1)); then sed -i 1d "$codes"; fi
fi
[[ "$code" == timeout ]] && exit 28
printf '%s' "$body"
((want_code)) && printf '\n%s' "$code"
exit 0
