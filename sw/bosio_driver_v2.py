"""PYNQ v2 ABI. Immutable scene DMA snapshots and frame-atomic pose commits."""
import time
import numpy as np
from bosio_geometry_v2 import camera_coefficients,pack_scene

class BosioV2:
 def __init__(self,bitstream,m=16,download=True):
  if m not in (8,16,32):raise ValueError('M must be 8,16,32')
  import pynq
  from pynq.pl_server import embedded_device
  if pynq.Device.devices:pynq.Device.active_device=pynq.Device.devices[0]
  from bosio_buttons import BosioButtons
  if download:
   self.overlay=pynq.Overlay(str(bitstream))
   # The running board was actually at 62.5MHz although Linux clk_summary said
   # 100MHz. The MMCM was designed for 100MHz; 62.5MHz produces ~37.5Hz HDMI.
   pynq.Clocks.fclk0_mhz=100.0
   self.clock_mhz=float(pynq.Clocks.fclk0_mhz)
   if abs(self.clock_mhz-100)>0.1:raise RuntimeError(f'Unexpected FCLK0 {self.clock_mhz}')
   time.sleep(.05)
   self.core=self.overlay.output_core_0
   if not hasattr(self.overlay,'buttons_gpio'):raise RuntimeError('Wrong bitstream: buttons_gpio is required')
   self.buttons=BosioButtons(self.overlay.buttons_gpio)
  else:
   # Attach to the design programmed by the boot service. Constructing an
   # Overlay object on this board can disturb the running PL even when its
   # download flag is false, so use the fixed HWH addresses directly.
   self.overlay=None
   self.clock_mhz=100.0
   self.core=pynq.MMIO(0x43C00000,0x10000)
   self.buttons=BosioButtons.from_address(0x41200000)
  self.signature=self.core.read(0x7c)
  if self.signature not in (0x42533234,0x42533235):raise RuntimeError('Wrong bitstream: BS24 or BS25 required')
  self.ddr_cache=self.signature==0x42533235
  self._ddr_buffers=[None,None];self._ddr_current=0;self._ddr_pending=None;self._scene_shadow=None
  self.m=m;self.allocate=pynq.allocate;self.buffer=None;self.running=False
  self.core.write(0x5c,{8:0,16:1,32:2}[m]);self.core.write(0x78,0)
 def status(self):
  s=self.core.read(4)
  sensor=self.core.read(0x78)
  signed32=lambda value:value-(1<<32) if value&(1<<31) else value
  inv=self.core.read(0x20)&7;aa=self.core.read(0x1c)
  return dict(raw=s,enabled=bool(s&1),scene_valid=bool(s&2),dma_busy=bool(s&4),pose_pending=bool(s&8),scene_pending=bool(s&16),error=bool(s&32),frames=s>>16,received=self.core.read(0x70),fclk0_mhz=self.clock_mhz,aa_enabled=bool(aa&1),aa_threshold=(aa>>8)&255,aa_strength=(aa>>16)&255,sensor_mode=bool(sensor&1),sensor_active=bool(sensor&2),sensor_pose_busy=bool(sensor&4),sensor_applied=(sensor>>16)&0xffff,sensor_packets=self.core.read(0x30),sensor_yaw_mrad=signed32(self.core.read(0x24)),sensor_pitch_mrad=signed32(self.core.read(0x28)),sensor_roll_mrad=signed32(self.core.read(0x2c)),sensor_invert_yaw=bool(inv&1),sensor_invert_pitch=bool(inv&2),sensor_invert_roll=bool(inv&4),ddr_cache=self.ddr_cache,cache_line_bytes=self.core.read(0x34) if self.ddr_cache else 0,cache_bytes=self.core.read(0x38) if self.ddr_cache else 0,cache_ways=self.core.read(0x3c) if self.ddr_cache else 0,cache_hits=self.core.read(0x10) if self.ddr_cache else 0,cache_misses=self.core.read(0x14) if self.ddr_cache else 0,cache_stall_cycles=self.core.read(0x18) if self.ddr_cache else 0)
 def _wait(self,predicate,timeout=3):
  end=time.monotonic()+timeout
  while time.monotonic()<end:
   s=self.status()
   if s['error']:raise RuntimeError('Scene DMA/AXI error')
   if predicate(s):return s
   time.sleep(.001)
  raise TimeoutError(f'Core did not acknowledge: {self.status()}')
 def set_pose(self,yaw,pitch,roll=0,fov_h=60,fov_v=45,wait=True):
  if self.status()['sensor_mode']:self.core.write(0x78,0)
  self._wait(lambda s:not s['pose_pending'])
  coeff=camera_coefficients(yaw,pitch,roll,fov_h,fov_v)
  self.core.write(0x60,0)
  for value in coeff.flat:self.core.write(0x64,int(value)&0xffffffff)
  self.core.write(0x68,1)
  if wait and self.running:self._wait(lambda s:not s['pose_pending'])
 def use_sensor(self,enabled=True,wait=True,timeout=5.0):
  before=self.status()['sensor_applied']
  self.core.write(0x78,1 if enabled else 0)
  if enabled and wait and self.running:
   # A continuous 1 kHz source can start the next conversion immediately
   # after a frame-atomic commit. The one-cycle idle gap is too short for
   # software polling, so the applied packet counter is the completion token.
   self._wait(lambda s:s['sensor_active'] and s['sensor_applied']!=before,timeout=timeout)
 def set_sensor_invert(self,yaw=False,pitch=False,roll=False):
  """Invert selected sensor axes in hardware before Q24 pose generation."""
  value=(1 if yaw else 0)|(2 if pitch else 0)|(4 if roll else 0)
  self.core.write(0x20,value)
  return value
 def set_antialias(self,enabled=True,threshold=24,strength=32):
  """Configure projected-stream edge AA. Threshold and strength are 0..255."""
  threshold=int(threshold);strength=int(strength)
  if not 0<=threshold<=255 or not 0<=strength<=255:raise ValueError('AA threshold and strength must be 0..255')
  value=(1 if enabled else 0)|(threshold<<8)|(strength<<16)
  self.core.write(0x1c,value);return value
 def upload(self,rgb):
  try:
   from bosio_native_compositor import pack_scene as native_pack_scene
   scene,count=native_pack_scene(rgb,self.m)
  except OSError:
   scene,count=pack_scene(rgb,self.m)
  self.upload_words(scene);return count
 def upload_words(self,scene):
  scene=np.asarray(scene,dtype=np.uint32)
  if self.ddr_cache:return self._upload_ddr_scene(scene)
  if len(scene)>53632:raise ValueError('BS24 scene exceeds BRAM capacity; BS25 is required')
  self._wait(lambda s:not s['dma_busy'])
  if self.buffer is None or len(self.buffer)<len(scene):
   if self.buffer is not None:self.buffer.freebuffer()
   self.buffer=self.allocate(shape=(len(scene),),dtype=np.uint32)
  self.buffer[:len(scene)]=scene;self.buffer.flush()
  before=self.core.read(0x70)
  self.core.write(8,self.buffer.physical_address);self.core.write(12,len(scene));self.core.write(0x6c,1)
  # Wait for transfer to finish; disabled core cannot perform the frame swap yet.
  self._wait(lambda s:((s['received']-before)&0xffffffff)>=len(scene) and (s['scene_pending'] or not s['dma_busy']))
  if self.running:self._wait(lambda s:not s['dma_busy'])

 def upload_patch(self,patch):
  """Apply BPT1 atomically: BS24 BRAM patch or BS25 DDR snapshot switch."""
  patch=np.asarray(patch,dtype=np.uint32)
  if not len(patch):return 0
  if self.ddr_cache:return self._upload_ddr_patch(patch)
  if self.core.read(0x7c)!=0x42533234:raise RuntimeError('Output core does not support BS24 partial tile updates')
  if len(patch)%16 or int(patch[0])!=0x42505431:raise ValueError('Invalid BPT1 patch packet')
  self._wait(lambda s:not s['dma_busy'])
  if self.buffer is None or len(self.buffer)<len(patch):
   if self.buffer is not None:self.buffer.freebuffer()
   self.buffer=self.allocate(shape=(len(patch),),dtype=np.uint32)
  self.buffer[:len(patch)]=patch;self.buffer.flush()
  before=self.core.read(0x70)
  self.core.write(8,self.buffer.physical_address);self.core.write(12,len(patch));self.core.write(0x6c,2)
  self._wait(lambda s:((s['received']-before)&0xffffffff)>=len(patch) and (s['scene_pending'] or not s['dma_busy']))
  if self.running:self._wait(lambda s:not s['dma_busy'])
  return int(patch[2])
 def start(self):
  self.core.write(0,1);self.running=True
  self._wait(lambda s:s['scene_valid'] and not s['pose_pending'])
  if self.ddr_cache and self._ddr_pending is not None:self._finish_ddr_commit()
 def _ddr_buffer(self,index,words):
  # Cache fills may read past the last used word. Pad to the maximum line size.
  size=(int(words)+255)&~255
  buf=self._ddr_buffers[index]
  if buf is None or len(buf)<size:
   if buf is not None:buf.freebuffer()
   buf=self.allocate(shape=(size,),dtype=np.uint32);buf[:]=0
   self._ddr_buffers[index]=buf
  return buf
 def _commit_ddr(self,target,word_count,patch=False):
  self.core.write(8,int(self._ddr_buffers[target].physical_address))
  self.core.write(12,int(word_count));self.core.write(0x6c,2 if patch else 1)
  self._ddr_pending=target
  # A stopped projector cannot acknowledge a frame boundary until start().
  address=int(self._ddr_buffers[target].physical_address)
  self._wait(lambda s:s['scene_pending'] or self.core.read(0x44)==address,timeout=10)
  if self.running:self._finish_ddr_commit()
 def _finish_ddr_commit(self):
  address=int(self._ddr_buffers[self._ddr_pending].physical_address)
  self._wait(lambda s:not s['dma_busy'] and self.core.read(0x44)==address,timeout=10)
  self._ddr_current=self._ddr_pending;self._ddr_pending=None
  other=self._ddr_current^1
  buf=self._ddr_buffer(other,len(self._scene_shadow))
  if self._pending_ranges is None:
   buf[:len(self._scene_shadow)]=self._scene_shadow
  else:
   for offset,payload in self._pending_ranges:buf[offset:offset+len(payload)]=payload
  buf.flush()
 def _upload_ddr_scene(self,scene):
  if len(scene)<4480 or len(scene)>1084816 or len(scene)%16:
   raise ValueError('Invalid BS25 full-scene length')
  if self._ddr_pending is not None:raise RuntimeError('Start the pending DDR scene before another upload')
  self._wait(lambda s:not s['dma_busy'])
  target=self._ddr_current^1
  buf=self._ddr_buffer(target,len(scene));buf[:len(scene)]=scene;buf.flush()
  self._scene_shadow=scene.copy();self._pending_ranges=None
  self._commit_ddr(target,len(scene))
 def _upload_ddr_patch(self,patch):
  if self._scene_shadow is None:raise RuntimeError('A full DDR scene is required before patches')
  if self._ddr_pending is not None:raise RuntimeError('A DDR scene is already pending')
  if len(patch)<16 or len(patch)%16 or int(patch[0])!=0x42505431:
   raise ValueError('Invalid BPT1 header')
  tile_words,records=int(patch[1]),int(patch[2])
  if tile_words!=self.m*self.m//4 or records>4220 or int(patch[3])!=len(patch) or len(patch)!=16+records*(16+tile_words):
   raise ValueError('Invalid BPT1 record size')
  ranges=[]
  for record in range(records):
   start=16+record*(16+tile_words);offset=int(patch[start])+4476;tile=int(patch[start+1])
   if tile>=4220 or offset+tile_words>len(self._scene_shadow) or int(self._scene_shadow[256+tile])!=(offset-4476)*4:
    raise ValueError('BPT1 record does not match the current DDR directory')
   ranges.append((offset,patch[start+16:start+16+tile_words]))
  if not ranges:return 0
  self._wait(lambda s:not s['dma_busy'])
  target=self._ddr_current^1;buf=self._ddr_buffers[target]
  for offset,payload in ranges:
   self._scene_shadow[offset:offset+len(payload)]=payload
   buf[offset:offset+len(payload)]=payload
  buf.flush();self._pending_ranges=ranges
  self._commit_ddr(target,len(self._scene_shadow),patch=True)
  return records
 def close(self):
  # Finish outstanding DMA before releasing its DDR source.
  if self.ddr_cache:self._wait(lambda s:not s['dma_busy'] or s['scene_pending'])
  elif self.running:self._wait(lambda s:not s['dma_busy'])
  self.core.write(0,0);self.running=False
  # BS25 continues reading DDR while enabled. Stop and drain before freeing it.
  if self.ddr_cache:
   deadline=time.monotonic()+3
   while not self.core.read(0x40)&1:
    if time.monotonic()>deadline:raise TimeoutError('DDR sampling has not drained; buffers retained')
    time.sleep(.001)
   for buf in self._ddr_buffers:
    if buf is not None:buf.freebuffer()
   self._ddr_buffers=[None,None]
  if self.buffer is not None:self.buffer.freebuffer();self.buffer=None
  if self.overlay is None:self.buttons.close()
