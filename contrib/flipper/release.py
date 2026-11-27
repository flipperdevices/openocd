#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Write SHA256SUMS and release.json for the archives in a directory.

    contrib/flipper/release.py DIR --tag flipper-v1 --commit <sha> --base <mainline sha>

release.json, schema 1: tag, source_commit, base_commit (the mainline commit the
Flipper patches sit on), version, archives {platform: {name, sha256, size}}, and
dependencies {name: {version, url, sha256, license}}.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARCHIVE = re.compile(r'^openocd-flipper-v[0-9]+-(linux-x86_64|linux-aarch64|darwin-arm64|windows-x64|windows-arm64)'
                     r'\.(tar\.gz|zip)$')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('dir', type=Path)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--base', required=True)
    args = parser.parse_args()

    archives, sums = {}, []
    for path in sorted(args.dir.iterdir()):
        if not path.is_file() or path.name in ('SHA256SUMS', 'release.json') or path.suffix == '.sha256':
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        sums.append(f'{digest}  {path.name}')
        match = ARCHIVE.match(path.name)
        if match:
            archives[match.group(1)] = {'name': path.name, 'sha256': digest, 'size': path.stat().st_size}
    if len(archives) != 5:
        raise SystemExit(f'expected 5 platform archives, found {sorted(archives)}')
    deps = json.loads((HERE / 'deps.json').read_text())
    record = {
        'schema': 1,
        'tag': args.tag,
        'version': f'0.12.0+dev-{args.tag}',
        'source_commit': args.commit,
        'base_commit': args.base,
        'archives': archives,
        'dependencies': {name: {k: dep[k] for k in ('version', 'url', 'sha256', 'license') if k in dep}
                         for name, dep in deps.items() if not dep.get('tool')},
    }
    (args.dir / 'SHA256SUMS').write_text('\n'.join(sums) + '\n')
    (args.dir / 'release.json').write_text(json.dumps(record, indent=2) + '\n')
    print('\n'.join(sums))


if __name__ == '__main__':
    main()
