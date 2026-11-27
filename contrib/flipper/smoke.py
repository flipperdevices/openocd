#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Check a release archive on the platform it was built for, without a probe.

    contrib/flipper/smoke.py ARCHIVE [--version 0.12.0+dev-flipper-v1]

Extracts the archive to a new directory, then checks the version banner and that
the configurations Flipper Zero, BUSY Bar and Flipper One use load and parse.
"""

import argparse
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

# Each line is one OpenOCD command line, before 'shutdown'
CONFIGS = {
    'Flipper Zero, ST-Link with the deprecated transport name': [
        '-f', 'interface/stlink.cfg', '-c', 'transport select hla_swd',
        '-f', 'target/stm32wbx.cfg', '-c', 'stm32wbx.cpu configure -rtos auto'],
    'Flipper Zero, CMSIS-DAP': [
        '-f', 'interface/cmsis-dap.cfg', '-c', 'transport select swd',
        '-f', 'target/stm32wbx.cfg', '-c', 'stm32wbx.cpu configure -rtos auto'],
    'BUSY Bar, CMSIS-DAP': [
        '-f', 'interface/cmsis-dap.cfg', '-c', 'transport select swd',
        '-f', 'target/stm32u5x.cfg', '-c', 'stm32u5x.cpu configure -rtos auto'],
    'BUSY Bar, J-Link': [
        '-f', 'interface/jlink.cfg', '-c', 'transport select swd', '-f', 'target/stm32u5x.cfg'],
    'Flipper One, CMSIS-DAP': [
        '-f', 'interface/cmsis-dap.cfg', '-f', 'target/rp2350.cfg',
        '-c', 'rp2350.cm0 configure -event gdb-detach { resume }'],
    'FTDI': [
        '-f', 'interface/ftdi/ft232h-module-swd.cfg', '-f', 'target/stm32wbx.cfg'],
}


def extract(archive, dest):
    if archive.name.endswith('.zip'):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
    else:
        with tarfile.open(archive) as tar:
            tar.extractall(dest, filter='data')
    exe = next(p for p in (dest / 'openocd').iterdir() if p.name in ('openocd', 'openocd.exe'))
    exe.chmod(0o755)
    return exe


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--version', help='text the version banner must contain')
    args = parser.parse_args()

    failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        exe = extract(args.archive.resolve(), Path(tmp))
        banner = subprocess.run([exe, '--version'], capture_output=True, text=True, timeout=60)
        first = (banner.stdout + banner.stderr).splitlines()[0]
        print(f'version: {first}')
        if banner.returncode != 0 or (args.version and args.version not in first):
            print(f'FAIL: expected a version with {args.version!r}')
            failed += 1
        # From another directory, so the scripts are found next to the binary
        for name, cmdline in CONFIGS.items():
            res = subprocess.run([exe, *cmdline, '-c', 'shutdown'], capture_output=True, text=True,
                                 timeout=60, cwd=tempfile.gettempdir())
            out = res.stdout + res.stderr
            ok = res.returncode == 0 and 'shutdown command invoked' in out
            print(f'{"ok  " if ok else "FAIL"} {name}')
            if not ok:
                print(out)
                failed += 1
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
