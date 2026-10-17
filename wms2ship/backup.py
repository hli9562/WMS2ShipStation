"""Stopped-application backup/restore. Never overwrites a populated data directory."""

import argparse
import hashlib
import io
import json
import sqlite3
import tarfile
import tempfile
from pathlib import Path

from wms2ship.config import Settings


def create_backup(data_dir: Path, target: Path):
    if target.exists():
        raise ValueError("Choose a new backup filename; existing backups are not overwritten.")
    database = data_dir / "app.sqlite3"
    if not database.is_file():
        raise ValueError("No database to back up.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        copy = Path(temp) / "app.sqlite3"
        with sqlite3.connect(database) as source, sqlite3.connect(copy) as dest:
            source.backup(dest)
        paths = [("app.sqlite3", copy)]
        labels = data_dir / "labels"
        if labels.exists():
            paths += [
                (p.relative_to(data_dir).as_posix(), p) for p in labels.rglob("*") if p.is_file()
            ]
        manifest = {}
        # Exclusive creation avoids overwriting a backup if another process races us.
        with target.open("xb") as output, tarfile.open(fileobj=output, mode="w:gz") as archive:
            for name, path in paths:
                payload = path.read_bytes()
                manifest[name] = hashlib.sha256(payload).hexdigest()
                entry = tarfile.TarInfo(name)
                entry.size = len(payload)
                entry.mode = 0o600
                archive.addfile(entry, io.BytesIO(payload))
            payload = json.dumps(manifest, sort_keys=True).encode()
            entry = tarfile.TarInfo("manifest.json")
            entry.size = len(payload)
            archive.addfile(entry, io.BytesIO(payload))


def restore_backup(data_dir: Path, source: Path):
    if data_dir.exists() and any(data_dir.iterdir()):
        raise ValueError("Restore requires an empty data directory; history is never overwritten.")
    # Validate every member before writing anything; never use extractall.
    with tarfile.open(source, "r:gz") as archive:
        members = archive.getmembers()
        names = [m.name for m in members]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate archive members.")
        files = {}
        for entry in members:
            path = Path(entry.name)
            if (
                not entry.isfile()
                or path.is_absolute()
                or ".." in path.parts
                or not (
                    entry.name in {"manifest.json", "app.sqlite3"}
                    or entry.name.startswith("labels/")
                )
            ):
                raise ValueError("Unsafe backup archive.")
            files[entry.name] = archive.extractfile(entry).read()
        manifest = json.loads(files.pop("manifest.json"))
        if "app.sqlite3" not in files or set(manifest) != set(files):
            raise ValueError("Incomplete backup.")
        for name, payload in files.items():
            if hashlib.sha256(payload).hexdigest() != manifest[name]:
                raise ValueError("Backup checksum mismatch.")
    data_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in files.items():
        target = data_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    (data_dir / "labels").mkdir(exist_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "restore"])
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    operation = create_backup if args.action == "create" else restore_backup
    operation(Settings().data_dir, args.archive)


if __name__ == "__main__":
    main()
