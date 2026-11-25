#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Install, update or remove IngeTrazo Web on a Mac (macOS 13 Ventura or later).
#
# Does every step of the README's "Install on macOS" section:
#
#   1. Finds Python 3.10 to 3.14, or installs Python 3.13 with Homebrew.
#   2. Finds Git, or installs it (Homebrew, or Apple's command line tools).
#   3. Downloads IngeTrazo Web (or updates it if it is already there).
#   4. Creates its Python environment and installs the packages.
#   5. Adds a launchd agent that runs the server in the background and logs to
#      server.log in the data folder, and an "IngeTrazo Web" app that starts the
#      server if needed and opens it in the browser.
#   6. Starts the server and opens it in the browser.
#
# No administrator password is needed (unless Apple's command line tools must be installed).
# Run the script again at any time to update; use the same options as the first time.
#
# Usage:
#   bash install-macos.sh [options]
#   curl -fsSL https://raw.githubusercontent.com/felixriestra/ingetrazo-web-open/main/install-macos.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/felixriestra/ingetrazo-web-open/main/install-macos.sh | bash -s -- --network
#
# Options:
#   --install-dir DIR   Where the program goes. Default: ~/Library/Application Support/IngeTrazoWeb
#   --data-dir DIR      Where documents, revisions and users are kept. Default: ~/IngeTrazoWebData
#                       An update or --uninstall never deletes it (unless --remove-data is given).
#   --port N            The port the server listens on. Default: 8000
#   --network           Let other computers on the network use the server: creates an
#                       administrator account (--admin-name, default "admin") if none exists,
#                       prints its access token once, and listens on all addresses.
#   --admin-name NAME   The administrator account --network creates.
#   --no-autostart      Do not start the server when you log in (the app still starts it).
#   --uninstall         Stop the server and remove the program, the agent and the app.
#   --remove-data       With --uninstall, also delete the data folder (every document).
#   --repository URL    Git repository to install from.
#   --branch NAME       Branch to install. Default: main
#   -h, --help          Show this help.
#
# Advanced (environment): INGETRAZO_AGENT_LABEL (default com.ingetrazo.web) and
# INGETRAZO_APP_DIR (default /Applications, or ~/Applications when that is not writable);
# INGETRAZO_NO_BROWSER=1 does not open the browser at the end.

set -euo pipefail

INSTALL_DIR="$HOME/Library/Application Support/IngeTrazoWeb"
DATA_DIR="$HOME/IngeTrazoWebData"
PORT=8000
NETWORK=0
ADMIN_NAME=admin
AUTOSTART=1
UNINSTALL=0
REMOVE_DATA=0
REPOSITORY=https://github.com/felixriestra/ingetrazo-web-open.git
BRANCH=main
LABEL="${INGETRAZO_AGENT_LABEL:-com.ingetrazo.web}"

step() { printf '\033[36m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }
fail() { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }
usage() { sed -n '3,42p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//'; exit 0; }

need_value() { [ $# -ge 2 ] && [ -n "$2" ] || fail "$1 needs a value."; }
while [ $# -gt 0 ]; do
    case "$1" in
        --install-dir) need_value "$@"; INSTALL_DIR="$2"; shift 2 ;;
        --data-dir)    need_value "$@"; DATA_DIR="$2"; shift 2 ;;
        --port)        need_value "$@"; PORT="$2"; shift 2 ;;
        --network)     NETWORK=1; shift ;;
        --admin-name)  need_value "$@"; ADMIN_NAME="$2"; shift 2 ;;
        --no-autostart) AUTOSTART=0; shift ;;
        --uninstall)   UNINSTALL=1; shift ;;
        --remove-data) REMOVE_DATA=1; shift ;;
        --repository)  need_value "$@"; REPOSITORY="$2"; shift 2 ;;
        --branch)      need_value "$@"; BRANCH="$2"; shift 2 ;;
        -h|--help)     usage ;;
        *) fail "Unknown option: $1 (see --help)" ;;
    esac
