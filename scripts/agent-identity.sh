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
#        scripts/agent-identity.sh use <app config file> [--identity <name>] [--force]
#          Share an App that already exists (made for another repo, or a shared config kept
#          wherever you like): point this repo's identity at its config. Creates nothing and
#          copies no key, so every repo using it shares the one App and the one key.
#        scripts/agent-identity.sh setup [--identity <name>] --app-id <id> --key <file.pem>
#                                         [--config <file>] [--key-file <path>] [--force]
#          One-off per machine. Stores the App's private key in the keyring (secret-tool,
#          i.e. Seahorse on GNOME) and its id, slug and bot user in
#          ~/.config/sdlc/<owner>_<repo>/<name>.env.
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
# Env: SDLC_AGENT_CONFIG  config file (default ~/.config/sdlc/<owner>_<repo>/<identity>.env)
#      SDLC_PERSONAS  persona registry (default ~/.config/sdlc/<owner>_<repo>/personas.conf if it exists,
#                     which `create --per-persona` writes, else .claude/personas.conf here)
#      SDLC_AGENT_KEY_STORE_DIR  create: keep new Apps' keys as <app>.pem files here (= --keys-dir)
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
  local user="${XDG_CONFIG_HOME:-$HOME/.config}/sdlc/$(repo_key)/personas.conf"
  if [[ -f "$user" ]]; then echo "$user"; return; fi
  local top
  top="$(git rev-parse --show-toplevel 2>/dev/null || dirname "$(dirname "$self")")"
  echo "$top/.claude/personas.conf"
}

# Apps belong to one repo, so everything about them is kept per repo: owner/name becomes
# owner_name (same rule as create-agent-apps.py). Outside a GitHub checkout: _norepo.
repo_key() {
  local r
  r="$(repo_name 2>/dev/null)" || { echo _norepo; return; }
  r="${r,,}"
  sed -E 's/[^a-z0-9_.-]+/-/g' <<<"${r//\//_}"
}

# Use identity $1: sets where its config, key and token cache live.
use_identity() {
  identity="$1"
  [[ "$identity" =~ ^[a-z0-9-]+$ ]] || die "bad identity name: $identity"
  default_config="${XDG_CONFIG_HOME:-$HOME/.config}/sdlc/$(repo_key)/$identity.env"
  config="${SDLC_AGENT_CONFIG:-$default_config}"
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


# Load the identity's config. A config may be a pointer (SDLC_AGENT_USE=<file>) to one kept
# anywhere, which is how several repos and personas share one App: they all point at one
# file, which names one key. Sets $config to the file actually used.
load_config() {
  local hops=0
  unset SDLC_AGENT_APP_ID SDLC_AGENT_APP_SLUG SDLC_AGENT_BOT_ID SDLC_AGENT_KEY
  while :; do
    [[ -f "$config" ]] || return 1
    unset SDLC_AGENT_USE
    # shellcheck disable=SC1090
    source "$config"
    [[ -n "${SDLC_AGENT_USE:-}" ]] || break
    ((++hops <= 5)) || die "too many SDLC_AGENT_USE pointers from $config"
    config="$SDLC_AGENT_USE"
  done
  [[ -n "${SDLC_AGENT_APP_ID:-}" && -n "${SDLC_AGENT_APP_SLUG:-}" ]]
}

# The App's private key, from where its config says (SDLC_AGENT_KEY=keyring:<account> or
# file:<path>). Configs without it use the keyring entry named after the App.
private_key() {
  if [[ -n "${SDLC_AGENT_KEY_FILE:-}" ]]; then cat "$SDLC_AGENT_KEY_FILE"; return; fi
  local ref="${SDLC_AGENT_KEY:-keyring:github-app-private-key:${SDLC_AGENT_APP_SLUG:-}}"
  case "$ref" in
    file:*) cat "${ref#file:}" || die "can't read the key file ${ref#file:}" ;;
    keyring:*)
      command -v secret-tool >/dev/null || die "secret-tool not found; install libsecret-tools, or keep the key in a file (SDLC_AGENT_KEY=file:<path>)"
      secret-tool lookup service claude-sdlc account "${ref#keyring:}" \
        || die "no private key in the keyring under ${ref#keyring:}; run: $0 setup" ;;
    *) die "SDLC_AGENT_KEY in $config must be keyring:<account> or file:<path>, got: $ref" ;;
  esac
}

# Point this repo's identity at the config file $1 (unless it is that file).
write_pointer() {
  local target
  target="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
  [[ "$target" == "$default_config" ]] && return 0
  mkdir -p "$(dirname "$default_config")"
  {
    echo "# Points this repo's identity at a config kept elsewhere (agent-identity.sh)."
    echo "SDLC_AGENT_USE=$target"
  } > "$default_config"
}

