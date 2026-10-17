"""Interactive validation; controls only output pose, never reprograms the PL."""
import json
import math
import sys
import time
import numpy as np
sys.path.insert(0,'/home/xilinx/bosio_boayo_m32_20261017')
from pynq.pl_server import embedded_device
from pynq import MMIO
from bosio_driver_v2 import BosioV2
from bosio_wm_client import BosioWMClient

d=BosioV2.__new__(BosioV2)
d.core=MMIO(0x43c00000,0x10000);d.running=True;d.clock_mhz=100.;d.ddr_cache=True
d.display_transform_supported=d.core.read(0x50)==0x44544631;d._last_pose_coefficients=None
assert d.display_transform_supported
old_sensor=bool(d.core.read(0x78)&1)
c=BosioWMClient('display-transform-probe',timeout=45)
wid=None

def snapshot():
    s=c.get_state()
    assert not s['render_error'] and not s['output']['error']
    assert s['scanout']['video_locked'] and not s['scanout']['read_errors'] and not s['scanout']['write_errors']
    return s

def reply(value):print(json.dumps(value),flush=True)

try:
    status=d.status();yaw=math.degrees(status['sensor_yaw_mrad']/1000)
    pitch=math.degrees(status['sensor_pitch_mrad']/1000)
    d.set_pose(yaw,pitch,0)
    image=np.full((240,320,3),24,dtype=np.uint8)
    image[8:232,8:312]=(240,240,240)
    image[12:228,12:308]=(32,32,32)
    image[24:104,24:144]=(224,32,32)
    image[24:104,176:296]=(32,224,64)
    image[136:216,24:144]=(32,64,224)
    image[136:216,176:296]=(224,192,32)
    image[40:88,48:56]=(255,255,255);image[80:88,48:104]=(255,255,255)
    image[146:198,190:202]=(0,0,0);image[146:158,190:270]=(0,0,0)
    image[112:128,152:168]=(255,255,255)
    info=c.create_window('Transform validation',azimuth=yaw,elevation=pitch,width_deg=24,height_deg=18,
                         surface_width=320,surface_height=240,decorated=False,focus_on_create=False)
    wid=info['window_id'];c.update_surface(wid,image)
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        state=snapshot()
        if state.get('projection_presented',{}).get('generation')==state['generation']:break
        time.sleep(.05)
    else:raise TimeoutError('test pattern not presented')
    baseline=state;time.sleep(.3)
    reply({'ready':True,'state':state})
    for line in sys.stdin:
        command=json.loads(line);op=command['op']
        if op=='mode':
            mode=command['mode'];d.set_display_transform((mode&3)*90,bool(mode&4),bool(mode&8))
            time.sleep(.15);state=snapshot()
            assert state['generation']==baseline['generation']
            assert state['projection']['total_hw_jobs']==baseline['projection']['total_hw_jobs']
            reply({'mode':mode,'state':state})
        elif op=='sensor_modes':
            d.use_sensor(True);states=[]
            for mode in range(16):
                value=c.set_display_transform((mode&3)*90,bool(mode&4),bool(mode&8))
                state=snapshot()
                assert not value['pending'] and state['output']['sensor_mode'] and state['output']['sensor_active']
                assert state['generation']==baseline['generation']
                assert state['projection']['total_hw_jobs']==baseline['projection']['total_hw_jobs']
                states.append({'mode':mode,'output':state['output'],'scanout':state['scanout']})
            c.set_display_transform(0,False,False)
            c.pointer_warp(yaw,pitch)
            assert c.get_state()['pointer']['window_id']==wid
            reply({'sensor_modes':states,'gaze_hit_test':True,'reference':c.call('check_incremental_reference')})
        elif op=='finish':
            reply({'done':True});break
        else:raise ValueError(op)
finally:
    try:
        d.set_display_transform(0,False,False)
        d.use_sensor(old_sensor)
    finally:
        if wid is not None:c.destroy_window(wid)
        c.close()
