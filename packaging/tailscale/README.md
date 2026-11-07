# Private browser hosting with Docker and Tailscale

`install.py` downloads a pinned official web release, verifies its SHA-256, builds a
small static nginx image, and gives it a private Tailscale HTTPS address. It runs
on Windows, Linux and macOS with Python 3.9 or newer. No Rust build is required.

The default app is PdfCraft. The same installer can also host TextureCraft,
CADCraft, PhotoCraft, VectorCraft, FilmCraft and SolidCraft using `--app`.

## Set up another computer or network

1. Install Python 3.9+, Git, Docker with the Compose v2 plugin (Docker Desktop on
   Windows/macOS, configured for Linux containers), and Tailscale's CLI. Start Docker and connect Tailscale to the
   tailnet whose devices should access the app. For a Linux host, the account must
   be able to use Docker and configure Tailscale Serve. On macOS, ensure the
   `tailscale` command is on PATH.
2. Check out the repository version containing this directory, then run from its
   root on **the computer that will host the app**:

   Windows:

   ```powershell
   py -3 packaging/tailscale/install.py
   ```

   Linux or macOS:

   ```sh
   python3 packaging/tailscale/install.py
   ```

3. Open the printed `https://<this-host>.<tailnet>.ts.net:8443/` address on any
   permitted device connected to that tailnet. If HTTPS is not already enabled,
   Tailscale may ask a tailnet administrator to enable it; complete that step and
   rerun the installer.

The host can be on another home, office or mobile network. It needs an Internet
connection and membership in the intended tailnet. There is no router port
forwarding to configure. Existing tailnet access rules still apply. A separate
Tailscale account/tailnet produces an address accessible to that tailnet instead.

The app runs **in the visiting browser**. Open and Save use files on that device;
this does not add shared storage, document sync, server rendering, or GPU sharing.
For PdfCraft on a small phone, try the printed `/mobile.html` link and landscape
mode; the interface is designed for larger screens.

Keep the host awake and Docker and Tailscale running. Configure Docker to start at
login/boot as appropriate for the operating system. Containers use
`restart: unless-stopped`; Tailscale Serve is persistent (`--bg`). Windows/macOS
Docker Desktop normally requires a signed-in user after a restart.

## Options and maintenance

Check prerequisites and port ownership without making changes:

```sh
python3 packaging/tailscale/install.py --check
```

Additional app on the same host (use `py -3` in Windows if preferred):

```sh
python3 packaging/tailscale/install.py --app texturecraft --https-port 9443 --local-port 18766
```

Use `--install-dir /absolute/path` to choose where deployment files live. Defaults
are `%LOCALAPPDATA%/<app>-tailnet` on Windows,
`~/Library/Application Support/<app>-tailnet` on macOS, and
`${XDG_DATA_HOME:-~/.local/share}/<app>-tailnet` on Linux. A different
`--project-name` supports multiple independent instances. Every instance needs its
own local port, HTTPS port and install directory.

Rerun the same command to recover/reinstall the pinned release. The installer
preserves previous extracted releases and `compose.previous.json` for rollback.
It refuses to replace a different Tailscale service or reuse a port with public
Funnel enabled. nginx listens only on host loopback, and no PDF processing or
native app control/MCP endpoint is exposed. No Tailscale auth key is stored.

To stop an instance, substitute its own HTTPS port and the deployment path printed
by the installer:

```sh
tailscale serve --https=8443 off
docker compose -f /absolute/deployment/path/compose.json stop
```

To start it again, rerun the installer, or start its existing Compose service and
restore that instance's exact loopback proxy. Do not run `tailscale serve reset`:
it would remove unrelated services too.

