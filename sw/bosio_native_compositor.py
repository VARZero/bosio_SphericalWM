"""ctypes binding for the optional C++/NEON spherical compositor."""
import ctypes
import os
from pathlib import Path
import numpy as np

_pack_library = None

def pack_scene(rgb,m=16):
 global _pack_library
 array=np.ascontiguousarray(rgb,dtype=np.uint8)
 if array.shape!=(20,211,m*m,3):raise ValueError('Invalid triangular cell array shape')
 if _pack_library is None:
  path=Path(os.environ.get('BOSIO_COMPOSITOR_LIB',Path(__file__).with_name('libbosio_compositor.so')))
  _pack_library=ctypes.CDLL(str(path));_pack_library.bosio_pack_scene.argtypes=[ctypes.POINTER(ctypes.c_uint8),ctypes.c_uint32,ctypes.POINTER(ctypes.c_uint32),ctypes.c_uint32,ctypes.POINTER(ctypes.c_uint32)];_pack_library.bosio_pack_scene.restype=ctypes.c_int
 output=np.empty(53664,dtype=np.uint32);active=ctypes.c_uint32()
 words=_pack_library.bosio_pack_scene(array.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),m,output.ctypes.data_as(ctypes.POINTER(ctypes.c_uint32)),len(output),ctypes.byref(active))
 if words==-2:raise ValueError('Active tiles exceed 196608-byte cache')
 if words<0:raise RuntimeError('native scene pack failed')
 return output[:words].copy(),int(active.value)

class NativeCompositor:
 def __init__(self,rays):
  path=Path(os.environ.get('BOSIO_COMPOSITOR_LIB',Path(__file__).with_name('libbosio_compositor.so')))
  self.lib=ctypes.CDLL(str(path));self._bind()
  self.rays=np.ascontiguousarray(rays,dtype=np.float32).reshape(-1,3)
  self.ctx=self.lib.bosio_compositor_create(self.rays.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),len(self.rays))
  if not self.ctx:raise RuntimeError('native compositor allocation failed')
  self.known=set()
 def _bind(self):
  L=self.lib;L.bosio_compositor_create.argtypes=[ctypes.POINTER(ctypes.c_float),ctypes.c_uint32];L.bosio_compositor_create.restype=ctypes.c_void_p
  L.bosio_compositor_destroy.argtypes=[ctypes.c_void_p]
  L.bosio_compositor_sync_window.argtypes=[ctypes.c_void_p,ctypes.c_uint64]+[ctypes.c_float]*5+[ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint64,ctypes.POINTER(ctypes.c_uint8)]
  L.bosio_compositor_sync_window_dirty.argtypes=L.bosio_compositor_sync_window.argtypes+[ctypes.c_uint32]*4
  L.bosio_compositor_remove_window.argtypes=[ctypes.c_void_p,ctypes.c_uint64]
  L.bosio_compositor_render.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint64),ctypes.c_uint32,ctypes.c_uint64,ctypes.c_float,ctypes.c_float,ctypes.c_int,ctypes.c_uint8,ctypes.c_uint8,ctypes.c_uint8,ctypes.POINTER(ctypes.c_uint8)]
  L.bosio_compositor_render_packed.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint64),ctypes.c_uint32,ctypes.c_uint64,ctypes.c_float,ctypes.c_float,ctypes.c_int,ctypes.c_uint8,ctypes.c_uint8,ctypes.c_uint8,ctypes.c_uint32,ctypes.POINTER(ctypes.c_uint32),ctypes.c_uint32,ctypes.POINTER(ctypes.c_uint32)];L.bosio_compositor_render_packed.restype=ctypes.c_int
  L.bosio_compositor_render_patch.argtypes=L.bosio_compositor_render_packed.argtypes;L.bosio_compositor_render_patch.restype=ctypes.c_int
  L.bosio_compositor_error.argtypes=[ctypes.c_void_p];L.bosio_compositor_error.restype=ctypes.c_char_p
 def _sync(self,windows,z_order):
  current=set(z_order)
  for wid in self.known-current:self.lib.bosio_compositor_remove_window(self.ctx,wid)
  self.known=current
  for wid in z_order:
   w=windows[wid];surf=np.ascontiguousarray(w.surface,dtype=np.uint8)
   rect=w.dirty_rect or (0,0,0,0)
   rc=self.lib.bosio_compositor_sync_window_dirty(self.ctx,wid,w.azimuth,w.elevation,w.roll,w.width_deg,w.height_deg,w.surface_width,w.surface_height,w.surface_revision,surf.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),*rect)
   if rc:raise RuntimeError(self.lib.bosio_compositor_error(self.ctx).decode())
  return np.ascontiguousarray(z_order,dtype=np.uint64)
 def render(self,windows,z_order,focus,pointer,background,shape):
  order=self._sync(windows,z_order);out=np.empty((*shape,3),dtype=np.uint8);bg=list(map(int,background))
  rc=self.lib.bosio_compositor_render(self.ctx,order.ctypes.data_as(ctypes.POINTER(ctypes.c_uint64)),len(order),focus or 0,pointer[0],pointer[1],int(pointer[2]),*bg,out.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)))
  if rc:raise RuntimeError(self.lib.bosio_compositor_error(self.ctx).decode())
  return out
 def render_packed(self,windows,z_order,focus,pointer,background,m):
  order=self._sync(windows,z_order);out=np.empty(53664,dtype=np.uint32);active=ctypes.c_uint32();bg=list(map(int,background))
  words=self.lib.bosio_compositor_render_packed(self.ctx,order.ctypes.data_as(ctypes.POINTER(ctypes.c_uint64)),len(order),focus or 0,pointer[0],pointer[1],int(pointer[2]),*bg,m,out.ctypes.data_as(ctypes.POINTER(ctypes.c_uint32)),len(out),ctypes.byref(active))
  if words==-2:raise ValueError('Active tiles exceed 196608-byte cache')
  if words<0:raise RuntimeError(self.lib.bosio_compositor_error(self.ctx).decode() or 'native packed render failed')
  for w in windows.values():w.dirty_rect=None
  return out[:words].copy(),int(active.value)
 def render_update(self,windows,z_order,focus,pointer,background,m):
  order=self._sync(windows,z_order);out=np.empty(53664,dtype=np.uint32);tiles=ctypes.c_uint32();bg=list(map(int,background));args=(self.ctx,order.ctypes.data_as(ctypes.POINTER(ctypes.c_uint64)),len(order),focus or 0,pointer[0],pointer[1],int(pointer[2]),*bg,m,out.ctypes.data_as(ctypes.POINTER(ctypes.c_uint32)),len(out),ctypes.byref(tiles))
  words=self.lib.bosio_compositor_render_patch(*args)
  if words==-3:
   words=self.lib.bosio_compositor_render_packed(*args);kind='full'
  else:kind='patch'
  if words==-2:raise ValueError('Active tiles exceed 196608-byte cache')
  if words<0:raise RuntimeError(self.lib.bosio_compositor_error(self.ctx).decode() or 'native incremental render failed')
  for w in windows.values():w.dirty_rect=None
  return out[:words].copy(),int(tiles.value),kind
 def close(self):
  if self.ctx:self.lib.bosio_compositor_destroy(self.ctx);self.ctx=None
 def __del__(self):
  try:self.close()
  except Exception:pass
