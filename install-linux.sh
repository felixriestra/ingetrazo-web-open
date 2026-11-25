#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Install, update or remove IngeTrazo Web on a Linux server. Run it as root (with sudo).
#
# Does every step of the README's "Install on a Linux web server" section:
#
#   1. Installs the system packages (apt on Debian and Ubuntu, dnf on Fedora and RHEL).
#   2. Creates the service user "ingetrazo" and downloads IngeTrazo Web to /opt/ingetrazo/app
#      (or updates it if it is already there).
#   3. Creates its Python environment and installs the packages.
#   4. Creates the first administrator account and prints its access token once.
#   5. Runs it as the systemd service "ingetrazo-web", started at boot.
#   6. With --domain, installs Caddy and serves the site over HTTPS with a free certificate.
#
# Run the script again at any time to update; use the same options as the first time.
#
# Usage:
#   sudo bash install-linux.sh [options]
#   curl -fsSL https://raw.githubusercontent.com/felixriestra/ingetrazo-web-open/main/install-linux.sh | sudo bash
#   curl -fsSL https://raw.githubusercontent.com/felixriestra/ingetrazo-web-open/main/install-linux.sh | sudo bash -s -- --domain ingetrazo.example.com
#
# Options:
#   --domain NAME       Serve https://NAME through Caddy (installed if needed). The name must
#                       already point to this server, and ports 80 and 443 must be reachable.
#   --network           Serve plain HTTP on all addresses at --port instead (no HTTPS: access
#                       tokens travel in plain text; for a trusted network only).
#   --port N            The port the service listens on. Default: 8000
#   --admin-name NAME   The first administrator account. Default: admin
#   --install-dir DIR   The service user's home; the program goes in DIR/app. Default: /opt/ingetrazo
#   --data-dir DIR      Documents, revisions and users. Default: /opt/ingetrazo/data
#                       An update or --uninstall never deletes it (unless --remove-data is given).
#   --no-service        Install only; do not create or start the systemd service (for
#                       containers, or to run it your own way).
#   --uninstall         Stop and remove the service and the program. Keeps the data folder
#                       and the service user.
#   --remove-data       With --uninstall, also delete the data folder and the service user.
#   --repository URL    Git repository to install from.
#   --branch NAME       Branch to install. Default: main
#   -h, --help          Show this help.
#
# Without --domain or --network the service listens on 127.0.0.1 only: reach it through an
# SSH tunnel (ssh -L 8000:127.0.0.1:8000 server), or put your own reverse proxy in front.

set -euo pipefail

DOMAIN=""
NETWORK=0
PORT=8000
ADMIN_NAME=admin
INSTALL_DIR=/opt/ingetrazo
DATA_DIR=""
SERVICE=1
UNINSTALL=0
REMOVE_DATA=0
REPOSITORY=https://github.com/felixriestra/ingetrazo-web-open.git
BRANCH=main
SERVICE_USER=ingetrazo
UNIT_NAME=ingetrazo-web
UNIT=/etc/systemd/system/$UNIT_NAME.service
CADDYFILE=/etc/caddy/Caddyfile
MARK="# Written by install-linux.sh (IngeTrazo Web)."

