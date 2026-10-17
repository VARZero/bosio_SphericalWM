# Buffered HDMI scanout

M=32 and both projection engines are unchanged. The compositor still projects
only changed window tiles, reuses cached layers, and commits only changed scene
payload/directory ranges. An unchanged scene still produces zero projection jobs
and zero scene commits.

The output path now separates pixel generation from HDMI transmission:

```
Output Core RGB24 -> VDMA write -> three DDR frames -> VDMA read
    -> Video Out (timing master) -> free-running 720p60 VTC / HDMI
```

VDMA write is the dynamic genlock master; read is the dynamic genlock slave.
Internal genlock exchanges ownership of completed frames and prevents the writer
from overwriting the frame being read. When the producer is late, scanout repeats
the latest completed image. The first images are initialized to black. The VTC's
clock enable is always asserted, independent of producer readiness.

The PS allocates/clears the three buffers once and configures the DMA. Ongoing
frame storage, repetition and switching happen in hardware, without CPU copies.
This adds 8,294,400 bytes (7.91 MiB) of DDR storage. At 60 frames/s, RGB24 scanout
reads 165.9 MB/s; writing adds 2.7648 MB per generated frame. The output sampler's
16 KiB cache and the projector tile caches remain unchanged. Completed-frame
buffering adds latency; slow pixel generation is still displayed at its actual
update rate while HDMI timing remains continuous.

## Registers and ownership

- Existing Output Core: `0x43c00000`, HP0.
- Existing projection engines: `0x43c10000` / HP1, `0x43c20000` / HP2.
- VDMA: `0x43000000`, both memory channels through HP3.
- Video health GPIO: `0x41210000`.
  - Offset 0: bit 0 locked, bit 1 underflow, bit 2 overflow, bit 3 ever locked,
    bit 4 overflow seen, bits 15:8 saturated lock-loss count,
    bits 31:16 saturated underflow rising-edge count.
  - Offset 8: native video VSYNC count, wrapping at 32 bits.

`bosio_scanout.py` owns the allocation until both DMA channels have reset and
halted. The daemon starts scanout only when the HWH contains `scanout_vdma`;
legacy overlays remain supported. `get_state()['scanout']` reports DMA errors,
frame ownership, lock state, underflow events and native video frame count.
The existing Output Core frame counter measures generated frames, not HDMI rate.

Video Out has an 8192-pixel FIFO with a 2048-pixel start threshold. VDMA has 8192
read-side and 4096 write-side line buffers. These absorb memory latency, but an
unbounded DDR read failure or physical cable/power failure remains outside the
producer-stall guarantee. Health counters make those failures distinguishable.

## Verification

Host: `python -m unittest discover -s overlays/dual_projection/verification` for
DMA buffer lifetime/configuration tests, and `python overlays/dual_projection/run.py
--script test_incremental.py` for partial-vs-full recomposition and no-op reuse.
`verification/tb_video_health.v` checks the actual health RTL with an RTL simulator.

On board, `check_display_health.py` reports producer and native HDMI frame rates
separately. Fault injection must run with exclusive control over software pose
and producer enable, restore the previous IMU/enable state in a finally block,
and independently record the capture-card picture. Counter progress alone does
not prove that the HDMI receiver displayed an image.

With the buffered overlay and Dashboard running, privileged
`run.py --script validate_scanout.py` performs the angle sweep and four-second
producer stop/restart. It temporarily takes over pose and restores IMU/enable on
exit. Record HDMI separately while running it. To attribute incremental job
counts, temporarily suspend unrelated desktop UI updates during
`validate_incremental.py`, then resume them; otherwise its per-operation metrics
can be superseded by a subsequent caption-only update.

The DMA ordering and synchronization follow AMD PG020's
[programming sequence](https://docs.amd.com/r/en-US/pg020_axi_vdma/Programming-Sequence)
and [dynamic genlock slave](https://docs.amd.com/r/en-US/pg020_axi_vdma/Dynamic-Genlock-Slave)
model. Video timing follows PG044's
[master timing mode](https://docs.amd.com/r/en-US/pg044_v_axis_vid_out/Timing-Modes).

## Accepted board result — 2026-10-17

PYNQ-Z2, M=32, two projectors, BoAYO Dashboard and external caption controls:

- 13 angle cases (roll 0–315 degrees, returning to 0, plus yaw/pitch offsets):
  HDMI 59.81–59.97 Hz, zero additional underflows or lock losses. Producer rates
  varied from 51.91 to 90.38 fps; scanout remained independent.
- Producer disabled for 4.0035 seconds: zero generated frames, 240 native HDMI
  frames, unchanged visible capture image, zero new underflows or lock losses.
  Producer restart recovered without losing HDMI sync. This deliberate partial
  frame abort raised S2MM frame-error flags `0x4090`; they were recorded, cleared,
  and did not recur. Normal angle changes had no VDMA errors.
- One underflow was recorded during initial empty-pipeline startup, before the
  first lock. No subsequent event occurred during angle, stop/restart, or scene
  validation. Report deltas separately from this startup event.
- Capture: 57.233 seconds / 1,717 frames at 1280×720, 30 fps. FFmpeg blackdetect
  found no near-total black frames (98% dark pixels, pixel threshold 0.05).
  Independent 5 Hz image sampling also confirmed the frozen picture during stop.
- Incremental tests: all 14 board cases passed, including overlapping cached
  windows, z-order, hide/show, move, fallback and recovery. The 8×8 source patch
  used 5 projection jobs versus 72 for the full test window, changed 3 output
  tiles and sent 832 words. Identical/no-visual updates used zero jobs and zero
  output words. Full 4,220-tile references had zero cached/output mismatches.
- Final services active, restart counts zero, IMU restored, Dashboard visible.
  No reboot was required or performed for this verification.

Evidence: [capture intervals](verification/scanout_20261017/summary.json),
[board events](verification/scanout_20261017/capture_events.json),
[incremental cases](verification/scanout_20261017/incremental_results.json),
[final health](verification/scanout_20261017/display_health.json).
Host checks: 14 incremental tests, 5 scanout driver tests and 10 WM tests passed;
the actual health RTL simulation reported `VIDEO_HEALTH_PASS`.

Routed utilization: 35,772 LUTs (67.24%), 43,227 FFs (40.63%), 50 BRAM tiles
(35.71%), 155 DSPs (70.45%). Setup slack +0.148 ns, hold +0.050 ns. Timing,
bus-skew and HDMI pin checks passed; DRC had warnings but no errors.

The board runs `/home/xilinx/bosio_output_projection_scanout_20261017/` with
`bosio_output_projection_scanout.bit/.hwh`. The repository bundles those same
bytes under the existing `bitstream/bosio_output_projection_dual.bit/.hwh` names.

- Bit SHA256: `ce31ede26331fe5c45ca09acda75262cf24d4fe3610cb073a52f60d7a2236342`
- HWH SHA256: `c27170a7069c6583b1179831f0b2e385724654b4c506add4d83036cad85a340f`

The enabled WM service has a `scanout.conf` drop-in selecting the new bitstream;
its base unit remains intact. Runtime daemon and scanout allocation helper are in
`/home/xilinx/bosio_boayo_m32_20261017`. Original daemon/unit backups are under the
new overlay directory's `before/` folder. Rollback: stop BoAYO and WM, restore the
backed-up daemon, remove only the scanout drop-in, reload systemd and restart WM
then BoAYO. The original bit/HWH remain at their original dual-overlay path.
