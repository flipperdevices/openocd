# OpenOCD for Flipper Devices

The `flipper` branch is mainline [OpenOCD](https://github.com/openocd-org/openocd) plus a few patches that the Flipper Zero (STM32WB55, Cortex-M4), BUSY Bar (STM32U5, Cortex-M33) and Flipper One (RP2350) projects need. Releases are self-contained archives for Linux, macOS and Windows.

## What this branch adds

| Patch | Why |
| --- | --- |
| FreeRTOS register stacking for ARMv8-M (Cortex-M33), with and without FPU frames | Mainline reads M33 task stacks with the Cortex-M4 layouts, so thread backtraces are garbage. From [raspberrypi/openocd#151](https://github.com/raspberrypi/openocd/pull/151) |
| `transport select hla_swd` (and the other deprecated names) on any adapter | `interface/stlink.cfg` now uses the dapdirect `st-link` driver; older project scripts still select `hla_swd` |
| `guess-rev.sh` honours `OPENOCD_RELSTR` | Release builds name their own version suffix |
| `contrib/flipper/`, `.github/workflows/flipper-*.yml` | Release builds |

Everything else comes from mainline, including RP2350 (`target/rp2350.cfg`, the `rp2xxx` flash driver), STM32U5 device IDs and CMSIS-DAP over TCP.

## Compatibility notes

- **RP2350:** use mainline's `target/rp2350.cfg`. Targets are `rp2350.cm0` and `rp2350.cm1`. Raspberry Pi's `rp2350-rescue.cfg` and `rp2350-riscv.cfg` do not exist here: use `-c "set RESCUE 1"` or `-c "set USE_CORE {rv0 rv1}"`. The RISC-V cores cannot be debugged yet.
- **ST-Link firmware older than V2J24** has no dapdirect support: use `interface/stlink-hla.cfg` instead of `interface/stlink.cfg`.
- Deprecated commands such as `gdb_port`, `cmsis_dap_serial`, `hla_serial` and `-chain-position` still work, with a warning.

## Releases

Tag `flipper-v<N>` on the `flipper` branch. The release workflow builds and tests every platform and publishes:

- `openocd-flipper-v<N>-<platform>.tar.gz` (`.zip` on Windows) for `linux-x86_64`, `linux-aarch64`, `darwin-arm64`, `windows-x64` and `windows-arm64`;
- `SHA256SUMS`, `release.json` and a source archive with the dependency sources.

Each archive holds `openocd/openocd[.exe]` with `scripts/` next to it, `contrib/60-openocd.rules` and `licenses/`. USB libraries are linked statically; Linux needs glibc 2.28 or newer and `libudev1`.

`openocd --version` reports `0.12.0+dev-flipper-v<N>`.

## Building

```shell
contrib/flipper/build.py --platform darwin-arm64 --out dist
```

`contrib/flipper/deps.json` pins every dependency by URL and sha256. Linux archives are built in a `manylinux_2_28` container, Windows archives are cross-built on Linux with llvm-mingw; see `.github/workflows/flipper-build.yml`.

## Updating the base

Rebase the Flipper patches onto a mainline commit that is at least two weeks old, rebuild, and check the targets above on hardware before tagging.