done

case "$PORT" in ''|*[!0-9]*) fail "--port must be a number." ;; esac
[ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || fail "--port must be between 1 and 65535."
case "$ADMIN_NAME" in ''|*[!A-Za-z0-9._-]*) fail "--admin-name may use letters, digits, '.', '_' and '-'." ;; esac
[ "$(uname -s)" = Darwin ] || fail "This script is for macOS. See the README for Windows and Linux."

APP_DIR="$INSTALL_DIR/app"
VENV_PYTHON="$APP_DIR/.venv/bin/python"
AGENT="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
URL="http://127.0.0.1:$PORT"
if [ -n "${INGETRAZO_APP_DIR:-}" ]; then
    APPS="$INGETRAZO_APP_DIR"
elif [ -w /Applications ]; then
    APPS=/Applications
else
    APPS="$HOME/Applications"
fi
LAUNCHER_APP="$APPS/IngeTrazo Web.app"

# Stop the server (the launchd agent, and anything else run from this install's Python).
stop_server() {
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
        launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
        note "Stopped the running server."
    fi
    pkill -f "^$APP_DIR/.venv/bin/python" 2>/dev/null || true
    sleep 1
}

# Escape text for an XML (plist) string.
xml() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

# ---------------------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------------------

if [ "$UNINSTALL" = 1 ]; then
    step "Removing IngeTrazo Web"
    stop_server
    for path in "$AGENT" "$LAUNCHER_APP" "$HOME/Applications/IngeTrazo Web.app" "$INSTALL_DIR"; do
        if [ -e "$path" ]; then rm -rf "$path"; note "Removed $path"; fi
    done
    if [ "$REMOVE_DATA" = 1 ] && [ -e "$DATA_DIR" ]; then
        rm -rf "$DATA_DIR"
        note "Removed $DATA_DIR and every document in it."
    elif [ -e "$DATA_DIR" ]; then
        note "Kept your documents in $DATA_DIR (delete the folder yourself, or use --remove-data)."
    fi
    step "Done."
    exit 0
fi

# ---------------------------------------------------------------------------------------
# Install or update
# ---------------------------------------------------------------------------------------

macos_major=$(sw_vers -productVersion | cut -d. -f1)
[ "$macos_major" -ge 13 ] || fail "IngeTrazo Web needs macOS 13 Ventura or later (this Mac has $(sw_vers -productVersion))."

echo
printf '\033[1mIngeTrazo Web installer\033[0m\n'
note "Program:   $INSTALL_DIR"
note "Documents: $DATA_DIR"
echo

BREW=""
for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [ -x "$candidate" ]; then BREW="$candidate"; break; fi
done
if [ -z "$BREW" ] && command -v brew >/dev/null 2>&1; then BREW="$(command -v brew)"; fi

# A Python 3.10 to 3.14, preferring 3.13. /usr/bin/python3 is Apple's 3.9 (or a stub that
# asks to install the command line tools), so it is never used.
find_python() {
    local candidate
    for candidate in \
        python3.13 python3.14 python3.12 python3.11 python3.10 python3 \
        /opt/homebrew/bin/python3.13 /usr/local/bin/python3.13 \
        /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
        /opt/homebrew/bin/python3.14 /usr/local/bin/python3.14 \
        /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 \
        /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12 \
        /Library/Frameworks/Python.framework/Versions/3.12/bin/python3; do
        local path
        path=$(command -v "$candidate" 2>/dev/null) || continue
        [ "$path" = /usr/bin/python3 ] && continue
        if "$path" -c 'import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 14) else 1)' 2>/dev/null; then
            echo "$path"
            return 0
        fi
    done
    return 1
}

