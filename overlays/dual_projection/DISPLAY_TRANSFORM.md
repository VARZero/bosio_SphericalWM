# Whole-display rotation and reflection

The DTF1 Output Core extension rotates the final spherical-scene sampling axes.
It accepts 0/90/180/270 degrees clockwise, then horizontal and vertical reflection
in output-screen coordinates. Settings apply at a frame boundary and work with
both the hardware IMU path and software camera poses.

```python
from bosio_wm_client import BosioWMClient

with BosioWMClient('display-settings') as wm:
    wm.set_display_transform(rotation=90, flip_x=False, flip_y=False)
    wm.set_display_transform(rotation=0, flip_x=True, flip_y=False)
    wm.set_display_transform()  # restore default orientation
```

The running WM owns the hardware. The IPC operation takes its driver lock and
does not touch app geometry, content surfaces, cached projections or scene
generation. An unchanged scene still requires zero new projection jobs and zero
scene commits when only display orientation changes. A capability check rejects
these operations on older overlays instead of silently succeeding.

From a checkout on the board:

```sh
python overlays/dual_projection/run.py --script display_transform.py --rotation 90
python overlays/dual_projection/run.py --script display_transform.py --flip-x
python overlays/dual_projection/run.py --script display_transform.py --status
python overlays/dual_projection/run.py --script display_transform.py
```

Each call supplies the complete setting; omitted flips are false. Default/reset
orientation is unrotated and unreflected. Settings currently last until hardware
reset/reprogramming; this API does not change boot configuration.

HDMI remains 1280x720 at 60 Hz with triple-buffer VDMA. Rotation preserves the
center and sample pitch. At 90/270 degrees the logical viewport is 720x1280:
the scene is sampled through a portrait viewport rather than squeezing the old
landscape image or adding black bars. Its visible bounds therefore change.

IMU gaze and existing spherical pointer APIs stay in world coordinates. Their
center hit stays at the display center through every transform. The evdev mouse
adapter inversely transforms screen-relative deltas using the active hardware
setting. External clients can use `input_display_move(dx,dy)` for screen-oriented
angular deltas (+x right, +y down). Existing `input_move`/`input_warp` remain
spherical-coordinate operations for compatibility.

The underlying registers, coefficient math and RTL validation are documented in
[Output Core display transforms](../../hw/ip_repo/bosio_output_core_1.0/docs/DISPLAY_TRANSFORM.md).

## Deployed validation, 2026-10-18

The PYNQ now runs `bitstream/bosio_output_projection_transform.bit` and its matching
HWH, with the updated Output Core driver and WM runtime. The default
`bosio_output_projection_dual.bit` and HWH are byte-identical copies of these
deployed artifacts. The Output Core submodule is pinned to the matching DTF1
source and driver, so the normal M=32 launcher selects this release. The prior
release manifest is retained as `results/scanout_publication_manifest_20261017.json`;
its bitstream remains available in Git history.

All 16 software-pose combinations passed actual USB HDMI image comparison, and
all 16 combinations passed live IMU/API checks without additional projection jobs.
The 14 live incremental cases passed full-cache reference comparison: a small
patch required 5 projection jobs instead of 72, while unchanged content required
zero jobs and no scene commit. HDMI recorded zero lock losses and no additional
underflows. Default orientation, IMU tracking and Dashboard were restored.

The routed build uses 36,374 LUTs, 43,905 FFs, 50 BRAM36 and 155 DSPs. Compared with
the previous build this adds 602 LUTs and 678 FFs, with unchanged BRAM/DSP usage.
Final setup/hold slack is +0.032/+0.010 ns at 100 MHz. The initial -0.007 ns setup
result was rejected; post-route physical optimization and rerouting passed the
same timing gates before a new bitstream was exported.

See the [artifact/source hashes and build reports](results/display_transform_20261018/manifest.json),
[capture/API results](verification/display_transform_20261018/capture_results.json),
and [live incremental results](verification/display_transform_20261018/incremental_results.json).
