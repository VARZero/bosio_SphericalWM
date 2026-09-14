#!/bin/sh
# Install the BS24 bitstream and BOSIO window daemon as a boot service on PYNQ-Z2.
set -eu

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer with sudo." >&2
    exit 1
fi

SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
INSTALL_DIR=/home/xilinx/bosio_v2
PYTHON=/usr/local/share/pynq-venv/bin/python3
SERVICE=bosio-window-manager.service

required_files="
bosio_wm_daemon.py
bosio_window_manager.py
bosio_native_compositor.py
bosio_mouse_input.py
bosio_buttons.py
bosio_driver_v2.py
bosio_geometry_v2.py
bosio_wm_client.py
libbosio_compositor.so
bitstream/bosio_output_disp.bit
bitstream/bosio_output_disp.hwh
bosio-window-manager.service
"

for relative in $required_files; do
    if [ ! -r "$SOURCE_DIR/$relative" ]; then
        echo "Missing required file: $SOURCE_DIR/$relative" >&2
        exit 1
    fi
done
if [ ! -x "$PYTHON" ]; then
    echo "PYNQ Python was not found at $PYTHON" >&2
    exit 1
fi

install -d -m 0755 "$INSTALL_DIR" "$INSTALL_DIR/bitstream"
for relative in $required_files; do
    case "$relative" in
        bosio-window-manager.service) continue ;;
    esac
    source_path="$SOURCE_DIR/$relative"
    target_path="$INSTALL_DIR/$relative"
    if [ "$(readlink -f "$source_path")" != "$(readlink -f "$target_path" 2>/dev/null || true)" ]; then
        install -m 0644 "$source_path" "$target_path"
    fi
done

install -m 0644 "$SOURCE_DIR/bosio-window-manager.service" "/etc/systemd/system/$SERVICE"
chown -R xilinx:xilinx "$INSTALL_DIR"
systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl restart "$SERVICE"

attempt=0
while [ "$attempt" -lt 90 ]; do
    if [ -S /tmp/bosio-wm.sock ] && systemctl is-active --quiet "$SERVICE"; then
        break
    fi
    attempt=$((attempt + 1))
    sleep 1
done

if ! systemctl is-active --quiet "$SERVICE"; then
    systemctl status "$SERVICE" --no-pager >&2 || true
    journalctl -u "$SERVICE" -n 40 --no-pager >&2 || true
    exit 1
fi

cd "$INSTALL_DIR"
"$PYTHON" - <<'PY'
from bosio_wm_client import BosioWMClient

with BosioWMClient("boot-installer") as client:
    pong = client.ping()
    state = client.get_state()
output = state.get("output") or {}
if pong.get("m") != 32:
    raise SystemExit(f"Unexpected compositor resolution: {pong}")
if not output.get("scene_valid") or output.get("error"):
    raise SystemExit(f"Output core did not start cleanly: {output}")
print("BOSIO_BOOT_READY", {
    "compositor": state.get("compositor"),
    "scene_valid": output.get("scene_valid"),
    "sensor_active": output.get("sensor_active"),
    "fclk0_mhz": output.get("fclk0_mhz"),
})
PY

echo "Installed and enabled $SERVICE. The BS24 overlay will be loaded on every boot."
