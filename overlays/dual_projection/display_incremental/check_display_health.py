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
    assert diagnostics['presented']['backend']['total_hw_jobs'] > 0
    assert diagnostics['presented']['backend']['cached_window_tiles'] > 0
    assert after['output']['enabled'] and after['output']['scene_valid'] and not after['output']['error']
    assert 55 < delta/elapsed < 65, ('Unexpected output frame rate', delta/elapsed)
    services = subprocess.check_output(['systemctl', 'show', 'bosio-window-manager', 'boayo-desktop',
                                       '-p', 'ActiveState', '-p', 'NRestarts'], text=True)
    assert services.count('ActiveState=active') == 2 and services.count('NRestarts=0') == 2
    report = dict(passed=True, m=32, frame_delta=delta, elapsed_seconds=elapsed,
                  output_fps=delta/elapsed, state=after, diagnostics=diagnostics, services=services)
    Path(__file__).with_name('display_health.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(dict(passed=True, m=32, output_fps=report['output_fps'],
                          presented=diagnostics['presented'], services=services)), flush=True)