Release versions/checksums and the nginx image digest are deliberately pinned in
`install.py`. To update, review an official release, verify its digest, update
`RELEASES`, and rerun. The application source checkout is not built or altered.
PhotoCraft's compressed `.part-*` files are served byte-for-byte; loaders with
stable names revalidate instead of being cached forever. The pinned PhotoCraft
release may also need its verified root `snippets/` mirrored into
`app/snippets/` for the nested loader to start; `configure_site` does this only
when the nested folder is absent. Generated JS and WebAssembly are unchanged.
This is a hosting workaround for [upstream packaging PR #10248](https://github.com/storytold/photocraft/pull/10248).

## Unraid: dashboard and seven Artcraft apps

`setup-unraid.sh` installs the Artcraft dashboard plus PdfCraft, TextureCraft,
CADcraft, PhotoCraft, VectorCraft, FilmCraft and SolidCraft. A pinned Python
container prepares the files, so Python and Git are not required on Unraid.
The dashboard offers app links, running/stopped status, CPU/memory readings,
activity history, and Start/Stop controls for each editor.

### Install on the host

1. Enable Docker on Unraid. Install Docker Compose v2 if `docker compose version`
   is unavailable (for example through [Compose Manager Plus](https://github.com/mstrhakr/compose_plugin#installation)).
   Connect the **host** Tailscale plugin to the same tailnet as the Windows VMs.
   MagicDNS and HTTPS must be enabled. Tailnet access rules must allow all eight
   HTTPS ports below.
2. Extract the provided `artcraft-unraid-installer.zip` and copy the entire
   `artcraft-unraid-installer` folder to the Unraid host, for example under
   `/mnt/user/appdata/`. Keep `install.py`, `unraid.py`, `setup-unraid.sh`, and
   `artcraft-dashboard-source.zip` together. The dashboard bundle is a local
   private artifact, separate from this public repository.
3. Run in the Unraid host terminal, rather than in a VM or another container:

   ```sh
   bash /mnt/user/appdata/artcraft-unraid-installer/setup-unraid.sh
   ```

4. After installation completes, open the printed dashboard URL in Edge or Chrome
   on each Windows VM. Bookmark `https://<unraid-host>.<tailnet>.ts.net:7443/`.
   Use Open to launch an editor, and Start/Stop to manage its service. No Docker
   or Craft installation is needed inside either Windows VM.

The default deployment directory is `/mnt/user/appdata/craft-web`; pass another
absolute path as the script's first argument if needed. Dashboard settings use
this host's actual Tailscale name and generated container names. The two VMs can
work concurrently in independent browser sessions. Editor work, preferences and
files stay in each visiting browser/VM. Existing SMB shares may be used through
browser Open/Save dialogs; the installer does not create shares or shared editing.
The server hosts browser apps; it does not supply GPU rendering to the VMs.

The dashboard controls are shared by tailnet users who can access it. Stopping an
app affects everyone opening that app's URL on this host. The dashboard itself
stays running so apps can be started again.

| Service | Pinned release | Private HTTPS port | Host loopback port |
| --- | --- | --- | --- |
| Artcraft dashboard | 1.0.0 | 7443 | 18760 |
| PdfCraft | 0.18.2 | 8443 | 18765 |
| TextureCraft | 0.3.2 | 9443 | 18766 |
| CADcraft | 0.18.0 | 10443 | 18767 |
| PhotoCraft | 0.21.0 | 11443 | 18768 |
| VectorCraft | 0.21.1 | 12443 | 18769 |
| FilmCraft | 0.18.0 | 13443 | 18771 |
| SolidCraft | 0.30.1 | 14443 | 18770 |

VectorCraft keeps its original Unraid ports. FilmCraft uses 18771 here to avoid
that existing local port. Tailscale Serve is persistent and private; no Funnel,
router port forwarding, or container LAN IP is needed. All published container
ports bind to host loopback.

### Validation, security and upgrades

Before changing any app, the installer verifies the local dashboard ZIP's pinned
SHA-256, checks all eight Tailscale endpoints for conflicting services or public
Funnel, and checks Docker port occupants. It never calls `tailscale serve reset`.
An endpoint is rechecked immediately before configuring its proxy. App downloads
come from SHA-256 pinned official release ZIPs (`storytold` repositories, except
`tangency-labs/solidcraft`). Extracted releases and previous Compose files are
kept for rollback. No app source is built or modified.

The dashboard's web container has no Docker socket. A separate gateway has socket
access only on an internal Docker network with no published port; it permits
inspect, resource readings, start and stop for the seven exact generated app
container names. It rejects exec/create/delete, unrelated containers and arbitrary
Docker commands. The actual socket group is detected at installation; neither
container runs as root. Web controls also validate Host, Origin and a request token.
The shared dashboard requires no additional password: access follows Tailscale's
HTTPS endpoint rules.

The dashboard's named volume preserves its activity history. `unless-stopped`
restarts running services when Docker starts after reboot and leaves deliberately
stopped apps stopped. Keep the host Tailscale plugin connected. Rerunning the
installer rebuilds the pinned releases, keeps history and backups, and starts
**all seven** apps again. The Unraid host runs independently of the original host
once the installer files have been copied.

After changing installer versions, copy the matching complete kit: a dashboard
checksum mismatch stops before app changes. To build a fresh local kit from the
separate dashboard source repository:

```sh
python3 ../artcraft-dashboard/tools/package-source.py
python3 packaging/tailscale/make-unraid-kit.py \
  --dashboard-source ../artcraft-dashboard/dist/artcraft-dashboard-source.zip \
  --output ../artcraft-dashboard/dist/artcraft-unraid-installer.zip
```

Review and update `BUNDLE_SHA256` in `unraid.py` only after checking any source
bundle changes. The builder validates this checksum too. Generated kits and source
ZIPs are ignored by Git; nothing is uploaded or served as a source download.

### Troubleshooting and service management

The generated link list and dashboard Compose files are persistent:

```sh
cat /mnt/user/appdata/craft-web/app-urls.txt
docker compose -f /mnt/user/appdata/craft-web/dashboard/compose.yaml ps
docker compose -f /mnt/user/appdata/craft-web/dashboard/compose.yaml logs --tail 50
tailscale serve status
```

For one editor (substitute its name for `pdfcraft`):

```sh
docker compose -f /mnt/user/appdata/craft-web/pdfcraft/compose.json logs --tail 50
docker compose -f /mnt/user/appdata/craft-web/pdfcraft/compose.json stop
docker compose -f /mnt/user/appdata/craft-web/pdfcraft/compose.json up -d --wait
```

Stopping an app leaves its Tailscale URL configured; starting it restores access.
To remove an endpoint, use only its own port, e.g. `tailscale serve --https=8443 off`.
Do not restore `tailscale-serve-before.json` wholesale if unrelated services have
changed since installation. If a new deployment fails, rerun the same kit after
resolving the reported issue. Existing `compose.previous.json` files (and
`dashboard/compose.previous.yaml`) allow manual rollback without deleting volumes.
The installer has focused Windows and Linux preparation tests and a Linux
Docker dashboard build; a live Unraid host deployment has not been exercised here.
