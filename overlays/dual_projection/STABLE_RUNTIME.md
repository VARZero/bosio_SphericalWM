# Current deployed M=32 runtime — 2026-10-17

This snapshot matches the running PYNQ deployment confirmed by the user after
rapid rotations. It preserves M=32, two projection cores, the original 16 KiB
2-way output read cache, and the 2048-pixel video FIFO. The 128 KiB cache / larger
video FIFO candidate has NOT been deployed and is not included here.

## Included fixes

BPT2 tile activation/clearing now reloads the output core's 4480-word metadata
bank. Content-only changes continue using address-only patch commits. DDR copies
and window projections remain incremental. Earlier active-DDR/reference checks
could pass while the hardware retained an empty directory; those checks alone
did not verify visible HDMI pixels. Reloading metadata made the window visible,
confirmed by the user. The driver regression model now retains hardware metadata.

Board validation: activation reloaded 4480 words, content-only editing reloaded
0 words, clearing reloaded 4480 words. All three cases matched full recomposition
and active DDR. See results/metadata_refresh_validation.json.

BoAYO now starts Dashboard once the scene and IMU are ready, at the current gaze.
The WM unit is preserved in deployment/bosio-window-manager.service. BoAYO's
matching service and startup override are in its deploy/m32 directory. These
units document the existing /home/xilinx/bosio_boayo_m32_20261017 layout and the
original bitstream directory; deploy the runtime/dependencies there before use.

## Bitstream identity

- bit SHA256: 2a9a981d9638077c49c09149d22d1eba962970e181a67fa35c20e4d1a6adb2d1
- HWH SHA256: 7d72d9c4dfc0b65893ab939c1650f82ae337aff38dc7c02ed1125142d3c0fb43

Both match the board's configured service files and the files in this overlay.
An earlier intermittent display resynchronization was not conclusively explained.
A diagnostic sweep measured ~30 produced frames/s at some poses, but the user
subsequently confirmed stable display during rapid movement with this original
bitstream. This publication does not claim an all-angle timing guarantee or
attribute that later observation to the undeployed hardware candidate.
