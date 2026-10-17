import json, math, time, signal
from pathlib import Path
import numpy as np
from bosio_wm_client import BosioWMClient
running=True
def stop(*args):
    global running
    running=False
signal.signal(signal.SIGTERM,stop)
signal.signal(signal.SIGINT,stop)
with BosioWMClient("incremental-preview",timeout=45) as c:
    state=c.get_state(); output=state['output']
    yaw=math.degrees(output.get('sensor_yaw_mrad',0)/1000)
    pitch=math.degrees(output.get('sensor_pitch_mrad',0)/1000)
    if output.get('sensor_invert_yaw'): yaw=-yaw
    if output.get('sensor_invert_pitch'): pitch=-pitch
    pixels=np.full((192,320,3),(16,32,64),dtype=np.uint8)
    pixels[:36]=(32,96,192)
    pixels[48:136,16:104]=(224,64,64)
    pixels[48:136,116:204]=(64,192,96)
    pixels[48:136,216:304]=(64,128,224)
    pixels[150:176,16:304]=(224,192,64)
    try:
        from PIL import Image,ImageDraw
        image=Image.fromarray(pixels);draw=ImageDraw.Draw(image)
        draw.text((12,10),'M=32 | DUAL PROJECTION',fill='white')
        draw.text((22,155),'CACHED WINDOW / INCREMENTAL TILES',fill='black')
        pixels=np.asarray(image)
    except ImportError: pass
    w=c.create_window('Incremental projection preview',azimuth=yaw,elevation=pitch,width_deg=32,height_deg=22,surface_width=320,surface_height=192,always_on_top=True,decorated=False)
    wid=w['window_id'];c.update_surface(wid,pixels)
    generation=c.get_state()['generation'];deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        s=c.get_state();p=s.get('projection_presented')
        if s['render_error']: raise RuntimeError(s['render_error'])
        if p and p['generation']>=generation: break
        time.sleep(.05)
    else: raise TimeoutError('Window presentation timed out')
    diag=c.call('get_display_diagnostics')
    assert diag['shadow_matches'] and not diag['output']['error']
    result=dict(window_id=wid,title=w['title'],azimuth=yaw,elevation=pitch,presented=True,backend=p['backend'],output_error=diag['output']['error'])
    Path('preview_window_result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
    while running:
        if not any(x['window_id']==wid for x in c.get_state()['windows']): break
        time.sleep(1)
