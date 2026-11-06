# Private browser hosting with Docker and Tailscale

`install.py` downloads a pinned official web release, verifies its SHA-256, builds a
small static nginx image, and gives it a private Tailscale HTTPS address. It runs
on Windows, Linux and macOS with Python 3.9 or newer. No Rust build is required.

The default app is PdfCraft. The same installer can also host TextureCraft,
CADCraft, PhotoCraft and VectorCraft using `--app`.

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
stable names revalidate instead of being cached forever.

## Unraid: CADCraft, PhotoCraft and VectorCraft

`setup-unraid.sh` prepares all three apps using a pinned Python container, so
Python does not need to be installed on Unraid. It requires Docker, Compose v2
(for example through Compose Manager), and a connected **host** Tailscale plugin
with MagicDNS and HTTPS available. Run it in the Unraid host's terminal, not inside
its VM or another container:

```sh
bash /path/to/pdfcraft/packaging/tailscale/setup-unraid.sh
```

Default persistent files: `/mnt/user/appdata/craft-web`. An optional first argument
selects another absolute directory. The script uses ordinary Docker bridge
networks and host loopback ports, avoiding a separate LAN IP for each container.

| App | Private HTTPS port | Host loopback port |
| --- | --- | --- |
| CADCraft | 10443 | 18767 |
| PhotoCraft | 11443 | 18768 |
| VectorCraft | 12443 | 18769 |

Connect the VM to the same tailnet and open the printed URLs in its browser.
The Unraid host serves the application files; the VM's browser performs the work.
The web server needs no GPU passthrough. The **browser** needs the graphics features
required by the app, so the VM's browser/GPU configuration still matters. Web
builds have browser file-access and feature limitations compared with native apps.

If the goal is to use the server's GPU for native applications, running the native
releases inside a VM with GPU passthrough is a separate deployment. A GUI-streaming
container also needs a desktop/display stack and GPU support; a static web
container does not provide those.

Unraid deployment has not been tested against a live Unraid server. The preparation
code and shell syntax were checked in Linux; the installer and TextureCraft
hosting were exercised on Windows with Linux Docker containers. Verify the
containers and Tailscale proxy again after an Unraid reboot. No Unraid settings,
VM settings or GPU assignments are changed by these scripts.

## Validation

```sh
python3 -m unittest discover -s packaging/tailscale -p test_install.py -v
```

The tests cover endpoint ownership, extra paths, TCP listeners, public Funnel,
checksum mismatch, traversal, symlinks and extraction limits. The generated nginx
configuration is checked with `nginx -t` before a service is started.

See the apps' official `packaging/web/README.md` files for browser requirements,
and [Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve) for
private sharing and access-policy details.
