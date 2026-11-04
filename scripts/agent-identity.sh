#!/usr/bin/env bash
# Give Claude sessions their own GitHub identity: a GitHub App, so commits, pushes, PRs and
# replies show as "<app>[bot]" instead of the person running the session.
#
# Which persona uses which identity is set in .claude/personas.conf. The default identity is
# `agent`; `--persona <name>` picks the identity that persona is mapped to.
#
# Usage: scripts/agent-identity.sh create [--per-persona | --groups <g>] [--name <app name>] [--org <org>]
#          Create the App(s) in your browser with GitHub's manifest flow, and store them as
#          `setup` would. In a terminal it first asks: one App for everything, or which personas
#          get their own App and which App each other persona shares.
#        scripts/agent-identity.sh identities
#          List the github-app identities the personas use, one per line.
#        scripts/agent-identity.sh identity-of <persona>
#          Print the identity a persona (local or CI) acts as.
#        scripts/agent-identity.sh setup [--identity <name>] --app-id <id> --key <file.pem>
#          One-off per machine. Stores the App's private key in the keyring (secret-tool,
#          i.e. Seahorse on GNOME) and its id, slug and bot user in ~/.config/sdlc/<name>.env.
#        scripts/agent-identity.sh check
#          Is the App configured, installed on this repo, and able to issue a token?
#        scripts/agent-identity.sh show
#          Print "<app id> <app slug>" (for bootstrap-github.sh); exit 1 if not configured.
#        scripts/agent-identity.sh key
#          Print the private key, for storing it as the SDLC_AGENT_APP_KEY Actions secret.
#        scripts/agent-identity.sh token
#          Print an installation token for this repo (cached; renewed when <10 minutes remain).
#        scripts/agent-identity.sh git-credential get
#          Git credential helper: answers with the token for github.com.
#        scripts/agent-identity.sh env [--persona <name>]
#          Print `export` lines that make git and gh in a session act as the App. Used by
#          scripts/agent-session.sh and the SessionStart hook in docs/agent-identity.md.
#          Prints nothing when the App isn't configured, so sessions fall back to the person.
#
# Env: SDLC_AGENT_CONFIG  config file (default ~/.config/sdlc/<identity>.env)
#      SDLC_PERSONAS  persona registry (default ~/.config/sdlc/personas.conf if it exists,
#                     which `create --per-persona` writes, else .claude/personas.conf here)
#      SDLC_AGENT_KEY_STORE_DIR  keep private keys as <identity>.pem files here, not the keyring
#      SDLC_AGENT_KEY_FILE  read the private key from this file instead of the keyring
#      SDLC_AGENT_REPO  owner/name (default: from `git remote get-url origin`)
#      SDLC_GITHUB_API  API base URL (default https://api.github.com; tests point it elsewhere)
#
# Tokens last one hour and are scoped to this repo's installation. Nothing long-lived is
# written to disk: the key stays in the keyring and the token cache lives in $XDG_RUNTIME_DIR.
set -euo pipefail

self="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
api="${SDLC_GITHUB_API:-https://api.github.com}"
runtime="${XDG_RUNTIME_DIR:-${TMPDIR:-/tmp}}/sdlc-agent-$(id -u)"

die() { echo "agent-identity: $*" >&2; exit 1; }

personas_file() {
  if [[ -n "${SDLC_PERSONAS:-}" ]]; then echo "$SDLC_PERSONAS"; return; fi
  local user="${XDG_CONFIG_HOME:-$HOME/.config}/sdlc/personas.conf"
  if [[ -f "$user" ]]; then echo "$user"; return; fi
  local top
  top="$(git rev-parse --show-toplevel 2>/dev/null || dirname "$(dirname "$self")")"
  echo "$top/.claude/personas.conf"
}

# Use identity $1: sets where its config, key and token cache live.
use_identity() {
  identity="$1"
  [[ "$identity" =~ ^[a-z0-9-]+$ ]] || die "bad identity name: $identity"
  config="${SDLC_AGENT_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/sdlc/$identity.env}"
  keyring_attrs=(service claude-sdlc account "github-app-private-key:$identity")
}

# The identity a persona acts as, from the registry. Only github-app identities qualify, and
# only local personas unless $2 is "any" (bootstrap asks for the CI persona spec-ci).
identity_for() {
  local file line
  file="$(personas_file)"
  [[ -f "$file" ]] || die "no persona registry at $file"
  line="$(awk -v p="$1" '$1 == "persona" && $2 == p {print $3, $4}' "$file")"
  [[ -n "$line" ]] || die "unknown persona '$1'; the personas are listed in $file"
  read -r id where <<<"$line"
  [[ "$where" == local || "${2:-}" == any ]] || die "persona '$1' runs in $where, not in a local session"
  awk -v i="$id" '$1 == "identity" && $2 == i {print $3}' "$file" | grep -qx github-app \
    || die "persona '$1' maps to identity '$id', which isn't a github-app identity in $file"
  echo "$id"
}

use_identity agent

