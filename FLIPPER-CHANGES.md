# Changes from mainline OpenOCD

Base: mainline [`openocd-org/openocd`](https://github.com/openocd-org/openocd) commit `4900bcdfc828` (2026-11-10), recorded in `contrib/flipper/base.txt`.

## Patches

| Commit | Change | Why |
| --- | --- | --- |
| rtos: add ARMv8-M (Cortex-M33/M23) FreeRTOS register stackings | Stack layouts for FreeRTOS ARMv8-M ports (PSPLIM and EXC_RETURN first), basic and FPU frames | Mainline reads M33 task stacks with the M4 layouts: garbage backtraces. From [raspberrypi/openocd#151](https://github.com/raspberrypi/openocd/pull/151) (Anuj Deshpande) |
| rtos/FreeRTOS: select ARMv8-M stacking from EXC_RETURN | On ARMv8-M, pick the layout from EXC_RETURN bit 4, not from the FPU/CPACR probe | The probe misreports the FPU on M33, so FPU-frame tasks were misread. Same PR |
| transport: select by a deprecated name on any adapter | `transport select hla_swd` (and `hla_jtag`, `dapdirect_*`) selects the adapter's transport of that kind, with a deprecation warning | `interface/stlink.cfg` now uses the dapdirect `st-link` driver, so the Flipper Zero and BUSY Bar ST-Link command lines failed |
| guess-rev: take the version suffix from OPENOCD_RELSTR | Builds may set their own version suffix | Releases report `0.12.0+dev-flipper-v<N>` |
| `flipper:` commits | `contrib/flipper/`, `.github/workflows/flipper-*.yml`, `README-flipper.md`, this file; mainline's `snapshot.yml` removed | Release builds for five platforms |

## Not carried over from the old fork (tag `legacy-2025`)

- STM32U5F/U5G and U59x/U5Ax flash IDs: in mainline.
- FreeRTOS M33 stacking (Particle): replaced by the patches above, which do not depend on the FPU probe.
- EFR32 series 2 driver (`efr32` branch): mainline has series 2 in `efm32.c`, configs in `target/silabs/`.
- CMSIS-DAP network transport (`hedger/dap_net`): mainline has `cmsis_dap_tcp` (`cmsis-dap backend tcp`). It is not wire-compatible with the draft.

## Checked on hardware

- Flipper One (RP2350, CMSIS-DAP probe), macOS and Windows: SWD, slot flashing, and FreeRTOS backtraces of all tasks. The previous Raspberry Pi build gave none.
- BUSY Bar (STM32U5), Windows: chip ID, `program … verify reset exit`, and FreeRTOS backtraces of all 46 tasks.
- Flipper Zero (STM32WB55), Windows, at 24 MHz with its own `stm32wbx.cfg`: chip ID, flash verify, and FreeRTOS backtraces.

## Known issues

- Right after GDB attaches, the first thread GDB lists can show the running task's registers when the halt lands outside it. This comes from the initial stop reply, not from the stack layouts; it is correct after the next stop.
- RP2350 RISC-V (Hazard3) cores cannot be debugged: mainline lacks RISC-V debug over the ARM DAP.
- A Flipper One firmware stopped for several seconds in tickless idle faults in `PendSV_Handler` on resume (PSPLIM stack overflow). This is a firmware bug and happens with the Raspberry Pi build too.