# Git, without touching /usr/bin/git when the command line tools are missing (it would
# open Apple's install dialog).
find_git() {
    local path
    for path in /opt/homebrew/bin/git /usr/local/bin/git; do
        if [ -x "$path" ]; then echo "$path"; return 0; fi
    done
    if xcode-select -p >/dev/null 2>&1 && [ -x /usr/bin/git ]; then echo /usr/bin/git; return 0; fi
    path=$(command -v git 2>/dev/null) || return 1
    [ "$path" = /usr/bin/git ] && return 1
    echo "$path"
}

step "Looking for Python 3.10 to 3.14"
if ! PYTHON=$(find_python); then
    if [ -n "$BREW" ]; then
        step "Installing Python 3.13 with Homebrew"
        "$BREW" install python@3.13
        PYTHON=$(find_python) || fail "Python was installed but cannot be found. Open a new Terminal window and run this script again."
    else
        open "https://www.python.org/downloads/macos/" 2>/dev/null || true
        fail "Python 3.10 to 3.14 is not installed. Install it from python.org (the page is now open) or with Homebrew (https://brew.sh), then run this script again."
    fi
fi
note "Using $PYTHON ($("$PYTHON" -c 'import platform; print(platform.python_version())'))"

step "Looking for Git"
if ! GIT=$(find_git); then
    if [ -n "$BREW" ]; then
        step "Installing Git with Homebrew"
        "$BREW" install git
        GIT=$(find_git) || fail "Git was installed but cannot be found. Open a new Terminal window and run this script again."
    else
        xcode-select --install 2>/dev/null || true
        fail "Git is not installed. A window now offers Apple's command line tools, which include it: click Install, wait for it to finish, then run this script again."
    fi
fi
# pip needs git on the PATH to install the SketchUp reader.
PATH="$(dirname "$GIT"):$PATH"
export PATH
note "Using $GIT"

mkdir -p "$INSTALL_DIR" "$DATA_DIR" "$(dirname "$AGENT")"
stop_server

if [ -d "$APP_DIR/.git" ]; then
    step "Updating IngeTrazo Web"
    "$GIT" -C "$APP_DIR" pull --ff-only || fail "Updating the program (git pull) failed."
elif [ -e "$APP_DIR" ]; then
    fail "$APP_DIR exists but is not a Git checkout. Move it away, or choose another --install-dir."
else
    step "Downloading IngeTrazo Web"
    "$GIT" clone --depth 1 --branch "$BRANCH" "$REPOSITORY" "$APP_DIR" || fail "Downloading the program (git clone) failed."
fi

if [ ! -x "$VENV_PYTHON" ]; then
    step "Creating the Python environment"
    "$PYTHON" -m venv "$APP_DIR/.venv" || fail "Creating the Python environment failed."
fi

step "Installing the Python packages (a few minutes the first time)"
cd "$APP_DIR"
"$VENV_PYTHON" -m pip install --quiet --disable-pip-version-check --upgrade pip || fail "Updating pip failed."
"$VENV_PYTHON" -m pip install --quiet --disable-pip-version-check \
    -r requirements.txt -r web/backend/requirements.txt || fail "Installing the packages failed."
"$VENV_PYTHON" -c 'import PySide6, numpy, fastapi, uvicorn, openskp, manifold3d, ezdxf' \
    || fail "The packages were installed but do not load."

export INGETRAZO_WEB_DATA="$DATA_DIR"
TOKEN=""
if [ "$NETWORK" = 1 ]; then
    step "Setting up accounts"
    users=$("$VENV_PYTHON" -m web.backend users list) || fail "Could not read the user accounts."
    if [ -n "$users" ]; then
        note "Accounts already exist; keeping them."
    else
        created=$("$VENV_PYTHON" -m web.backend users add "$ADMIN_NAME" --admin) \
            || fail "Could not create the account '$ADMIN_NAME'."
        TOKEN=$(printf '%s\n' "$created" | tail -n 1)
    fi
    HOST=0.0.0.0
else
    HOST=127.0.0.1
fi

step "Adding the background service"
if [ "$AUTOSTART" = 1 ]; then
    run_at_load='<true/>'
    keep_alive='<dict><key>SuccessfulExit</key><false/></dict>'   # restart it if it crashes