load_config() {
  [[ -f "$config" ]] || return 1
  # shellcheck disable=SC1090
  source "$config"
  [[ -n "${SDLC_AGENT_APP_ID:-}" && -n "${SDLC_AGENT_APP_SLUG:-}" ]]
}

private_key() {
  if [[ -n "${SDLC_AGENT_KEY_FILE:-}" ]]; then cat "$SDLC_AGENT_KEY_FILE"; return; fi
  if [[ -n "${SDLC_AGENT_KEY_STORE_DIR:-}" ]]; then cat "$SDLC_AGENT_KEY_STORE_DIR/$identity.pem"; return; fi
  command -v secret-tool >/dev/null || die "secret-tool not found; install libsecret-tools or set SDLC_AGENT_KEY_FILE"
  secret-tool lookup "${keyring_attrs[@]}" || die "no private key in the keyring; run: $0 setup"
}

b64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }

# A JWT signed with the App's key, valid for 9 minutes (GitHub allows 10).
app_jwt() {
  local now header payload unsigned sig keyfile
  now="$(date +%s)"
  header="$(printf '{"alg":"RS256","typ":"JWT"}' | b64url)"
  payload="$(printf '{"iat":%d,"exp":%d,"iss":"%s"}' $((now - 60)) $((now + 540)) "$SDLC_AGENT_APP_ID" | b64url)"
  unsigned="$header.$payload"
  keyfile="$(umask 077; mktemp)"
  if ! private_key > "$keyfile" \
    || ! sig="$(printf '%s' "$unsigned" | openssl dgst -sha256 -sign "$keyfile" | b64url)"; then
    rm -f "$keyfile"
    die "couldn't sign the App token request with the private key"
  fi
  rm -f "$keyfile"
  printf '%s.%s\n' "$unsigned" "$sig"
}

