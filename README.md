# IngeTrazo Web

*Pronounced **EEN-heh-TRAH-soh**, from Spanish* inge(niería) *"engineering" +* trazo
*"a drawn stroke": the engineer's stroke.*

![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)
![Engine: IngeTrazo 0.6.3.2](https://img.shields.io/badge/engine-IngeTrazo%200.6.3.2-informational)
![Server: Linux · Windows · macOS](https://img.shields.io/badge/server-Linux%20%7C%20Windows%20%7C%20macOS-informational)

**IngeTrazo Web is a free 3D modeler for architecture and engineering that runs in the web
browser.** It is the browser edition of [IngeTrazo](https://github.com/ingelibre/ingetrazo),
the open-source desktop modeler: the same geometry engine and the same `.igz` documents,
served by your own server and used from any modern browser.

You install it once on a computer or server you control. People then open it in Chrome,
Edge, Firefox or Safari, with nothing to install on their side. Every edit is saved on the
server as a new revision of the document, so nothing is lost and every step can be undone.

## Contents

- [What it does](#what-it-does)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Install on macOS](#install-on-macos)
- [Install on Windows](#install-on-windows)
- [Install on a Linux web server](#install-on-a-linux-web-server)
- [Let other people use it: accounts and HTTPS](#let-other-people-use-it-accounts-and-https)
- [Configuration](#configuration)
- [Updating, backups and uninstalling](#updating-backups-and-uninstalling)
- [Optional extras](#optional-extras)
- [For developers](#for-developers)
- [What is not included](#what-is-not-included)
- [License and credits](#license-and-credits)

## What it does

- **Modeling:** lines, rectangles, circles, arcs and polygons; push/pull, offset, follow me,
  fillet, move, rotate, scale and flip. It also includes:
  - solid tools (union, subtract, intersect, trim, split)
  - Bridge, Join Segments, Explode Curve, and changing a curve's segment count
  - Make Faces and Extrude
- **Organization:** groups and components, layers with lock and visibility, scenes,
  section planes, and a model outline.
- **Architecture:**
  - windows and doors that cut their own opening in a wall, and keep it as they move
  - editable terrain, built from a grid, from survey points or from contour lines
  - BIM classification (IFC4) with quantity takeoff
  - georeferencing, map imagery and true north
- **Drawings:** a sheet composer that lays out drawings with views at an exact scale, title
  blocks, dimensions, text, north arrows and legends, and exports vector PDFs.
- **Materials:** a texture library, plus import of IngeTrazo `.igmat` and SketchUp `.skm`
  material files, and export of a document's materials.
- **Import:** OBJ, STL, COLLADA (.dae), DXF, glTF/GLB and SketchUp (.skp).
- **Export:** GLB, glTF, OBJ, STL, COLLADA, DXF, SVG, IFC4 and BIM quantities (CSV).
- **History:** every edit is an immutable revision; Undo and Redo work across reloads and
  browsers; any revision can be restored.
- **Teams:** optional user accounts, so each person sees only their own documents.
- **Automation:** server-side extensions written in Python, and an MCP server so AI agents
  (Claude Code, Claude Desktop or any MCP client) can model through the same API.
- **Languages:** 21 interface translations from the desktop application.

## How it works

```
 Browser (Three.js client)  <-- HTTP/JSON -->  IngeTrazo Web server (Python)
                                               - FastAPI web service
                                               - IngeTrazo geometry engine
                                               - documents and revisions on disk
```

- **Server:** a Python program (FastAPI and Uvicorn) that runs the IngeTrazo engine. Each
  edit loads the document, applies the operation with the same code the desktop uses, and
  saves the next revision.
- **Client:** a Three.js page served by that same program. It is shipped already built, in
  `web/frontend/dist`, so you do **not** need Node.js to install or run it.
- **Data:** documents are stored as files in a data folder. There is no database to set up.

## Requirements

### Hardware and operating system

| | Minimum | Notes |
|---|---|---|
| Operating system | macOS 13 Ventura or later, Windows 10/11 (64-bit), or Linux (Ubuntu 22.04+ / Debian 12+, x86-64 or ARM64) | macOS 12 is not supported by the Qt version IngeTrazo uses |
| Memory | 2 GB free (4 GB or more for large models) | Imports and exports run in separate worker processes |
| Disk | about 1.5 GB for the program, plus space for documents | Each revision is a full copy of the document |
| Browser (for users) | A current Chrome, Edge, Firefox or Safari with WebGL 2 | Nothing to install on the users' computers |

### Software you install first

| Software | Version | Why |
|---|---|---|
| [Python](https://www.python.org/downloads/) | **3.10 to 3.14** (tested with 3.14) | Runs the server and the geometry engine |
| [Git](https://git-scm.com/downloads) | any recent version | Downloads this repository, and pip uses it to install the SketchUp reader (OpenSKP) |

### Python packages (installed for you by `pip`)

They are listed in [`requirements.txt`](requirements.txt) (the engine) and
[`web/backend/requirements.txt`](web/backend/requirements.txt) (the web service).

| Package | Version | License | Used for |
|---|---|---|---|
| PySide6 | 6.11.2 on macOS; 6.7 to < 6.12 elsewhere | LGPL-3.0 | Qt geometry math, fonts and drawing (runs without a window) |
| numpy | 1.26 or later | BSD | Terrain and fast geometry |
| ezdxf | 1.4.4 or later | MIT | DXF import and export |
| manifold3d | 3.5.3 or later | Apache-2.0 | Solid booleans |
| openskp | pinned commit, from GitHub | MIT | SketchUp (.skp) import |
| fastapi | 0.115 to < 1 | MIT | Web service |
| uvicorn[standard] | 0.34 to < 1 | BSD | Web server |
| python-multipart | 0.0.20 to < 1 | Apache-2.0 | File uploads |
| pytest | 8 or later | MIT | Running the test suite (not needed to run the server) |
| httpx2, httpx | 2.0 / 0.27 or later | BSD | FastAPI's test client, for the tests only |

The browser client bundles [Three.js](https://threejs.org/) 0.180 (MIT).

### Optional

| Software | When you need it |
|---|---|
| A reverse proxy with HTTPS ([Caddy](https://caddyserver.com/) or [nginx](https://nginx.org/)) | To let other people use the server over the network (strongly recommended) |
| [Node.js](https://nodejs.org/) 20.19 or later | Only to change and rebuild the browser client |
| [Rust](https://rustup.rs/) and [maturin](https://www.maturin.rs/) | Only for the optional native engine, which speeds up very large models |
| [ifcopenshell](https://ifcopenshell.org/) | Only for some extra IFC tests; IFC export works without it |

## Install on macOS

These steps run IngeTrazo Web on your Mac. To serve other people from it, continue with
[Let other people use it](#let-other-people-use-it-accounts-and-https).

1. **Install Python and Git.** The simplest way is [Homebrew](https://brew.sh/): open
   **Terminal** and run

   ```bash
   brew install python@3.13 git
   ```

   Or install Python from [python.org](https://www.python.org/downloads/macos/). Git comes
   with the Xcode command line tools: run `xcode-select --install`.

2. **Download IngeTrazo Web:**

   ```bash
   cd ~
   git clone https://github.com/felixriestra/ingetrazo-web-open.git
   cd ingetrazo-web-open
   ```

3. **Create a virtual environment and install the dependencies** (a few minutes; PySide6
   is a large download):

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install --upgrade pip
   pip install -r requirements.txt -r web/backend/requirements.txt
   ```

4. **Start the server:**

   ```bash
   python -m web.backend
   ```

   Open <http://127.0.0.1:8000> in your browser. Choose **File ▸ Open…** or drag an
   `.igz` file in; there are samples in [`examples/`](examples). Stop the server with
   **Control-C**.

5. **Optional: start it automatically at login.** Save this as
   `~/Library/LaunchAgents/com.ingetrazo.web.plist`. Replace `YOURNAME` with your user
   name, and edit the paths if you cloned the repository somewhere else.

   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
   <plist version="1.0">
   <dict>
     <key>Label</key><string>com.ingetrazo.web</string>
     <key>WorkingDirectory</key><string>/Users/YOURNAME/ingetrazo-web-open</string>
     <key>ProgramArguments</key>
     <array>
       <string>/Users/YOURNAME/ingetrazo-web-open/.venv/bin/python</string>
       <string>-m</string><string>web.backend</string>
     </array>
     <key>EnvironmentVariables</key>
     <dict>
       <key>INGETRAZO_WEB_DATA</key><string>/Users/YOURNAME/IngeTrazoWebData</string>
     </dict>
     <key>RunAtLoad</key><true/>
     <key>KeepAlive</key><true/>
     <key>StandardErrorPath</key><string>/Users/YOURNAME/Library/Logs/ingetrazo-web.log</string>
   </dict>
   </plist>
   ```

   Then load it:

   ```bash
   launchctl load ~/Library/LaunchAgents/com.ingetrazo.web.plist
   ```

## Install on Windows

### With the install script

[`install-windows.ps1`](install-windows.ps1) does all the steps below for you. Open
**PowerShell** (no administrator rights needed) and run:

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/felixriestra/ingetrazo-web-open/main/install-windows.ps1)))
```

Or download the file and run `powershell -ExecutionPolicy Bypass -File .\install-windows.ps1`.

It installs Python 3.13 and Git with `winget` if they are missing, puts the program in
`%LOCALAPPDATA%\IngeTrazoWeb` and your documents in `%USERPROFILE%\IngeTrazoWebData`, starts
the server without a console window, and opens <http://127.0.0.1:8000>. It adds two entries to
the Start menu (open IngeTrazo Web, start the server), and starts the server each time you sign in.
The log is `server.log` in the documents folder.

| Option | What it does |
|---|---|
| `-Port 8080` | Use another port |
| `-Network` | Let other computers on the network in: creates an `admin` account and prints its access token once, and opens the port in Windows Firewall (when run as administrator) |
| `-InstallDir`, `-DataDir` | Other folders for the program and the documents |
| `-NoAutostart` | Do not start the server when you sign in |
| `-Uninstall` | Remove the program, shortcuts and firewall rule; your documents stay (add `-RemoveData` to delete them too) |

To pass options with the one-line command, add them at the end, for example
`& ([scriptblock]::Create((irm https://...))) -Network`. **Update** by running the script
again with the same options.

### By hand

1. **Install Python** from [python.org](https://www.python.org/downloads/windows/) (64-bit,
   3.10 to 3.14). In the first screen of the installer, tick **Add python.exe to PATH**.
2. **Install Git** from [git-scm.com](https://git-scm.com/download/win) with the default
   options.
3. **Download IngeTrazo Web.** Open **PowerShell** and run:

   ```powershell
   cd $HOME
   git clone https://github.com/felixriestra/ingetrazo-web-open.git
   cd ingetrazo-web-open
   ```

4. **Create a virtual environment and install the dependencies:**

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt -r web\backend\requirements.txt
   ```

   If PowerShell refuses to run `Activate.ps1`, allow local scripts once with
   `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` and try again. In the classic
   Command Prompt, use `.venv\Scripts\activate.bat` instead.

5. **Start the server:**

   ```powershell
   python -m web.backend
   ```

   Open <http://127.0.0.1:8000> in your browser. Stop the server with **Ctrl+C**.

6. **Optional: run it as a Windows service** so it starts with the computer. The free
   [NSSM](https://nssm.cc/) tool does this. From an **Administrator** PowerShell, after
   placing `nssm.exe` on the PATH:

   ```powershell
   nssm install IngeTrazoWeb "$HOME\ingetrazo-web-open\.venv\Scripts\python.exe" "-m web.backend"
   nssm set IngeTrazoWeb AppDirectory "$HOME\ingetrazo-web-open"
   nssm set IngeTrazoWeb AppEnvironmentExtra INGETRAZO_WEB_DATA=C:\IngeTrazoWebData
   nssm start IngeTrazoWeb
   ```

   You can also use **Task Scheduler**: create a task that runs at startup, with the program
   `...\ingetrazo-web-open\.venv\Scripts\python.exe`, the arguments `-m web.backend` and the start
   folder `...\ingetrazo-web-open`.

   To set a variable for one session in PowerShell, use
   `$env:INGETRAZO_WEB_PORT = "8080"` before `python -m web.backend`.

## Install on a Linux web server

These steps are for Ubuntu or Debian. Other distributions need the same packages under
their own names.

1. **Install the system packages.** PySide6 runs without a display, but it still needs a few
   system libraries:

   ```bash
   sudo apt update
   sudo apt install -y python3 python3-venv python3-pip git \
       libgl1 libegl1 libxkbcommon0 libfontconfig1 libglib2.0-0 libdbus-1-3
   ```

2. **Create a user for the service and download IngeTrazo Web:**

   ```bash
   sudo useradd --system --create-home --home-dir /opt/ingetrazo --shell /usr/sbin/nologin ingetrazo
   sudo -u ingetrazo git clone https://github.com/felixriestra/ingetrazo-web-open.git /opt/ingetrazo/app
   cd /opt/ingetrazo/app
   sudo -u ingetrazo python3 -m venv .venv
   sudo -u ingetrazo .venv/bin/pip install --upgrade pip
   sudo -u ingetrazo .venv/bin/pip install -r requirements.txt -r web/backend/requirements.txt
   ```

3. **Create the first administrator.** This turns user accounts on and prints an access
   token. Save the token: it is shown only once.

   ```bash
   sudo -u ingetrazo env INGETRAZO_WEB_DATA=/opt/ingetrazo/data \
       .venv/bin/python -m web.backend users add admin --admin
   ```

4. **Run it as a systemd service.** Create `/etc/systemd/system/ingetrazo-web.service`:

   ```ini
   [Unit]
   Description=IngeTrazo Web
   After=network.target

   [Service]
   User=ingetrazo
   WorkingDirectory=/opt/ingetrazo/app
   Environment=INGETRAZO_WEB_DATA=/opt/ingetrazo/data
   Environment=INGETRAZO_WEB_HOST=127.0.0.1
   Environment=INGETRAZO_WEB_PORT=8000
   Environment=INGETRAZO_WEB_SECURE_COOKIES=1
   ExecStart=/opt/ingetrazo/app/.venv/bin/python -m web.backend
   Restart=on-failure

   [Install]
   WantedBy=multi-user.target
   ```

   Then start it:

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now ingetrazo-web
   sudo systemctl status ingetrazo-web
   ```

5. **Put HTTPS in front of it** with a reverse proxy. With [Caddy](https://caddyserver.com/),
   which gets a free certificate by itself, `/etc/caddy/Caddyfile` is just:

   ```
   ingetrazo.example.com {
       reverse_proxy 127.0.0.1:8000
       request_body {
           max_size 110MB
       }
   }
   ```

   With nginx, proxy the site to `http://127.0.0.1:8000`, set
   `client_max_body_size 110m;` and `proxy_read_timeout 900s;`, and add a certificate (for
   example with [Certbot](https://certbot.eff.org/)).

Users then open `https://ingetrazo.example.com` and sign in with the token you give them.

## Let other people use it: accounts and HTTPS

By default the server listens only on the computer it runs on (`127.0.0.1`), and nobody has
to sign in. That is right for one person on their own machine.

To let other people use it:

1. **Turn accounts on** by creating users. Each command prints an access token once; give it
   to that person.

   ```bash
   python -m web.backend users add ana --admin   # an administrator
   python -m web.backend users add ben           # a regular user
   python -m web.backend users token ben         # a new token for ben (the old one stops working)
   python -m web.backend users list
   python -m web.backend users remove ben
   ```

   With accounts on, every document belongs to the person who made it. Other users cannot
   see it; administrators see everything. The browser asks for the token once and then
   keeps a session cookie. Scripts send `Authorization: Bearer <token>`.

2. **Serve it over HTTPS** behind a reverse proxy, as in
   [the Linux steps](#install-on-a-linux-web-server), and set
   `INGETRAZO_WEB_SECURE_COOKIES=1`.

3. **Or bind it to the network directly** with `INGETRAZO_WEB_HOST=0.0.0.0`. This is
   possible only when accounts exist; without accounts the server refuses to start on a
   network address. Open the port in the firewall, and still prefer HTTPS: without it,
   tokens travel in plain text.

There are no passwords, e-mail sign-up, password reset or per-user quotas.
`INGETRAZO_WEB_ALLOW_REMOTE=1` serves the network **without** accounts. Use it only when
your own proxy already authenticates every request.

## Configuration

Everything is set with environment variables. None is required.

| Variable | Default | Meaning |
|---|---|---|
| `INGETRAZO_WEB_DATA` | `var/web-data` inside the repository | Folder for documents, revisions, users and extensions. Put it outside the repository on a server |
| `INGETRAZO_WEB_HOST` | `127.0.0.1` | Address to listen on |
| `INGETRAZO_WEB_PORT` | `8000` | Port to listen on |
| `INGETRAZO_WEB_AUTH` | automatic | `1` forces accounts on, `0` forces them off; by default they are on as soon as a user exists |
| `INGETRAZO_WEB_SECURE_COOKIES` | off | `1` marks the session cookie HTTPS-only; set it when serving over HTTPS |
| `INGETRAZO_WEB_ALLOW_REMOTE` | off | `1` allows a network address without accounts (only behind an authenticating proxy) |
| `INGETRAZO_WEB_JOB_WORKERS` | `2` | Imports and exports that may run at the same time |
| `INGETRAZO_WEB_JOB_TIMEOUT` | `900` | Seconds before an import or export is stopped |
| `INGETRAZO_WEB_JOB_MEMORY_MIB` | `4096` | Memory limit of each import or export process (Linux only) |
| `INGETRAZO_WEB_KEEP_REVISIONS` | `0` (keep all) | Keep only the newest N revisions of each document (at least 5; Undo always still works N-1 steps back) |
| `INGETRAZO_WEB_EXTENSIONS` | `extensions` inside the data folder | Folder for server-side Python extensions |
| `INGETRAZO_WEB_EXTENSION_TIMEOUT` | `60` | Seconds before an extension is stopped |
| `INGETRAZO_RUST` | off | `1` uses the optional native engine when it is built (see below) |

Uploads are limited to 100 MiB per file.

## Updating, backups and uninstalling

**Update** to the latest version: stop the server, then from the repository folder (with the
virtual environment active) run

```bash
git pull
pip install -r requirements.txt -r web/backend/requirements.txt
```

and start the server again. Documents are not touched by an update.

**Back up** by copying the data folder (`INGETRAZO_WEB_DATA`). It holds every document,
revision and user. To restore, stop the server and copy the folder back.

**Remove old revisions** to save disk space, keeping the newest 20 of each document:

```bash
python -m web.backend prune --keep 20
```

**Uninstall:** stop the server (and remove the launchd agent, Windows service or systemd
unit if you created one), then delete the repository folder and, if you no longer need the
documents, the data folder.

## Optional extras

### AI agents (MCP)

[`web/mcp/ingetrazo_web_mcp.py`](web/mcp/ingetrazo_web_mcp.py) is a Model Context Protocol
server that lets Claude Code, Claude Desktop or any MCP client model through a running
IngeTrazo Web, with the same validated and undoable commands as the browser. It uses only
the Python standard library and can run on another machine. See
[`web/mcp/README.md`](web/mcp/README.md).

### Server-side extensions

Put Python files in the extensions folder. Each one declares `EXTENSION` (its name,
description and parameters) and `run(scene, params)`. It appears in the **Extensions** menu
with a form for its parameters, and runs as one revision in its own process. See
[`examples/web-extensions/column_grid.py`](examples/web-extensions/column_grid.py) and
[`web/backend/ingetrazo_web/extensions.py`](web/backend/ingetrazo_web/extensions.py).
Extensions run with the server's rights, so only install code you trust.

### The native engine (Rust, for very large models)

A native module from the desktop application speeds up hidden lines, orientation and
push/pull on models with hundreds of thousands of faces. On ordinary models it makes no
visible difference, so it is off. To build it, install Rust from <https://rustup.rs/>, then
with the virtual environment active:

```bash
pip install maturin
cd rust/ingetrazo_core
maturin develop --release
cd ../..
INGETRAZO_RUST=1 python -m web.backend
```

On Windows, set `$env:INGETRAZO_RUST = "1"` before starting the server. Results are the same
with and without it.

## For developers

**Run the tests** (about four minutes):

```bash
pip install -r requirements.txt   # includes pytest and the test client
python -m pytest -q
python -m web.tools.reachability --check
```

**Change the browser client.** Install Node.js 20.19 or later, then:

```bash
cd web/frontend
npm ci
npm run build        # writes web/frontend/dist, which the server serves
```

**Repository layout:**

| Path | What |
|---|---|
| `web/backend` | The web service (FastAPI): documents, revisions, commands, jobs, accounts |
| `web/frontend` | The browser client (TypeScript and Three.js), with the built copy in `dist/` |
| `web/mcp` | The MCP server for AI agents |
| `core/`, `formats/`, `georef/`, `tools/` | The IngeTrazo geometry engine and file formats, pruned to what the service uses |
| `rust/` | The optional native engine |
| `i18n/`, `resources/` | Translations, components, textures and BIM tables |
| `examples/` | Sample `.igz` documents and an example extension |
| `tests/` | The test suite |
| `docs/` | Design notes, the web port plan and its status |

More technical detail is in [`web/README.md`](web/README.md): the API, the error format, the
revision model, sheets and the preferences. Every error response is JSON in the form
`{"detail": {"code", "message", "fields"?}}`.

**Engine updates.** The engine is the desktop application's code, pruned to what the web
service reaches. [`web/KEEP.txt`](web/KEEP.txt) lists the modules it may use, and a test
fails if it reaches anything else. [`UPSTREAM.md`](UPSTREAM.md) records which upstream
version each part comes from, and how to bring in newer upstream fixes.

## What is not included

- **The desktop interface.** The Qt windows, interactive desktop tools and desktop plugins
  are not part of this repository; they live in
  [IngeTrazo](https://github.com/ingelibre/ingetrazo). Web extensions replace the plugins.
- **SketchUp export.** SketchUp files can be **imported**, but `.skp` **export** is not part
  of the open-source release: the writer is not in this repository, and the export option is
  commented out in `web/backend/ingetrazo_web/interchange.py` and in the browser client.

## License and credits

IngeTrazo Web is free software under the **GNU General Public License, version 3 or (at your
option) any later version** (GPL-3.0-or-later), the same license as the original
[IngeTrazo](https://github.com/ingelibre/ingetrazo). See [`LICENSE`](LICENSE). You may use,
study, change and share it. If you distribute a changed version, or offer one to others,
share its source code under the same license.

- **IngeTrazo** was created by **Marco Sumari Tellez** and its contributors (see
  [`AUTHORS`](AUTHORS)).
- **The web edition** is by **Felix Riestra**.
- **Third-party components** keep their own licenses: Three.js (MIT), PySide6/Qt
  (LGPL-3.0), FastAPI (MIT), Uvicorn (BSD-3-Clause), NumPy (BSD-3-Clause), ezdxf (MIT),
  manifold3d (Apache-2.0), OpenSKP (MIT) and python-multipart (Apache-2.0).
- The bundled textures and components list their sources in
  [`resources/textures/SOURCES.md`](resources/textures/SOURCES.md) and
  [`resources/components/SOURCES.md`](resources/components/SOURCES.md).