step() { printf '\033[36m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }
fail() { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }
usage() { sed -n '3,44p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//'; exit 0; }

need_value() { [ $# -ge 2 ] && [ -n "$2" ] || fail "$1 needs a value."; }
while [ $# -gt 0 ]; do
    case "$1" in
        --domain)      need_value "$@"; DOMAIN="$2"; shift 2 ;;
        --network)     NETWORK=1; shift ;;
        --port)        need_value "$@"; PORT="$2"; shift 2 ;;
        --admin-name)  need_value "$@"; ADMIN_NAME="$2"; shift 2 ;;
        --install-dir) need_value "$@"; INSTALL_DIR="$2"; shift 2 ;;
        --data-dir)    need_value "$@"; DATA_DIR="$2"; shift 2 ;;
        --no-service)  SERVICE=0; shift ;;
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
case "$DOMAIN" in *[!A-Za-z0-9.-]*) fail "--domain must be a host name such as ingetrazo.example.com." ;; esac
[ -z "$DOMAIN" ] || [ "$NETWORK" = 0 ] || fail "Use --domain or --network, not both."
case "$INSTALL_DIR" in /*) ;; *) fail "--install-dir must be an absolute path." ;; esac
[ "$(uname -s)" = Linux ] || fail "This script is for Linux. See the README for macOS and Windows."
[ "$(id -u)" = 0 ] || fail "Run it as root: sudo bash install-linux.sh (with your options)."

INSTALL_DIR="${INSTALL_DIR%/}"
DATA_DIR="${DATA_DIR:-$INSTALL_DIR/data}"
case "$DATA_DIR" in /*) ;; *) fail "--data-dir must be an absolute path." ;; esac
APP_DIR="$INSTALL_DIR/app"
VENV_PYTHON="$APP_DIR/.venv/bin/python"

have() { command -v "$1" >/dev/null 2>&1; }
systemd_running() { [ -d /run/systemd/system ]; }
# Run a command as the service user, with its own home (pip and git keep their files there).
as_service() { runuser -u "$SERVICE_USER" -- env HOME="$INSTALL_DIR" "$@"; }

ufw_active() { have ufw && ufw status 2>/dev/null | grep -q '^Status: active'; }
firewalld_active() { have firewall-cmd && firewall-cmd --state >/dev/null 2>&1; }

# ---------------------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------------------

if [ "$UNINSTALL" = 1 ]; then
    step "Removing IngeTrazo Web"
    if [ -f "$UNIT" ]; then
        systemctl disable --now "$UNIT_NAME" >/dev/null 2>&1 || true
        rm -f "$UNIT"
        systemctl daemon-reload 2>/dev/null || true
        note "Removed the service $UNIT_NAME."
    fi
    if [ -f "$CADDYFILE" ] && grep -qF "$MARK" "$CADDYFILE"; then
        printf '%s\n# The IngeTrazo Web site was removed by install-linux.sh --uninstall.\n' "$MARK" > "$CADDYFILE"
        systemctl reload caddy >/dev/null 2>&1 || true
        note "Removed the site from $CADDYFILE (Caddy itself stays installed)."
    fi
    if ufw_active; then ufw delete allow "$PORT/tcp" >/dev/null 2>&1 || true; fi
    if [ -d "$APP_DIR" ]; then rm -rf "$APP_DIR"; note "Removed $APP_DIR"; fi
    if [ "$REMOVE_DATA" = 1 ]; then
        [ -d "$DATA_DIR" ] && rm -rf "$DATA_DIR" && note "Removed $DATA_DIR and every document in it."
        if id "$SERVICE_USER" >/dev/null 2>&1; then
            userdel "$SERVICE_USER" 2>/dev/null || true
            note "Removed the user $SERVICE_USER."
        fi
        rmdir "$INSTALL_DIR" 2>/dev/null || true
    elif [ -d "$DATA_DIR" ]; then
        note "Kept your documents in $DATA_DIR and the user $SERVICE_USER (use --remove-data to delete them)."
    fi
    step "Done."
    exit 0
fi

# ---------------------------------------------------------------------------------------
# Install or update
# ---------------------------------------------------------------------------------------

echo
printf '\033[1mIngeTrazo Web installer\033[0m\n'
note "Program:   $APP_DIR"
note "Documents: $DATA_DIR"
echo

step "Installing the system packages"
if have apt-get; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq python3 python3-venv python3-pip git curl ca-certificates \
        libgl1 libegl1 libxkbcommon0 libfontconfig1 libglib2.0-0 libdbus-1-3 >/dev/null
    PKG=apt
elif have dnf; then
    extra=""
    have curl || extra=curl            # Fedora images carry curl-minimal, which conflicts with curl
    dnf install -y -q python3 python3-pip git ca-certificates shadow-utils util-linux $extra \
        mesa-libGL mesa-libEGL libxkbcommon fontconfig glib2 dbus-libs >/dev/null
    PKG=dnf
else
    fail "This script knows apt (Debian, Ubuntu) and dnf (Fedora, RHEL). On other systems follow the README by hand."
fi

# A Python 3.10 to 3.14, preferring the system's own python3.
python_ok() { "$1" -c 'import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 14) else 1)' 2>/dev/null; }
PYTHON=""
for candidate in python3 python3.13 python3.12 python3.11 python3.10 python3.14; do
    if have "$candidate" && python_ok "$(command -v "$candidate")"; then PYTHON="$(command -v "$candidate")"; break; fi
done
if [ -z "$PYTHON" ] && [ "$PKG" = dnf ]; then
    for version in 3.12 3.11; do                     # RHEL 9 ships 3.9 but offers these
        if dnf install -y -q "python$version" "python$version-pip" >/dev/null 2>&1; then
            PYTHON="$(command -v "python$version")"; break
        fi
    done
fi
[ -n "$PYTHON" ] || fail "IngeTrazo Web needs Python 3.10 to 3.14, and this system's python3 is $(python3 -V 2>&1). Use Ubuntu 22.04+, Debian 12+ or Fedora."
note "Using $PYTHON ($("$PYTHON" -c 'import platform; print(platform.python_version())'))"

step "Creating the service user $SERVICE_USER"
if id "$SERVICE_USER" >/dev/null 2>&1; then
    note "It already exists."
else
    nologin=$(command -v nologin || echo /usr/sbin/nologin)
    useradd --system --create-home --home-dir "$INSTALL_DIR" --shell "$nologin" "$SERVICE_USER"
fi
mkdir -p "$INSTALL_DIR" "$DATA_DIR"
chown "$SERVICE_USER:" "$INSTALL_DIR"
chown -R "$SERVICE_USER:" "$DATA_DIR"
chmod 750 "$DATA_DIR"
cd "$INSTALL_DIR"          # the service user cannot read root's working directory

if [ "$SERVICE" = 1 ] && systemd_running && systemctl is-active --quiet "$UNIT_NAME" 2>/dev/null; then
    systemctl stop "$UNIT_NAME"
    note "Stopped the running service."
fi

if [ -d "$APP_DIR/.git" ]; then
    step "Updating IngeTrazo Web"
    as_service git -C "$APP_DIR" pull --ff-only || fail "Updating the program (git pull) failed."
elif [ -e "$APP_DIR" ]; then
    fail "$APP_DIR exists but is not a Git checkout. Move it away, or choose another --install-dir."
else
    step "Downloading IngeTrazo Web"
    as_service git clone --depth 1 --branch "$BRANCH" "$REPOSITORY" "$APP_DIR" \
        || fail "Downloading the program (git clone) failed."
fi

if [ ! -x "$VENV_PYTHON" ]; then
    step "Creating the Python environment"
    as_service "$PYTHON" -m venv "$APP_DIR/.venv" || fail "Creating the Python environment failed."
fi

step "Installing the Python packages (a few minutes the first time)"
cd "$APP_DIR"
as_service "$VENV_PYTHON" -m pip install --quiet --disable-pip-version-check --upgrade pip \
    || fail "Updating pip failed."
as_service "$VENV_PYTHON" -m pip install --quiet --disable-pip-version-check \
    -r requirements.txt -r web/backend/requirements.txt || fail "Installing the packages failed."
as_service env QT_QPA_PLATFORM=offscreen "$VENV_PYTHON" -c 'import PySide6.QtGui, numpy, fastapi, uvicorn, openskp, manifold3d, ezdxf' \
    || fail "The packages were installed but do not load (a system library may be missing)."

step "Setting up accounts"
TOKEN=""
users=$(as_service env INGETRAZO_WEB_DATA="$DATA_DIR" "$VENV_PYTHON" -m web.backend users list) \
    || fail "Could not read the user accounts."
if [ -n "$users" ]; then
    note "Accounts already exist; keeping them."
else
    created=$(as_service env INGETRAZO_WEB_DATA="$DATA_DIR" "$VENV_PYTHON" -m web.backend users add "$ADMIN_NAME" --admin) \
        || fail "Could not create the account '$ADMIN_NAME'."
    TOKEN=$(printf '%s\n' "$created" | tail -n 1)
fi

if [ "$NETWORK" = 1 ]; then HOST=0.0.0.0; else HOST=127.0.0.1; fi
if [ -n "$DOMAIN" ]; then SECURE=1; else SECURE=0; fi

if [ "$SERVICE" = 0 ]; then
    echo
    printf '\033[32mIngeTrazo Web is installed (no service, as asked).\033[0m\n'
    note "Start it with:"
    note "  cd $APP_DIR && sudo -u $SERVICE_USER env INGETRAZO_WEB_DATA=$DATA_DIR INGETRAZO_WEB_HOST=$HOST INGETRAZO_WEB_PORT=$PORT QT_QPA_PLATFORM=offscreen .venv/bin/python -m web.backend"
    if [ -n "$TOKEN" ]; then
        printf "\n\033[33mAccess token for '%s' (shown only once; keep it safe):\n%s\033[0m\n" "$ADMIN_NAME" "$TOKEN"
    fi
    exit 0
fi

systemd_running || fail "systemd is not running here (a container?). Run the script with --no-service."

step "Adding the systemd service $UNIT_NAME"
cat > "$UNIT" <<EOF
$MARK Running the installer again rewrites it.
[Unit]
Description=IngeTrazo Web
After=network-online.target
Wants=network-online.target

[Service]
User=$SERVICE_USER
WorkingDirectory=$APP_DIR
Environment="INGETRAZO_WEB_DATA=$DATA_DIR"
Environment=INGETRAZO_WEB_HOST=$HOST
Environment=INGETRAZO_WEB_PORT=$PORT
Environment=INGETRAZO_WEB_SECURE_COOKIES=$SECURE
Environment=QT_QPA_PLATFORM=offscreen
ExecStart=$VENV_PYTHON -m web.backend
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload

if have ss && ss -ltnH "( sport = :$PORT )" 2>/dev/null | grep -q .; then
    fail "Another program already uses port $PORT. Run the script again with --port and another number."
fi
systemctl enable --now "$UNIT_NAME" >/dev/null 2>&1 || fail "The service did not start. See: journalctl -u $UNIT_NAME"
ready=0
for _ in $(seq 1 60); do
    if curl -sf "http://127.0.0.1:$PORT/api/v1/health" >/dev/null 2>&1; then ready=1; break; fi
    sleep 1
done
[ "$ready" = 1 ] || fail "The service did not answer within a minute. See: journalctl -u $UNIT_NAME"
note "The service runs now and starts at boot."

if [ -n "$DOMAIN" ]; then
    step "Serving https://$DOMAIN with Caddy"
    if ! have caddy; then
        if [ "$PKG" = apt ]; then
            if ! apt-get install -y -qq caddy >/dev/null 2>&1; then
                note "Adding Caddy's own package repository (as caddyserver.com describes)"
                apt-get install -y -qq gnupg debian-keyring debian-archive-keyring apt-transport-https >/dev/null
                curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
                    | gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
                curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
                    -o /etc/apt/sources.list.d/caddy-stable.list
                apt-get update -qq
                apt-get install -y -qq caddy >/dev/null
            fi
        else
            dnf install -y -q caddy >/dev/null 2>&1 \
                || fail "Could not install Caddy with dnf. Install it as https://caddyserver.com/docs/install describes, then run this script again."
        fi
    fi
    site="$MARK Running the installer again rewrites it.
$DOMAIN {
	reverse_proxy 127.0.0.1:$PORT
	request_body {
		max_size 110MB
	}
}"
    # Replace the Caddyfile only if it is ours, missing, or the package's sample.
    if [ ! -s "$CADDYFILE" ] || grep -qF "$MARK" "$CADDYFILE" \
        || { grep -q '^:80' "$CADDYFILE" && grep -q 'root \* /usr/share/caddy' "$CADDYFILE"; }; then
        mkdir -p "$(dirname "$CADDYFILE")"
        printf '%s\n' "$site" > "$CADDYFILE"
        caddy validate --config "$CADDYFILE" --adapter caddyfile >/dev/null 2>&1 \
            || fail "Caddy does not accept $CADDYFILE."
        systemctl enable caddy >/dev/null 2>&1 || true
        systemctl reload-or-restart caddy || fail "Caddy did not start. See: journalctl -u caddy"
        note "Caddy gets the certificate by itself once $DOMAIN points to this server."
    else
        note "$CADDYFILE has sites of its own, so it was not changed. Add this block and reload Caddy:"
        printf '%s\n' "$site" | sed 's/^/        /'
    fi
    if ufw_active; then
        ufw allow 80/tcp >/dev/null && ufw allow 443/tcp >/dev/null && note "Opened ports 80 and 443 in ufw."
    elif firewalld_active; then
        firewall-cmd -q --permanent --add-service=http --add-service=https && firewall-cmd -q --reload \
            && note "Opened http and https in firewalld."
    fi
elif [ "$NETWORK" = 1 ]; then
    if ufw_active; then
        ufw allow "$PORT/tcp" >/dev/null && note "Opened port $PORT in ufw."
    elif firewalld_active; then
        firewall-cmd -q --permanent --add-port="$PORT/tcp" && firewall-cmd -q --reload \
            && note "Opened port $PORT in firewalld."
    fi
fi

echo
if [ -n "$DOMAIN" ]; then
    printf '\033[32mIngeTrazo Web is running at https://%s/\033[0m\n' "$DOMAIN"
elif [ "$NETWORK" = 1 ]; then
    address=$(hostname -I 2>/dev/null | awk '{print $1}')
    printf '\033[32mIngeTrazo Web is running at http://%s:%s/\033[0m\n' "${address:-this-server}" "$PORT"
    note "Plain HTTP: access tokens travel unencrypted. Use --domain for HTTPS."
else
    printf '\033[32mIngeTrazo Web is running at http://127.0.0.1:%s/ (this server only)\033[0m\n' "$PORT"
    note "From your computer: ssh -L $PORT:127.0.0.1:$PORT this-server, then open http://127.0.0.1:$PORT/"
    note "Or run the script again with --domain your.domain for HTTPS."
fi
note "Status: systemctl status $UNIT_NAME    Log: journalctl -u $UNIT_NAME"
note "Accounts: cd $APP_DIR && sudo -u $SERVICE_USER env INGETRAZO_WEB_DATA=$DATA_DIR .venv/bin/python -m web.backend users list"
if [ -n "$TOKEN" ]; then
    printf "\n\033[33mAccess token for '%s' (shown only once; keep it safe):\n%s\033[0m\n" "$ADMIN_NAME" "$TOKEN"
fi
note "Update: run this script again. Remove: run it with --uninstall."
