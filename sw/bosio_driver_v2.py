"""PYNQ v2 ABI. Immutable scene DMA snapshots and frame-atomic pose commits."""
import time
import numpy as np
from bosio_geometry_v2 import camera_coefficients,pack_scene

class BosioV2:
 def __init__(self,bitstream,m=16):
  if m not in (8,16,32):raise ValueError('M must be 8,16,32')
  import pynq
  from pynq.pl_server import embedded_device
  if pynq.Device.devices:pynq.Device.active_device=pynq.Device.devices[0]
  self.overlay=pynq.Overlay(str(bitstream))
  # The running board was actually at 62.5MHz although Linux clk_summary said
  # 100MHz. The MMCM was designed for 100MHz; 62.5MHz produces ~37.5Hz HDMI.
  pynq.Clocks.fclk0_mhz=100.0
  self.clock_mhz=float(pynq.Clocks.fclk0_mhz)
  if abs(self.clock_mhz-100)>0.1:raise RuntimeError(f'Unexpected FCLK0 {self.clock_mhz}')
  time.sleep(.05)
  self.core=self.overlay.output_core_0
  from bosio_buttons import BosioButtons
  if not hasattr(self.overlay,'buttons_gpio'):raise RuntimeError('Wrong bitstream: buttons_gpio is required')
  self.buttons=BosioButtons(self.overlay.buttons_gpio)
  if self.core.read(0x7c)!=0x42533233:raise RuntimeError('Wrong bitstream: BS23 partial-tile core required')
  self.m=m;self.allocate=pynq.allocate;self.buffer=None;self.running=False
  self.core.write(0x5c,{8:0,16:1,32:2}[m]);self.core.write(0x78,0)
 def status(self):
  s=self.core.read(4)
  sensor=self.core.read(0x78)
  signed32=lambda value:value-(1<<32) if value&(1<<31) else value
  inv=self.core.read(0x20)&7
  return dict(raw=s,enabled=bool(s&1),scene_valid=bool(s&2),dma_busy=bool(s&4),pose_pending=bool(s&8),scene_pending=bool(s&16),error=bool(s&32),frames=s>>16,received=self.core.read(0x70),fclk0_mhz=self.clock_mhz,sensor_mode=bool(sensor&1),sensor_active=bool(sensor&2),sensor_pose_busy=bool(sensor&4),sensor_applied=(sensor>>16)&0xffff,sensor_packets=self.core.read(0x30),sensor_yaw_mrad=signed32(self.core.read(0x24)),sensor_pitch_mrad=signed32(self.core.read(0x28)),sensor_roll_mrad=signed32(self.core.read(0x2c)),sensor_invert_yaw=bool(inv&1),sensor_invert_pitch=bool(inv&2),sensor_invert_roll=bool(inv&4))
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
 def upload(self,rgb):
  try:
   from bosio_native_compositor import pack_scene as native_pack_scene
   scene,count=native_pack_scene(rgb,self.m)
  except OSError:
   scene,count=pack_scene(rgb,self.m)
  self.upload_words(scene);return count
 def upload_words(self,scene):
  scene=np.asarray(scene,dtype=np.uint32)
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
  """Apply a BPT1 tile patch atomically to both cache banks (ABI BS23)."""
  patch=np.asarray(patch,dtype=np.uint32)
  if not len(patch):return 0
  if self.core.read(0x7c)!=0x42533233:raise RuntimeError('Output core does not support partial tile updates')
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
 def close(self):
  # Finish outstanding DMA before releasing its DDR source.
  if self.running:self._wait(lambda s:not s['dma_busy'])
  self.core.write(0,0);self.running=False
  if self.buffer is not None:self.buffer.freebuffer();self.buffer=None
