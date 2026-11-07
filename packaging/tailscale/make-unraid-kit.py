#!/usr/bin/env python3
"""Build a local, self-contained Unraid installer kit; nothing is uploaded."""
import argparse
import hashlib
from pathlib import Path
import zipfile
from unraid import read_bundle

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--dashboard-source", type=Path, required=True)
parser.add_argument("--output", type=Path, default=Path(__file__).parent / "dist/artcraft-unraid-installer.zip")
args = parser.parse_args()
read_bundle(args.dashboard_source)
root = Path(__file__).resolve().parent
args.output.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(args.output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as kit:
    for name in ("install.py", "unraid.py", "setup-unraid.sh", "README.md"):
        kit.write(root / name, "artcraft-unraid-installer/" + name)
    kit.write(args.dashboard_source, "artcraft-unraid-installer/artcraft-dashboard-source.zip")
    kit.writestr("artcraft-unraid-installer/INSTALL.txt", """Artcraft on Unraid

1. Enable Docker and Docker Compose v2 on the Unraid host. Connect its host
   Tailscale plugin to the same tailnet as the Windows VMs.
   MagicDNS and Tailscale HTTPS must be enabled.
2. Copy this entire extracted folder to the Unraid host, for example:
   /mnt/user/appdata/artcraft-unraid-installer
   Keep the four installer/source files together. Do not run it inside a VM.
3. In Unraid Terminal, run:
   bash /mnt/user/appdata/artcraft-unraid-installer/setup-unraid.sh
4. Once installation completes, open in Edge or Chrome on either Windows VM:
   https://<unraid-host>.<tailnet>.ts.net:7443/ (use the printed URL)
   Use Open to launch an editor and Start/Stop to manage its hosting container.

Default deployment files: /mnt/user/appdata/craft-web
All eight HTTPS ports must be permitted by your tailnet access rules:
7443, 8443, 9443, 10443, 11443, 12443, 13443, 14443.

The host runs independently of DarthMechinus after installation. Both VMs can
use it at the same time; editing and files stay in each visiting browser/VM.
Keep Docker and the host Tailscale plugin enabled after reboot. Stopped apps
stay stopped until started. Re-running this installer starts all seven apps.
The dashboard is shared: stopping an app affects anyone using that host URL.

See README.md for versions, ports, upgrades, troubleshooting and rollback.
""")
digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
args.output.with_suffix(".zip.sha256").write_text(f"{digest}  {args.output.name}\n", encoding="utf-8")
print(f"Created {args.output}\nSHA-256 {digest}")
