#!/usr/bin/env python3
"""Generate a private Unraid dashboard from the locally supplied source bundle."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import uuid
import zipfile
from install import RELEASES

BUNDLE_SHA256 = "614fd94c31bd6d3f141f9c427671cb211762c61d4ee47565596735f65b84120b"
# Preserve the original four Unraid endpoints, especially VectorCraft on 18769.
SPECS = (("pdfcraft", 8443, 18765), ("texturecraft", 9443, 18766),
         ("cadcraft", 10443, 18767), ("photocraft", 11443, 18768),
         ("vectorcraft", 12443, 18769), ("filmcraft", 13443, 18771),
         ("solidcraft", 14443, 18770))
DASHBOARD = ("dashboard", 7443, 18760)
REQUIRED = {"Dockerfile", "compose.yaml", "package.json", "server.mjs", "gateway.mjs",
            "services.json", "lib/docker.mjs", "public/index.html", "public/app.js", "public/icons.js"}


def read_bundle(archive, expected_hash=BUNDLE_SHA256):
    if archive.stat().st_size > 8 * 1024 * 1024:
        raise RuntimeError("Dashboard source bundle is too large.")
    content = archive.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_hash:
        raise RuntimeError("Dashboard bundle SHA-256 mismatch. Copy the matching installer kit again.")
    files = {}
    with zipfile.ZipFile(io.BytesIO(content)) as bundle:
        members = bundle.infolist()
        if len(members) > 1000 or sum(m.file_size for m in members) > 16 * 1024 * 1024:
            raise RuntimeError("Dashboard archive exceeds extraction limits.")
        for member in members:
            name = member.orig_filename
            parts = PurePosixPath(name).parts
            if ("\\" in name or not parts or parts[0] != "artcraft-dashboard" or
                    any(p in ("..", ".") or ":" in p for p in name.split("/")) or
                    stat.S_ISLNK(member.external_attr >> 16)):
                raise RuntimeError("Unsafe dashboard archive member.")
            if member.is_dir():
                continue
            relative = PurePosixPath(*parts[1:]).as_posix()
            if relative in files or relative.startswith(("/", ".git/", "data/")) or relative == ".env":
                raise RuntimeError("Unexpected dashboard archive member.")
            files[relative] = bundle.read(member)
    if not REQUIRED.issubset(files):
        raise RuntimeError("Dashboard source bundle is incomplete.")
    if json.loads(files["package.json"]).get("name") != "artcraft-studio":
        raise RuntimeError("Dashboard source identity mismatch.")
    return files


def settings_for(template, dns, host):
    dns = dns.rstrip(".").lower()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.ts\.net", dns):
        raise RuntimeError("Expected the Unraid host's Tailscale DNS name.")
    if not host or len(host) > 100 or any(ord(c) < 32 for c in host):
        raise RuntimeError("Invalid host name.")
    apps = {app["id"]: dict(app) for app in template["apps"]}
    apps["vectorcraft"] = {"id": "vectorcraft", "name": "VectorCraft", "description": "A little curve can lead to something wonderful.",
                           "category": "image", "label": "Vector drawing", "icon": "vector", "color": "#818eb8"}
    ports = {app: https for app, https, _ in SPECS}
    ordered = ["photocraft", "filmcraft", "solidcraft", "cadcraft", "pdfcraft", "texturecraft", "vectorcraft"]
    registry = []
    for app in ordered:
        entry = apps[app]
        entry.update(container=f"{app}-tailnet-web-1", port=ports[app], version=RELEASES[app][0])
        registry.append(entry)
    return {"hostName": host, "publicUrl": f"https://{dns}:7443", "allowedHosts": [f"{dns}:7443",
            "127.0.0.1:18760", "localhost:18760", "127.0.0.1:8080", "localhost:8080"], "apps": registry}


def prepare_dashboard(root, files, dns, host, socket_gid):
    if not re.fullmatch(r"[0-9]{1,10}", str(socket_gid)):
        raise RuntimeError("Docker socket group must be numeric.")
    settings = settings_for(json.loads(files["services.json"]), dns, host)
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / "deployment.json"
    compose = root / "compose.yaml"
    if compose.is_symlink() or marker.is_symlink() or (root / ".env").is_symlink():
        raise RuntimeError("Dashboard metadata must not be symlinks.")
    if compose.exists() and not marker.exists():
        raise RuntimeError("Dashboard directory contains an unmanaged Compose file.")
    if marker.exists() and json.loads(marker.read_text())["app"] != "artcraft-dashboard":
        raise RuntimeError("Dashboard directory belongs to another application.")
    releases = root / "releases"
    if releases.is_symlink():
        raise RuntimeError("Dashboard release directory must not be a symlink.")
    context = releases / f"{BUNDLE_SHA256[:12]}-{uuid.uuid4().hex[:8]}"
    context.mkdir(parents=True)
    for relative, content in files.items():
        target = context / relative
        if not target.resolve().is_relative_to(context.resolve()):
            raise RuntimeError("Dashboard path escapes the deployment directory.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (context / "services.json").write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    text = files["compose.yaml"].decode().replace("    build: .", f"    build: ./{context.relative_to(root).as_posix()}")
    text = text.replace("artcraft-dashboard-local:1.0.0", f"artcraft-dashboard-local:unraid-{BUNDLE_SHA256[:12]}")
    if compose.exists():
        shutil.copyfile(compose, root / "compose.previous.yaml")
    staged = root / "compose.next.yaml"
    if staged.is_symlink():
        raise RuntimeError("Dashboard staged Compose file must not be a symlink.")
    staged.write_text(text, encoding="utf-8")
    os.replace(staged, compose)
    (root / ".env").write_text(f"DOCKER_SOCKET_GID={socket_gid}\n", encoding="utf-8")
    marker.write_text(json.dumps({"app": "artcraft-dashboard", "sha256": BUNDLE_SHA256,
                                  "public_url": settings["publicUrl"], "context": str(context.relative_to(root))}, indent=2) + "\n", encoding="utf-8")
    return compose


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("specs", "endpoints", "verify", "prepare"))
    parser.add_argument("--bundle", type=Path, default=Path(__file__).parent / "artcraft-dashboard-source.zip")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--dns")
    parser.add_argument("--host")
    parser.add_argument("--socket-gid")
    args = parser.parse_args()
    if args.action in ("specs", "endpoints"):
        specs = SPECS + ((DASHBOARD,) if args.action == "endpoints" else ())
        print(" ".join(f"{app}:{https}:{local}" for app, https, local in specs))
        return
    files = read_bundle(args.bundle)
    if args.action == "verify":
        print("Local dashboard source bundle verified.")
        return
    if None in (args.root, args.dns, args.host, args.socket_gid):
        parser.error("prepare requires --root, --dns, --host and --socket-gid")
    print(prepare_dashboard(args.root, files, args.dns, args.host, args.socket_gid))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile) as error:
        print(f"Unraid setup failed: {error}", file=sys.stderr)
        sys.exit(1)
