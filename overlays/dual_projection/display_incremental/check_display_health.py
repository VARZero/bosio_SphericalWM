"""Read-only live presentation, stream rate and service checks after display tests."""
import json
from pathlib import Path
import subprocess
import time
from bosio_wm_client import BosioWMClient

with BosioWMClient('display-health', timeout=30) as client:
    before = client.get_state()
    started = time.monotonic()
    time.sleep(3)
    after = client.get_state()
    elapsed = time.monotonic()-started
    delta = (after['output']['frames']-before['output']['frames']) & 65535
    diagnostics = client.call('get_display_diagnostics')
    assert client.ping()['m'] == 32
    assert after['render_error'] is None and after['compositor'] == 'fpga-dual+ps-incremental'
    assert diagnostics['shadow_matches'] and diagnostics['active_address'] == diagnostics['owned_address']
    assert diagnostics['presented']['backend']['mode'] == 'fpga-dual+ps-incremental'
    assert diagnostics['presented']['backend']['cached_window_tiles'] > 0
    assert after['output']['enabled'] and after['output']['scene_valid'] and not after['output']['error']
    assert delta > 0, ('Output producer made no progress', delta)
    scanout = after.get('scanout')
    hdmi_fps = None
    if scanout:
        previous = before['scanout']
        hdmi_fps = ((scanout['video_frames']-previous['video_frames']) & 0xffffffff)/elapsed
        assert scanout['video_locked'] and not scanout['read_errors'] and not scanout['write_errors'], scanout
        assert scanout['lock_losses'] == previous['lock_losses'], scanout
        assert scanout['underflow_events'] == previous['underflow_events'], scanout
        assert 55 < hdmi_fps < 65, ('Unexpected HDMI frame rate', hdmi_fps)
    services = subprocess.check_output(['systemctl', 'show', 'bosio-window-manager', 'boayo-desktop',
                                       '-p', 'ActiveState', '-p', 'NRestarts'], text=True)
    assert services.count('ActiveState=active') == 2 and services.count('NRestarts=0') == 2
    report = dict(passed=True, m=32, frame_delta=delta, elapsed_seconds=elapsed,
                  output_fps=delta/elapsed, hdmi_fps=hdmi_fps, state=after, diagnostics=diagnostics, services=services)
    Path(__file__).with_name('display_health.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(dict(passed=True, m=32, output_fps=report['output_fps'],
                          hdmi_fps=hdmi_fps, presented=diagnostics['presented'], services=services)), flush=True)
