#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Build a self-contained OpenOCD release archive for one platform.

The USB libraries, hidapi, libftdi, jimtcl and libjaylink are built from the
sources pinned in deps.json and linked statically, so the archive needs nothing
installed but the OS itself (and libudev on Linux).

    contrib/flipper/build.py --platform linux-x86_64 --out dist [--relstr=-flipper-v1]

Windows archives are cross-built on Linux with llvm-mingw.
"""

import argparse
import gzip
import hashlib
import io
import json
import os
import platform as host
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent.parent
PLATFORMS = {
    'linux-x86_64': {'host': None},
    'linux-aarch64': {'host': None},
    'darwin-arm64': {'host': None},
    'windows-x64': {'host': 'x86_64-w64-mingw32'},
    'windows-arm64': {'host': 'aarch64-w64-mingw32'},
}
# Script file names that break Windows tools and zip consumers
SKIP_SCRIPTS = re.compile(r'[^\x00-\x7f]')


def log(msg):
    print(f'==> {msg}', flush=True)


def run(cmd, cwd=None, env=None):
    print('+', ' '.join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, check=True)


def fetch(name, dep, cache):
    """Download a pinned source archive into the cache and check its sha256."""
    path = cache / dep['url'].rsplit('/', 1)[1]
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == dep['sha256']:
        return path
    for attempt in range(4):
        try:
            with urllib.request.urlopen(dep['url'], timeout=120) as resp:
                data = resp.read()
            break
        except OSError as exc:
            if attempt == 3:
                raise
            log(f'{name}: download failed ({exc}), retrying')
            time.sleep(5 * (attempt + 1))
    digest = hashlib.sha256(data).hexdigest()
    if digest != dep['sha256']:
        sys.exit(f'{name}: sha256 {digest}, expected {dep["sha256"]}')
    path.write_bytes(data)
    return path


def unpack(archive, dest):
    """Extract an archive and return its single top-level directory."""
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as tar:
        tar.extractall(dest, filter='data')
    (top,) = [p for p in dest.iterdir() if p.is_dir()]
    return top


class Build:
    def __init__(self, plat, work, cache):
        self.plat = plat
        self.cross = PLATFORMS[plat]['host']
        self.work = work
        self.cache = cache
        self.prefix = work / 'prefix'
        self.deps = json.loads((HERE / 'deps.json').read_text())
        self.env = dict(os.environ)
        # configure scripts take PKG_CONFIG as a program, not a command line
        wrapper = work / 'bin' / 'pkg-config-static'
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        wrapper.write_text(f'#!/bin/sh\nexec {shutil.which("pkg-config")} --static "$@"\n')
        wrapper.chmod(0o755)
        self.env['PKG_CONFIG'] = str(wrapper)
        pc = [str(self.prefix / 'lib' / 'pkgconfig'), str(self.prefix / 'share' / 'pkgconfig')]
        if plat.startswith('linux'):
            # libudev.pc, for the hidraw backend; everything else is ours
            pc += ['/usr/lib64/pkgconfig', '/usr/lib/pkgconfig', '/usr/share/pkgconfig']
        self.env['PKG_CONFIG_LIBDIR'] = os.pathsep.join(pc)
        self.env.pop('PKG_CONFIG_PATH', None)
        if plat == 'darwin-arm64':
            self.env['MACOSX_DEPLOYMENT_TARGET'] = '11.0'
        if self.cross:
            self.setup_llvm_mingw()

    def setup_llvm_mingw(self):
        root = unpack(fetch('llvm-mingw', self.deps['llvm-mingw'], self.cache), self.work / 'llvm-mingw')
        self.env['PATH'] = f'{root / "bin"}{os.pathsep}{self.env["PATH"]}'
        self.env['CC'] = f'{self.cross}-clang'
        self.env['CXX'] = f'{self.cross}-clang++'
        self.env['AR'] = f'{self.cross}-ar'
        self.env['RANLIB'] = f'{self.cross}-ranlib'
        self.env['STRIP'] = f'{self.cross}-strip'

    def host_args(self):
        return [f'--host={self.cross}'] if self.cross else []

    def cmake_args(self):
        args = ['-DCMAKE_BUILD_TYPE=Release', f'-DCMAKE_INSTALL_PREFIX={self.prefix}',
                '-DCMAKE_INSTALL_LIBDIR=lib', '-DBUILD_SHARED_LIBS=OFF',
                f'-DCMAKE_PREFIX_PATH={self.prefix}', '-DCMAKE_POLICY_VERSION_MINIMUM=3.5',
                f'-DPKG_CONFIG_EXECUTABLE={shutil.which("pkg-config")}']
        if self.cross:
            args += ['-DCMAKE_SYSTEM_NAME=Windows',
                     f'-DCMAKE_SYSTEM_PROCESSOR={self.cross.split("-")[0]}',
                     f'-DCMAKE_C_COMPILER={self.cross}-clang',
                     f'-DCMAKE_CXX_COMPILER={self.cross}-clang++',
                     f'-DCMAKE_RC_COMPILER={self.cross}-windres',
                     '-DCMAKE_FIND_ROOT_PATH_MODE_PROGRAM=NEVER',
                     '-DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY',
                     '-DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY',
                     f'-DCMAKE_FIND_ROOT_PATH={self.prefix}']
        if self.plat == 'darwin-arm64':
            args += ['-DCMAKE_OSX_DEPLOYMENT_TARGET=11.0', '-DCMAKE_OSX_ARCHITECTURES=arm64']
        return args

    def source(self, name):
        return unpack(fetch(name, self.deps[name], self.cache), self.work / 'src' / name)

    def autotools(self, src, *args, autogen=None):
        if autogen:
            run([autogen], cwd=src, env=self.env)
        run(['./configure', f'--prefix={self.prefix}', '--disable-shared', '--enable-static',
             *self.host_args(), *args], cwd=src, env=self.env)
        run(['make', f'-j{os.cpu_count()}'], cwd=src, env=self.env)
        run(['make', 'install'], cwd=src, env=self.env)

    def cmake(self, src, *args):
        build = src / 'build-flipper'
        run(['cmake', '-S', src, '-B', build, *self.cmake_args(), *args], env=self.env)
        run(['cmake', '--build', build, '--parallel', str(os.cpu_count())], env=self.env)
        run(['cmake', '--install', build], env=self.env)

    def libftdi(self, src):
        # Its shared library cannot link against a static libusb: build and
        # install only the static one
        build = src / 'build-flipper'
        run(['cmake', '-S', src, '-B', build, *self.cmake_args(), '-DSTATICLIBS=ON', '-DFTDIPP=OFF',
             '-DPYTHON_BINDINGS=OFF', '-DEXAMPLES=OFF', '-DDOCUMENTATION=OFF', '-DFTDI_EEPROM=OFF',
             '-DLINK_PYTHON_LIBRARY=OFF',
             f'-DLIBUSB_INCLUDE_DIR={self.prefix / "include" / "libusb-1.0"}',
             f'-DLIBUSB_LIBRARIES={self.prefix / "lib" / "libusb-1.0.a"}'], env=self.env)
        run(['cmake', '--build', build, '--parallel', str(os.cpu_count()), '--target', 'ftdi1-static'],
            env=self.env)
        include = self.prefix / 'include' / 'libftdi1'
        include.mkdir(parents=True, exist_ok=True)
        shutil.copy(src / 'src' / 'ftdi.h', include)
        shutil.copy(build / 'src' / 'libftdi1.a', self.prefix / 'lib')
        shutil.copy(build / 'libftdi1.pc', self.prefix / 'lib' / 'pkgconfig')

    def dependencies(self):
        log('libusb')
        self.autotools(self.source('libusb'))
        log('hidapi')
        hidapi = ['-DHIDAPI_BUILD_HIDTEST=OFF']
        if self.plat.startswith('linux'):
            hidapi += ['-DHIDAPI_WITH_LIBUSB=OFF']  # hidraw only
        self.cmake(self.source('hidapi'), *hidapi)
        log('libftdi1')
        self.libftdi(self.source('libftdi1'))
        log('jimtcl')
        jim = self.source('jimtcl')
        run(['./configure', f'--prefix={self.prefix}', *self.host_args(), '--minimal',
             '--disable-ssl', '--disable-docs', '--with-ext=json'], cwd=jim, env=self.env)
        run(['make', f'-j{os.cpu_count()}', 'libjim.a'], cwd=jim, env=self.env)
        run(['make', 'install'], cwd=jim, env=self.env)
        log('libjaylink')
        self.autotools(self.source('libjaylink'), autogen='./autogen.sh')
        # Static linking only: nothing shared may be found by the linker
        for pattern in ('*.so', '*.so.*', '*.dylib', '*.dll.a', '*.la'):
            for path in (self.prefix / 'lib').glob(pattern):
                path.unlink()

    def openocd(self, relstr):
        log('openocd')
        # automake wants the unused submodule directories, even empty
        for sub in ('jimtcl', 'src/jtag/drivers/libjaylink'):
            (SRC / sub).mkdir(parents=True, exist_ok=True)
        run(['./bootstrap'], cwd=SRC, env=self.env)
        build = self.work / 'openocd'
        build.mkdir(parents=True, exist_ok=True)
        # bindir == pkgdatadir puts scripts/ next to the binary
        dirs = ['--prefix=/openocd', '--bindir=/openocd/openocd', '--datarootdir=/openocd',
                '--datadir=/openocd']
        adapters = ['--enable-cmsis-dap', '--enable-cmsis-dap-v2', '--enable-stlink',
                    '--enable-jlink', '--enable-ftdi']
        env = dict(self.env)
        if self.cross:
            env['LDFLAGS'] = '-static'
        if self.plat == 'darwin-arm64':
            # libtool drops the '-Wl,-framework,X' form libusb's pkg-config file
            # uses, and hidapi's lists none
            env['LIBS'] = '-framework IOKit -framework CoreFoundation -framework Security'
        if relstr is not None:
            env['OPENOCD_RELSTR'] = relstr
        run([SRC / 'configure', *self.host_args(), *dirs, *adapters, '--disable-werror',
             '--disable-internal-jimtcl', '--disable-internal-libjaylink', '--without-capstone',
             '--disable-doxygen-html', 'MAKEINFO=true'], cwd=build, env=env)
        run(['make', f'-j{os.cpu_count()}', 'MAKEINFO=true'], cwd=build, env=env)
        stage = self.work / 'stage'
        shutil.rmtree(stage, ignore_errors=True)
        run(['make', 'install-exec', 'install-data', f'DESTDIR={stage}', 'MAKEINFO=true'], cwd=build, env=env)
        return stage / 'openocd' / 'openocd' / 'openocd'

    def gate(self, exe):
        """Fail when the binary needs a library the target OS does not provide."""
        log('checking linkage')
        if self.plat.startswith('linux'):
            out = subprocess.run(['readelf', '-dV', exe], capture_output=True, text=True, check=True).stdout
            needed = sorted(set(re.findall(r'\(NEEDED\).*\[(.+?)\]', out)))
            allowed = re.compile(r'lib(c|m|pthread|dl|rt|util|udev)\.so\.|ld-linux')
            bad = [lib for lib in needed if not allowed.match(lib)]
            glibc = max((tuple(map(int, v.split('.'))) for v in re.findall(r'GLIBC_([0-9.]+)', out)),
                        default=(0,))
            print('NEEDED:', ', '.join(needed), '| max GLIBC', '.'.join(map(str, glibc)))
            if bad or glibc > (2, 34):
                sys.exit(f'linkage: unexpected {bad} or glibc {glibc}')
        elif self.plat == 'darwin-arm64':
            out = subprocess.run(['otool', '-L', exe], capture_output=True, text=True, check=True).stdout
            libs = [line.split()[0] for line in out.splitlines()[1:]]
            print('\n'.join(libs))
            bad = [lib for lib in libs if not lib.startswith(('/usr/lib/', '/System/'))]
            minos = subprocess.run(['otool', '-l', exe], capture_output=True, text=True, check=True).stdout
            if bad or 'minos 11.0' not in minos:
                sys.exit(f'linkage: unexpected {bad} or minimum macOS is not 11.0')
        else:
            out = subprocess.run([f'{self.cross}-objdump', '-p', exe], capture_output=True, text=True,
                                 env=self.env, check=True).stdout
            dlls = sorted(set(re.findall(r'DLL Name: (\S+)', out)))
            print('DLLs:', ', '.join(dlls))
            system = re.compile(r'(api-ms-win-|ucrtbase|kernel32|user32|advapi32|ws2_32|setupapi|hid|'
                                r'cfgmgr32|ole32|shell32|bcrypt|winusb|ntdll|msvcrt)', re.I)
            bad = [dll for dll in dlls if not system.match(dll)]
            if bad:
                sys.exit(f'linkage: unexpected DLLs {bad}')

    def package(self, exe, out, name):
        """Deterministic archive: openocd/{openocd[.exe],scripts,contrib,licenses,README-flipper.md,...}."""
        log('packaging')
        root = 'openocd'
        # The installed data directory: scripts/, contrib/, adapter firmware
        files = {}
        for path in sorted(exe.parent.rglob('*')):
            rel = path.relative_to(exe.parent).as_posix()
            if path.is_file() and not SKIP_SCRIPTS.search(rel):
                files[f'{root}/{rel}'] = path
        files[f'{root}/README-flipper.md'] = SRC / 'README-flipper.md'
        files[f'{root}/licenses/openocd/COPYING'] = SRC / 'COPYING'
        for path in sorted((SRC / 'LICENSES').rglob('*')):
            if path.is_file():
                files[f'{root}/licenses/openocd/{path.relative_to(SRC / "LICENSES").as_posix()}'] = path
        for dep, info in self.deps.items():
            for lic in info.get('license_files', []):
                src = next((self.work / 'src' / dep).iterdir()) / lic
                files[f'{root}/licenses/{dep}/{lic}'] = src
        out.mkdir(parents=True, exist_ok=True)
        epoch = int(os.environ.get('SOURCE_DATE_EPOCH', '315532800'))
        if self.cross:
            archive = out / f'{name}.zip'
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zf:
                for arc, path in sorted(files.items()):
                    info = zipfile.ZipInfo(arc, time.gmtime(max(epoch, 315532800))[:6])
                    info.external_attr = (0o755 if arc.endswith('.exe') else 0o644) << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    zf.writestr(info, path.read_bytes())
        else:
            archive = out / f'{name}.tar.gz'
            with open(archive, 'wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=epoch) as gz, \
                    tarfile.open(fileobj=gz, mode='w', format=tarfile.PAX_FORMAT) as tar:
                for arc, path in sorted(files.items()):
                    info = tarfile.TarInfo(arc)
                    data = path.read_bytes()
                    info.size = len(data)
                    info.mtime = epoch
                    info.mode = 0o755 if path == exe else 0o644
                    info.uname = info.gname = ''
                    tar.addfile(info, io.BytesIO(data))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        (out / f'{archive.name}.sha256').write_text(f'{digest}  {archive.name}\n')
        log(f'{archive} {digest}')
        return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--platform', choices=sorted(PLATFORMS))
    parser.add_argument('--fetch-only', action='store_true',
                        help='download the pinned dependency sources into --cache and stop')
    parser.add_argument('--out', type=Path, default=Path('dist'))
    parser.add_argument('--work', type=Path, default=Path('build-flipper'))
    parser.add_argument('--cache', type=Path, default=Path('build-flipper/cache'))
    parser.add_argument('--relstr', help='version suffix, e.g. -flipper-v1 (default: from git)')
    parser.add_argument('--name', help='archive name without extension, e.g. openocd-flipper-v1-<platform> (default: openocd-flipper-<platform>)')
    args = parser.parse_args()

    if args.fetch_only:
        args.cache.mkdir(parents=True, exist_ok=True)
        for name, dep in json.loads((HERE / 'deps.json').read_text()).items():
            if not dep.get('tool'):
                print(fetch(name, dep, args.cache.resolve()))
        return
    if not args.platform:
        parser.error('--platform is required')
    if PLATFORMS[args.platform]['host'] and host.system() != 'Linux':
        parser.error('Windows archives are cross-built on Linux')
    work = args.work.resolve() / args.platform
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    args.cache.resolve().mkdir(parents=True, exist_ok=True)
    build = Build(args.platform, work, args.cache.resolve())
    build.dependencies()
    exe = build.openocd(args.relstr)
    if PLATFORMS[args.platform]['host']:
        exe = exe.with_suffix('.exe')
    build.gate(exe)
    build.package(exe, args.out.resolve(), args.name or f'openocd-flipper-{args.platform}')


if __name__ == '__main__':
    main()