else
    run_at_load='<false/>'
    keep_alive='<false/>'
fi
cat > "$AGENT" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<!-- Written by install-macos.sh. Running the installer again rewrites it. -->
<plist version="1.0">
<dict>
  <key>Label</key><string>$(xml "$LABEL")</string>
  <key>WorkingDirectory</key><string>$(xml "$APP_DIR")</string>
  <key>ProgramArguments</key>
  <array>
    <string>$(xml "$VENV_PYTHON")</string>
    <string>-m</string><string>web.backend</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>INGETRAZO_WEB_DATA</key><string>$(xml "$DATA_DIR")</string>
    <key>INGETRAZO_WEB_HOST</key><string>$HOST</string>
    <key>INGETRAZO_WEB_PORT</key><string>$PORT</string>
    <key>QT_QPA_PLATFORM</key><string>offscreen</string>
  </dict>
  <key>RunAtLoad</key>$run_at_load
  <key>KeepAlive</key>$keep_alive
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>$(xml "$DATA_DIR/server.log")</string>
  <key>StandardErrorPath</key><string>$(xml "$DATA_DIR/server.log")</string>
</dict>
</plist>
EOF
plutil -lint "$AGENT" >/dev/null || fail "The launchd agent file is not valid: $AGENT"
if [ "$AUTOSTART" = 1 ]; then
    note "The server will start each time you log in."
fi

step "Adding the IngeTrazo Web app"
mkdir -p "$APPS"
rm -rf "$LAUNCHER_APP"
script_file=$(mktemp -t ingetrazo-app)
cat > "$script_file" <<EOF
-- Written by install-macos.sh: start the IngeTrazo Web server if needed and open it.
do shell script "launchctl kickstart $DOMAIN/$LABEL >/dev/null 2>&1 || true; for i in \$(seq 1 60); do curl -sf $URL/api/v1/health >/dev/null && exit 0; sleep 1; done; exit 1"
open location "$URL/"
EOF
osacompile -o "$LAUNCHER_APP" "$script_file" >/dev/null 2>&1 || fail "Could not create $LAUNCHER_APP."
rm -f "$script_file"
note "$LAUNCHER_APP starts the server if needed and opens it."

step "Starting the server"
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    fail "Another program already uses port $PORT. Run the script again with --port and another number."
fi
launchctl bootstrap "$DOMAIN" "$AGENT" || fail "launchd refused the agent $AGENT."
launchctl kickstart "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
ready=0
for _ in $(seq 1 60); do
    if curl -sf "$URL/api/v1/health" >/dev/null 2>&1; then ready=1; break; fi
    sleep 1
done
[ "$ready" = 1 ] || fail "The server did not start within a minute. See $DATA_DIR/server.log."
[ -n "${INGETRAZO_NO_BROWSER:-}" ] || open "$URL/"

echo
printf '\033[32mIngeTrazo Web is running at %s/\033[0m\n' "$URL"
note "Open it again with the IngeTrazo Web app in $APPS."
note "Log: $DATA_DIR/server.log"
if [ "$NETWORK" = 1 ]; then
    addresses=""
    for interface in en0 en1 en2; do
        address=$(ipconfig getifaddr "$interface" 2>/dev/null || true)
        [ -n "$address" ] && addresses="$addresses http://$address:$PORT/"
    done
    [ -n "$addresses" ] && note "From other computers:$addresses"
    note "If macOS asks whether Python may accept incoming connections, click Allow."
    note "Without HTTPS, access tokens travel in plain text; see the README before exposing it beyond your network."
    if [ -n "$TOKEN" ]; then
        echo
        printf "\033[33mAccess token for '%s' (shown only once; keep it safe):\n%s\033[0m\n" "$ADMIN_NAME" "$TOKEN"
    fi
fi
note "Update: run this script again. Remove: run it with --uninstall."
