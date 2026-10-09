"""Build hash-verified changed-file packages from two tested portable folders."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def build(current, output, version, baseline=None, base_version=None):
    current, output = Path(current), Path(output)
    new = hashes(current)
    old = hashes(Path(baseline)) if baseline else {}
    changed = {name: {'sha256': digest, 'old': old.get(name)} for name, digest in new.items()
               if old.get(name) != digest}
    manifest = dict(schema=1, base=base_version, version=version, files=changed,
                    removed={name: digest for name, digest in old.items() if name not in new})
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr('update.json', json.dumps(manifest))
        for name in changed:
            archive.write(current / name, 'files/' + name)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + '.sha256').write_text(f'{digest} *{output.name}\n')
    print(f'{output.name}: {len(changed)} changed files, {output.stat().st_size:,} bytes')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('current'); parser.add_argument('output'); parser.add_argument('version')
    parser.add_argument('--baseline'); parser.add_argument('--base-version')
    args = parser.parse_args()
    build(args.current, args.output, args.version, args.baseline, args.base_version)
