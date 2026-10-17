"""Live changed-tile work, zero-work reuse, output deltas and full-cache reference."""
import json
from pathlib import Path
import time
import numpy as np
from bosio_wm_client import BosioWMClient
from projection_model import prepare_window,cell_coordinates

ROOT=Path(__file__).resolve().parent
MODE='fpga-dual+ps-incremental'
report=dict(tests=[])


def probe(yaw=0,fov=24,rect=(58,43,12,10)):
    desc,mask=prepare_window(128,96,yaw=yaw,fov_h=fov,fov_v=fov)
    x,y,w,h=rect
    for d in desc[mask]:
        u,v,den=cell_coordinates(d)
        cells=np.flatnonzero((den>0)&(u>=(x+1)*den)&(u<=(x+w-2)*den)&(v>=(y+1)*den)&(v<=(y+h-2)*den))
        if len(cells):return int(d[1])*4+int(cells[0])
    raise AssertionError('No probe cell')


def save(): (ROOT/'display_results.json').write_text(json.dumps(report,indent=2))


with BosioWMClient('incremental-validation',timeout=45) as c:
    initial=c.get_state()
    assert c.ping()['m']==32 and initial['compositor']==MODE
    original={w['window_id'] for w in initial['windows']};created=[]

    def check(name,cell=None,expected=None,mode=MODE,zero=False,noop=False,projected=None):
        generation=c.get_state()['generation'];deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            state=c.get_state();p=state.get('projection_presented')
            if state['render_error']:raise AssertionError(state['render_error'])
            if p and p['generation']>=generation and p['backend'].get('mode')==mode:break
            time.sleep(.02)
        else:raise TimeoutError(name)
        diag=c.call('get_display_diagnostics',cell_indices=[] if cell is None else [cell])
        assert diag['shadow_matches'] and diag['active_address']==diag['owned_address']
        assert diag['output']['enabled'] and diag['output']['scene_valid'] and not diag['output']['error']
        metrics=diag['presented']['backend']
        if expected is not None:assert diag['cell_indices']==[expected],(name,diag['cell_indices'],expected)
        if zero:assert metrics['jobs_per_core']==[0,0],(name,metrics)
        if noop:
            assert metrics['changed_tiles']==0 and metrics['output_words']==0 and metrics['update_kind']=='patch'
        if projected is not None:assert metrics['projected_windows']==projected,(name,metrics)
        reference=None
        if mode==MODE:
            reference=c.call('check_incremental_reference')
            assert reference['cached_mismatched_words']==reference['output_mismatched_words']==0 and reference['active_matches']
        item=dict(name=name,**diag,reference=reference,performance=state['performance'])
        report['tests'].append(item);save()
        print(json.dumps(dict(name=name,backend=metrics,reference=reference)),flush=True)
        return item

    try:
        w=c.create_window('Incremental cache test',width_deg=24,height_deg=24,
            surface_width=128,surface_height=96,always_on_top=True,focus_on_create=False)
        a=w['window_id'];created.append(a);c.fill(a,(255,0,0))
        sample=probe(rect=(30,40,8,8))
        first=check('initial_window_projection',sample,224,projected=[a])
        full_jobs=sum(first['presented']['backend']['jobs_per_core'])
        c.configure_window(a,title='Metadata-only change')
        unchanged=check('no_visual_change_zero_jobs_zero_commit',sample,224,zero=True,noop=True)
        assert unchanged['active_address']==first['active_address']
        pixels=np.full((8,8,3),(0,255,0),dtype=np.uint8)
        c.update_surface(a,pixels,x=30,y=40)
        part=check('small_surface_patch',sample,28,projected=[a])
        assert 0<sum(part['presented']['backend']['jobs_per_core'])<full_jobs
        assert part['presented']['backend']['update_kind']=='patch'
        c.update_surface(a,pixels,x=30,y=40)
        same=check('identical_pixels_zero_jobs_zero_commit',sample,28,zero=True,noop=True)
        assert same['active_address']==part['active_address']
        w=c.create_window('Cached upper layer',azimuth=3,width_deg=12,height_deg=12,
            surface_width=128,surface_height=96,always_on_top=True,focus_on_create=False)
        b=w['window_id'];created.append(b);c.fill(b,(0,0,255))
        center=probe(yaw=3,fov=12)
        check('new_layer_reuses_underlying_window',center,3,projected=[b])
        c.update_surface(a,np.full((8,8,3),(255,255,255),dtype=np.uint8),x=30,y=40)
        check('partial_update_reuses_unchanged_overlapping_layer',sample,255,projected=[a])
        c.raise_window(a)
        check('z_order_uses_cached_projection',center,224,zero=True)
        c.configure_window(a,azimuth=25)
        moved=probe(yaw=25)
        check('move_projects_only_moved_window',moved,224,projected=[a])
        c.configure_window(a,mapped=False)
        check('hide_uses_cached_underlay',center,3,zero=True)
        c.configure_window(a,mapped=True)
        check('show_reuses_hidden_window_cache',moved,224,zero=True)
        c.configure_window(a,decorated=True)
        check('native_fallback',mode='cpp-neon-fallback')
        c.configure_window(a,decorated=False)
        check('hardware_return_reuses_cache',moved,224,zero=True)
        c.destroy_window(b);created.remove(b)
        check('remove_upper_layer_zero_projection',zero=True)
        c.destroy_window(a);created.remove(a)
        check('desktop_restored_from_cache',zero=True)
        assert {w['window_id'] for w in c.get_state()['windows']}==original
        report.update(passed=True,output_m=32,full_window_jobs=full_jobs,
                      partial_window_jobs=sum(part['presented']['backend']['jobs_per_core']),final_state=c.get_state())
        save();print('ALL INCREMENTAL DISPLAY TESTS PASSED',flush=True)
    finally:
        for wid in created:c.destroy_window(wid)
