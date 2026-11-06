#!/usr/bin/env python3
"""Install verified Craft web releases behind private Tailscale HTTPS (Python 3.9+)."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import urllib.request
import uuid
import zipfile

# Official release checksums, recorded from GitHub's release asset digests.
RELEASES = {
    "pdfcraft": ("0.18.2", "3f2c11ae9e33d91762eaeb92a0921734a6e6cbab38c8a6a0d715fe1af73c6867"),
    "texturecraft": ("0.3.2", "df74aef4ed21df1b61478dccd719df82823967497d9bac7a6fd1ba60e785e608"),
    "cadcraft": ("0.17.1", "dbce95f605807a04f48620de1f71112b10145de7022dc5dd37f9a8e1d6c1270c"),
    "photocraft": ("0.20.2", "c4f712fa57ca76a84c4548681fafb734967e078304d93991840f674aa9041c3d"),
    "vectorcraft": ("0.21.1", "0ee84174aed234771294a0fdedf89a4f3467b34d66238d1dcf9c69d763604a80"),
}
NGINX = "nginx@sha256:583b7f2fce1cdb8da5ad5c39ebd3c33b98b87d493190e548bdee1fa8c619c311"
MAX_DOWNLOAD = 256 * 1024 * 1024
MAX_EXPANDED = 768 * 1024 * 1024
NGINX_CONF = r'''pid /tmp/nginx.pid;
error_log /dev/stderr warn;
events { worker_connections 256; }
http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    access_log /dev/stdout;
    sendfile on;
    server_tokens off;
    client_body_temp_path /tmp/client_temp;
    proxy_temp_path /tmp/proxy_temp;
    fastcgi_temp_path /tmp/fastcgi_temp;
    uwsgi_temp_path /tmp/uwsgi_temp;
    scgi_temp_path /tmp/scgi_temp;
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_comp_level 5;
    gzip_types application/wasm application/javascript text/javascript text/css application/json;
    server {
        listen 8080;
        root /usr/share/nginx/html;
        index index.html;
        location / {
            try_files $uri $uri/ =404;
            add_header X-Content-Type-Options nosniff always;
            add_header Cache-Control "no-cache";
        }
        # Only content-hashed names are immutable. PhotoCraft's loader and parts.txt
        # retain their names across releases and must continue to revalidate.
        location ~* "-[a-f0-9]{8,}[^/]*\.(wasm|js|part-[0-9]+)$" {
            try_files $uri =404;
            add_header X-Content-Type-Options nosniff always;
            add_header Cache-Control "public, max-age=31536000, immutable";
        }
        location = /favicon.ico { access_log off; return 204; }
        location ~ /\. { deny all; }
    }
}
'''


def run(args, timeout=300):
    result = subprocess.run([str(a) for a in args], text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"Command failed: {args[0]} {' '.join(str(a) for a in args[1:3])}\n"
                           f"{result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def executable(name):
    found = shutil.which(name)
    if not found and name == "tailscale" and os.name == "nt":
        candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Tailscale/tailscale.exe"
        if candidate.is_file():
            found = str(candidate)
    if not found:
        raise RuntimeError(f"Install {name} and put its CLI on PATH before running this installer.")
    return found


def validate_endpoint(config, dns_name, https_port, proxy):
    """Refuse to replace another app, a raw TCP listener, or any public Funnel."""
    port = str(https_port)
    tcp = config.get("TCP", {}).get(port)
    web = config.get("Web", {}).get(f"{dns_name}:{port}")
    if config.get("AllowFunnel", {}).get(f"{dns_name}:{port}"):
        raise RuntimeError("This HTTPS port has public Funnel enabled. Choose a different --https-port.")
    if tcp or web:
        expected = {"/": {"Proxy": proxy}}
        if not tcp or not tcp.get("HTTPS") or not web or web.get("Handlers") != expected:
            raise RuntimeError("This Tailscale port belongs to another service. Choose a different --https-port.")


def download(url, destination, expected_hash):
    digest = hashlib.sha256()
    request = urllib.request.Request(url, headers={"User-Agent": "Craft-private-web-installer/1"})
    count = 0
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            count += len(chunk)
            if count > MAX_DOWNLOAD:
                raise RuntimeError("Release download exceeds the size limit.")
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != expected_hash:
        raise RuntimeError("Release SHA-256 mismatch. Nothing has been started or exposed.")


def extract_release(archive, destination, prefix):
    """Validate every ZIP member before writing anything outside the fresh site folder."""
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if len(members) > 20000 or sum(m.file_size for m in members) > MAX_EXPANDED:
            raise RuntimeError("Release archive exceeds extraction limits.")
        validated = []
        for member in members:
            name = member.filename
            parts = PurePosixPath(name).parts
            if ("\\" in name or not parts or parts[0] != prefix or
                    any(part in ("..", ".") or ":" in part for part in parts) or
                    stat.S_ISLNK(member.external_attr >> 16)):
                raise RuntimeError(f"Unsafe release archive member: {name!r}")
            relative = parts[1:]
            if not relative or member.is_dir():
                continue
            target = destination.joinpath(*relative)
            if not target.resolve().is_relative_to(destination.resolve()):
                raise RuntimeError("Archive member escapes the release directory.")
            validated.append((member, target))
        for member, target in validated:
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
    if not (destination / "index.html").is_file() or not list(destination.rglob("*.wasm")):
        raise RuntimeError("Release does not contain a browser app (index.html and WebAssembly).")


def default_root(app):
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    return base / f"{app}-tailnet"


def prepare(root, app, project, local_port):
    version, checksum = RELEASES[app]
    root.mkdir(parents=True, exist_ok=True)
    marker = root / "deployment.json"
    if (root / "compose.json").exists() and not marker.exists():
        raise RuntimeError("The install directory contains an unmanaged compose.json. Choose a new --install-dir.")
    if marker.exists():
        previous = json.loads(marker.read_text(encoding="utf-8"))
        if previous.get("app") != app or previous.get("project") != project:
            raise RuntimeError("The install directory belongs to another app or project.")
    # Keep each extracted release for rollback. No recursive delete or move is needed.
    context = root / "releases" / f"{version}-{uuid.uuid4().hex[:8]}"
    site = context / "site"
    site.mkdir(parents=True)
    archive = context / "release.zip"
    url = f"https://github.com/storytold/{app}/releases/download/v{version}/{app}-web-{version}.zip"
    print(f"Downloading {app} v{version} from its official release...", flush=True)
    download(url, archive, checksum)
    extract_release(archive, site, f"{app}-web-{version}")
    if app == "pdfcraft":
        html = (site / "index.html").read_text(encoding="utf-8")
        viewport = "width=device-width, initial-scale=1"
        if viewport in html:
            (site / "mobile.html").write_text(html.replace(viewport, "width=1280"), encoding="utf-8")
    (context / "nginx.conf").write_text(NGINX_CONF, encoding="utf-8")
    (context / "Dockerfile").write_text(
        f"FROM {NGINX}\nCOPY nginx.conf /etc/nginx/nginx.conf\nCOPY site/ /usr/share/nginx/html/\n", encoding="utf-8")
    (context / ".dockerignore").write_text("*\n!Dockerfile\n!nginx.conf\n!site/\n!site/**\n", encoding="utf-8")
    compose = {"name": project, "services": {"web": {
        "image": f"{project}-local:{version}", "build": {"context": context.relative_to(root).as_posix()},
        "user": "101:101", "entrypoint": ["nginx"], "command": ["-g", "daemon off;"],
        "restart": "unless-stopped", "ports": [f"127.0.0.1:{local_port}:8080"],
        "read_only": True, "tmpfs": ["/tmp:rw,noexec,nosuid,size=32m,uid=101,gid=101"],
        "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
        "pids_limit": 64, "mem_limit": "128m",
        "healthcheck": {"test": ["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/"],
                        "interval": "5s", "timeout": "5s", "retries": 12},
        "logging": {"driver": "json-file", "options": {"max-size": "5m", "max-file": "2"}},
    }}}
    text = json.dumps(compose, indent=2) + "\n"
    staged = root / "compose.next.json"
    staged.write_text(text, encoding="utf-8")
    current = root / "compose.json"
    if current.exists():
        shutil.copyfile(current, root / "compose.previous.json")
    os.replace(staged, current)
    marker.write_text(json.dumps({"app": app, "version": version, "sha256": checksum,
                                 "project": project, "local_port": local_port, "release_url": url}, indent=2) + "\n",
                      encoding="utf-8")
    return current


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", choices=sorted(RELEASES), default="pdfcraft")
    parser.add_argument("--install-dir", type=Path)
    parser.add_argument("--local-port", type=int, default=18765)
    parser.add_argument("--https-port", type=int, default=8443)
    parser.add_argument("--project-name", help="Unique Docker Compose project name")
    parser.add_argument("--prepare-only", action="store_true", help="Download and generate files without Docker or Tailscale (for Unraid)")
    parser.add_argument("--check", action="store_true", help="Check prerequisites and port ownership without changing anything")
    args = parser.parse_args(argv)
    if not all(1024 <= p <= 65535 for p in (args.local_port, args.https_port)):
        parser.error("Both ports must be between 1024 and 65535.")
    if args.prepare_only and args.check:
        parser.error("--prepare-only and --check cannot be combined.")
    project = args.project_name or f"{args.app}-tailnet"
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", project):
        parser.error("Project names use lowercase letters, digits, underscores and hyphens.")
    root = (args.install_dir or default_root(args.app)).expanduser().resolve()
    proxy = f"http://127.0.0.1:{args.local_port}"
    if args.prepare_only:
        compose = prepare(root, args.app, project, args.local_port)
        print(f"Prepared {compose}. Run Docker Compose and Tailscale Serve on the host.")
        return
    docker, tailscale = executable("docker"), executable("tailscale")
    engine_os = run([docker, "version", "--format", "{{.Server.Os}}"])
    if engine_os != "linux":
        raise RuntimeError("Switch Docker to Linux containers before running this installer.")
    run([docker, "compose", "version"])
    endpoint = os.environ.get("DOCKER_HOST") or run([docker, "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"])
    if endpoint.startswith(("ssh://", "tcp://", "http://", "https://")):
        raise RuntimeError("Use a local Docker context: Tailscale must run on the same host as the web port.")
    status = json.loads(run([tailscale, "status", "--json"]))
    if status.get("BackendState") != "Running":
        raise RuntimeError("Connect Tailscale to the intended tailnet first, then rerun this installer.")
    dns = status.get("Self", {}).get("DNSName", "").rstrip(".")
    if not dns:
        raise RuntimeError("This Tailscale node has no DNS name. Enable MagicDNS and HTTPS in the tailnet.")
    config_text = run([tailscale, "serve", "status", "--json"])
    validate_endpoint(json.loads(config_text), dns, args.https_port, proxy)
    url = f"https://{dns}:{args.https_port}/"
    if args.check:
        print(f"Prerequisites OK. Planned private URL: {url}")
        return
    root.mkdir(parents=True, exist_ok=True)
    backup = root / "tailscale-serve-before.json"
    if not backup.exists():
        backup.write_text(config_text + "\n", encoding="utf-8")
    compose = prepare(root, args.app, project, args.local_port)
    print("Building and validating the static web server...", flush=True)
    run([docker, "compose", "-f", compose, "build"], timeout=600)
    run([docker, "compose", "-f", compose, "run", "--rm", "--no-deps", "web", "-t"])
    print(run([docker, "compose", "-f", compose, "up", "-d", "--wait"], timeout=600))
    # Building can take time; recheck ownership before changing a persistent endpoint.
    validate_endpoint(json.loads(run([tailscale, "serve", "status", "--json"])), dns, args.https_port, proxy)
    print(run([tailscale, "serve", "--bg", "--yes", f"--https={args.https_port}", proxy], timeout=120))
    print(f"\nReady: {url}\nKeep this host, Docker and Tailscale running.")
    if args.app == "pdfcraft":
        print(f"Phone layout: {url}mobile.html")
    print(f"Deployment files: {root}")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, subprocess.TimeoutExpired) as error:
        print(f"Setup failed: {error}", file=sys.stderr)
        sys.exit(1)