# Refuse to replace an existing config unless --force: it may name an App other repos use.
guard_overwrite() {  # path force
  [[ -e "$1" && "$2" != 1 ]] || return 0
  die "$1 already exists (it may name an App other repos use). Use --force to replace it, or 'use' to point at it"
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
  local app_id="" key="" target="" key_file="" force=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --app-id) app_id="$2"; shift 2 ;;
      --key) key="$2"; shift 2 ;;
      --identity) use_identity "$2"; shift 2 ;;
      --config) target="$2"; shift 2 ;;
      --key-file) key_file="$2"; shift 2 ;;
      --force) force=1; shift ;;
      *) die "unknown setup option: $1" ;;
    esac
  done
  [[ -n "$app_id" && -f "$key" ]] || die "usage: $0 setup --app-id <id> --key <downloaded .pem> [--identity <name>] [--config <file>] [--key-file <path>] [--force]"
  openssl pkey -in "$key" -noout 2>/dev/null || die "$key isn't a private key"
  target="${target:-$default_config}"
  guard_overwrite "$target" "$force"
  [[ "$target" == "$default_config" ]] || guard_overwrite "$default_config" "$force"
  SDLC_AGENT_APP_ID="$app_id"
  local app slug bot_id ref
  app="$(SDLC_AGENT_KEY_FILE="$key" github GET /app)" || die "GitHub rejected the App id or key"
  slug="$(jq -r .slug <<<"$app")"
  # The key is stored under the App's own (globally unique) name, so it can't replace
  # another App's key. Storing the same App's key again just rewrites the same entry.
  if [[ -n "$key_file" ]]; then
    mkdir -p "$(dirname "$key_file")"
    (umask 077; cp "$key" "$key_file")
    ref="file:$(cd "$(dirname "$key_file")" && pwd)/$(basename "$key_file")"
  else
    command -v secret-tool >/dev/null || die "secret-tool not found; install libsecret-tools or pass --key-file <path>"
    secret-tool store --label "claude-sdlc GitHub App private key ($slug)" \
      service claude-sdlc account "github-app-private-key:$slug" < "$key"
    ref="keyring:github-app-private-key:$slug"
  fi
  bot_id="$(curl -fsS "$api/users/$slug%5Bbot%5D" | jq -r .id)" || bot_id=0
  mkdir -p "$(dirname "$target")"
  {
    echo "# claude-sdlc agent identity (scripts/agent-identity.sh). Not secret: the key is at"
    echo "# SDLC_AGENT_KEY. Several repos and personas may point at this file to share the App."
    echo "SDLC_AGENT_APP_ID=$app_id"
    echo "SDLC_AGENT_APP_SLUG=$slug"
    echo "SDLC_AGENT_BOT_ID=$bot_id"
    echo "SDLC_AGENT_KEY=$ref"
  } > "$target"
  write_pointer "$target"
  echo "wrote $target: $slug[bot] (app $app_id), key at $ref"
  echo "now delete the downloaded key file ($key)"
}

# Share an existing App: point this repo's identity at its config. Nothing is created on
# GitHub and no key is copied or changed.
use_app() {
  local target="" force=0
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --identity) use_identity "$2"; shift 2 ;;
      --force) force=1; shift ;;
      -*) die "unknown use option: $1" ;;
      *) target="$1"; shift ;;
    esac
  done
  [[ -f "$target" ]] || die "usage: $0 use <app config file> [--identity <name>] [--force]"
  local abs
  abs="$(cd "$(dirname "$target")" && pwd)/$(basename "$target")"
  config="$abs"
  load_config || die "$target isn't an App config (needs SDLC_AGENT_APP_ID and SDLC_AGENT_APP_SLUG)"
  if [[ -f "$default_config" && "$abs" != "$default_config" ]] \
    && ! grep -qxF "SDLC_AGENT_USE=$abs" "$default_config"; then
    guard_overwrite "$default_config" "$force"
  fi
  write_pointer "$abs"
  echo "$identity in $(repo_name) now uses $SDLC_AGENT_APP_SLUG[bot] ($abs)"
  if token >/dev/null 2>&1; then echo "ok: it can act on $(repo_name)"
  else echo "install it on $(repo_name): https://github.com/apps/$SDLC_AGENT_APP_SLUG/installations/new"
  fi
}

check() {
  load_config || { echo "not configured: see docs/agent-identity.md"; exit 1; }
  echo "identity: $identity, app: $SDLC_AGENT_APP_SLUG[bot] (id $SDLC_AGENT_APP_ID)"
  echo "repo: $(repo_name)"
  token >/dev/null && echo "ok: a token for this repo was issued"
}

use_identity "${SDLC_AGENT_IDENTITY_NAME:-agent}"

case "${1:-}" in
  setup) shift; setup "$@" ;;
  use) shift; use_app "$@" ;;
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
  key) load_config || exit 1; private_key ;;
  token) token ;;
  git-credential) shift; git_credential "$@" ;;
  env) shift; print_env "$@" ;;
  *) sed -n '2,49p' "$0" >&2; exit 2 ;;
esac
