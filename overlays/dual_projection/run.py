"""Launch the M=32 runtime with independently versioned projection helpers."""
import os,runpy,sys
from pathlib import Path
root=Path(__file__).resolve().parent
wm=root.parents[1]
projection=wm/'hw/ip_repo/bosio_projection_core/sw'
if not projection.is_dir():raise SystemExit('Initialize Git submodules first')
sys.path[:0]=[str(root/'display_incremental'),str(projection),str(wm/'hw/ip_repo/bosio_output_core_1.0/software'),str(wm/'sw')]
os.environ.setdefault('BOSIO_COMPOSITOR_LIB',str(wm/'sw/libbosio_compositor.so'))
script='bosio_wm_daemon.py'
if len(sys.argv)>1 and sys.argv[1]=='--script':
    script=sys.argv[2];sys.argv=sys.argv[2:]
    if script not in ('test_incremental.py','validate_incremental.py','check_display_health.py','validate_display_pose.py','show_preview_window.py'):raise SystemExit('Unknown validation script')
else:
    sys.argv=[str(root/'display_incremental'/script),'--bit',str(root/'bitstream/bosio_output_projection_dual.bit'),'--m','32','--fps','30']+sys.argv[1:]
runpy.run_path(str(root/'display_incremental'/script),run_name='__main__')