github() {  # method path [json-body], authenticated as the App (JWT)
  local args=(-fsS -X "$1" -H "Accept: application/vnd.github+json"
    -H "Authorization: Bearer $(app_jwt)" -H "X-GitHub-Api-Version: 2022-11-28")
  [[ $# -ge 3 ]] && args+=(-d "$3")
  curl "${args[@]}" "$api$2"
}

repo_name() {
  if [[ -n "${SDLC_AGENT_REPO:-}" ]]; then echo "$SDLC_AGENT_REPO"; return; fi
  local url
  url="$(git remote get-url origin 2>/dev/null)" || die "no origin remote; set SDLC_AGENT_REPO=owner/name"
  url="${url%.git}"
  url="${url#git@github.com:}"
  url="${url#https://github.com/}"
  url="${url#ssh://git@github.com/}"
  [[ "$url" == */* ]] || die "can't read owner/name from origin: $url"
  echo "$url"
}

token() {
  load_config || die "not configured; run: $0 setup --app-id <id> --key <file.pem>"
  local repo cache now expires json id
  repo="$(repo_name)"
  mkdir -p "$runtime" && chmod 700 "$runtime"
  cache="$runtime/$identity-${repo//\//_}.json"
  now="$(date +%s)"
  if [[ -f "$cache" ]]; then
    expires="$(jq -r '.expires_epoch // 0' "$cache")"
    if ((expires - now > 600)); then jq -r .token "$cache"; return; fi
  fi
  id="$(github GET "/repos/$repo/installation" | jq -r .id)" \
    || die "the App '$SDLC_AGENT_APP_SLUG' isn't installed on $repo: https://github.com/apps/$SDLC_AGENT_APP_SLUG/installations/new"
  json="$(github POST "/app/installations/$id/access_tokens")" || die "GitHub refused a token for $repo"
  [[ "$(jq -r '.token // empty' <<<"$json")" == gh* ]] || die "GitHub's reply has no token for $repo"
  expires="$(date -d "$(jq -r .expires_at <<<"$json")" +%s 2>/dev/null || echo $((now + 3000)))"
  (umask 077; jq --argjson e "$expires" '{token, expires_epoch: $e}' <<<"$json" > "$cache")
  jq -r .token <<<"$json"
}

git_credential() {
  [[ "${1:-}" == get ]] || exit 0  # store/erase: nothing to do
  local line host=""
  while IFS= read -r line && [[ -n "$line" ]]; do
    [[ "$line" == host=* ]] && host="${line#host=}"
  done
  [[ "$host" == github.com ]] || exit 0
  printf 'username=x-access-token\npassword=%s\n' "$(token)"
}

print_env() {
  local persona=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --persona) persona="$2"; shift 2 ;;
      *) die "unknown env option: $1" ;;
    esac
  done
  if [[ -n "$persona" ]]; then use_identity "$(identity_for "$persona")"; fi
  if ! load_config; then
    echo "agent-identity: identity '$identity' not configured; this session acts as you (see docs/agent-identity.md)" >&2
    return 0
  fi
  local bin="$runtime/bin" real_gh name email requester
  real_gh="$(command -v gh || true)"
  [[ -n "$real_gh" && "$real_gh" != "$bin/gh" ]] || die "gh not found on PATH"
  mkdir -p "$bin" && chmod 700 "$runtime"
  # A gh that asks for a fresh token on every call, since installation tokens expire hourly.
  cat > "$bin/gh" <<EOF
#!/usr/bin/env bash
GH_TOKEN="\$(SDLC_AGENT_IDENTITY_NAME='$identity' "$self" token)" || exit 1
export GH_TOKEN
exec "$real_gh" "\$@"
EOF
  chmod 700 "$bin/gh"
  name="$SDLC_AGENT_APP_SLUG[bot]"
  email="${SDLC_AGENT_BOT_ID:-0}+$SDLC_AGENT_APP_SLUG[bot]@users.noreply.github.com"
  requester="$(git config user.name 2>/dev/null || true)"
  cat <<EOF
export SDLC_AGENT_IDENTITY='$name' SDLC_AGENT_IDENTITY_NAME='$identity'
export SDLC_AGENT_PERSONA='${persona}'
export SDLC_AGENT_REQUESTED_BY='${requester//\'/}'
export PATH='$bin':"\$PATH"
export GIT_AUTHOR_NAME='$name' GIT_AUTHOR_EMAIL='$email'
export GIT_COMMITTER_NAME='$name' GIT_COMMITTER_EMAIL='$email'
export GIT_CONFIG_COUNT=3
export GIT_CONFIG_KEY_0='credential.https://github.com.helper' GIT_CONFIG_VALUE_0=''
export GIT_CONFIG_KEY_1='credential.https://github.com.helper' GIT_CONFIG_VALUE_1='!SDLC_AGENT_IDENTITY_NAME=$identity "$self" git-credential'
export GIT_CONFIG_KEY_2='url.https://github.com/.insteadOf' GIT_CONFIG_VALUE_2='git@github.com:'
EOF
}

setup() {
  local app_id="" key=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --app-id) app_id="$2"; shift 2 ;;
      --identity) use_identity "$2"; shift 2 ;;
      --key) key="$2"; shift 2 ;;
      *) die "unknown setup option: $1" ;;
    esac
  done
  [[ -n "$app_id" && -f "$key" ]] || die "usage: $0 setup --app-id <id> --key <downloaded .pem>"
  openssl pkey -in "$key" -noout 2>/dev/null || die "$key isn't a private key"
  if [[ -z "${SDLC_AGENT_KEY_FILE:-}" ]]; then
    command -v secret-tool >/dev/null || die "secret-tool not found; install libsecret-tools"
    secret-tool store --label "claude-sdlc GitHub App private key ($identity)" "${keyring_attrs[@]}" < "$key"
    echo "stored the private key in the keyring (Seahorse: 'claude-sdlc GitHub App private key ($identity)')"
  fi
  SDLC_AGENT_APP_ID="$app_id"
  local app slug bot_id
  app="$(SDLC_AGENT_KEY_FILE="${SDLC_AGENT_KEY_FILE:-$key}" github GET /app)" || die "GitHub rejected the App id or key"
  slug="$(jq -r .slug <<<"$app")"
  bot_id="$(curl -fsS "$api/users/$slug%5Bbot%5D" | jq -r .id)" || bot_id=0
  mkdir -p "$(dirname "$config")"
  cat > "$config" <<EOF
# claude-sdlc agent identity (scripts/agent-identity.sh). Not secret: the key is in the keyring.
SDLC_AGENT_APP_ID=$app_id
SDLC_AGENT_APP_SLUG=$slug
SDLC_AGENT_BOT_ID=$bot_id
EOF
  echo "wrote $config: $slug[bot] (app $app_id)"
  echo "now delete the downloaded key file ($key); the keyring holds the only copy you need"
}

check() {
  load_config || { echo "not configured: see docs/agent-identity.md"; exit 1; }
  echo "identity: $identity, app: $SDLC_AGENT_APP_SLUG[bot] (id $SDLC_AGENT_APP_ID)"
  echo "repo: $(repo_name)"
  token >/dev/null && echo "ok: a token for this repo was issued"
}

[[ -n "${SDLC_AGENT_IDENTITY_NAME:-}" ]] && use_identity "$SDLC_AGENT_IDENTITY_NAME"

case "${1:-}" in
  setup) shift; setup "$@" ;;
  create)  # always from the repo's registry, so re-running doesn't stack on an old override
    shift
    top="$(git rev-parse --show-toplevel 2>/dev/null || dirname "$(dirname "$self")")"
    exec python3 "$(dirname "$self")/create-agent-apps.py" --registry "$top/.claude/personas.conf" "$@" ;;
  identity-of) identity_for "${2:?persona}" any ;;
  identities)
    file="$(personas_file)"
    awk '$1 == "identity" && $3 == "github-app" {k[$2] = 1} $1 == "persona" {u[$3] = 1}
         END {for (i in u) if (i in k) print i}' "$file" | sort ;;
  check) check ;;
  show) load_config || exit 1; echo "$SDLC_AGENT_APP_ID $SDLC_AGENT_APP_SLUG" ;;
  key) private_key ;;
  token) token ;;
  git-credential) shift; git_credential "$@" ;;
  env) shift; print_env "$@" ;;
  *) sed -n '2,42p' "$0" >&2; exit 2 ;;
esac
