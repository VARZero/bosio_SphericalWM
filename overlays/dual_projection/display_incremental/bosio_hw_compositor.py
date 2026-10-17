"""Incremental per-window projection caches and frame-atomic changed-tile output."""
import math
import time
import numpy as np

TILES, HEADER, TILE_WORDS = 4220, 4476, 256
WORDS = (HEADER + TILES*TILE_WORDS + 15) & ~15
PATCH_MAGIC = 0x42505432  # BPT2: fixed payload slot plus directory update.


def rgb_index(rgb):
    r, g, b = map(int, rgb)
    return (r & 224) | ((g >> 3) & 28) | (b >> 6)


def initialize_scene(scene):
    k = np.arange(256, dtype=np.uint32)
    r, g, b = (k >> 5)*255//7, ((k >> 2) & 7)*255//7, (k & 3)*255//3
    neutral = (((k >> 2) & 7) == (k >> 5)) & ((k & 3) == (r >> 6))
    scene[:] = 0
    scene[:256] = (r << 16) | (np.where(neutral, r, b) << 8) | g
    scene[256:HEADER] = np.uint32(0xffffffff)


def plane_upper(p):
    return np.maximum.reduce([p[...,0], p[...,0]+31*p[...,1],
                              p[...,0]+31*(p[...,1]+p[...,2])]) + np.maximum(0, p[...,3])


def affected_source_tiles(desc, rect):
    """Conservative integer planes include the one-texel bilinear footprint."""
    x, y, width, height = rect
    u, v, d = np.asarray(desc[:,6:], dtype=np.uint32).view(np.int32).astype(np.int64).reshape(-1,3,4).transpose(1,0,2)
    planes = np.stack([d, u-(x-1)*d, (x+width)*d-u, v-(y-1)*d, (y+height)*d-v], axis=1)
    upper = plane_upper(planes)
    return (upper[:,0] > 0) & np.all(upper[:,1:] >= 0, axis=1)


def coverage_masks(desc):
    """Exact hardware coverage cached once per geometry; interior is constant."""
    from projection_model import cell_coordinates
    u, v, d = np.asarray(desc[:,6:], dtype=np.uint32).view(np.int32).astype(np.int64).reshape(-1,3,4).transpose(1,0,2)
    planes = np.stack([d, u, v, (desc[:,2].astype(np.int64)-1)[:,None]*d-u,
                       (desc[:,3].astype(np.int64)-1)[:,None]*d-v], axis=1)
    lower = -plane_upper(-planes)
    interior = (lower[:,0] > 0) & np.all(lower[:,1:] >= 0, axis=1)
    masks = np.ones((len(desc),1024),dtype=bool)
    for i in np.flatnonzero(~interior):
        u,v,d = cell_coordinates(desc[i])
        masks[i] = (d > 0) & (u >= 0) & (v >= 0) & (u <= d*(int(desc[i,2])-1)) & (v <= d*(int(desc[i,3])-1))
    return masks


def tile_patch(scene, ids):
    ids = np.asarray(ids,dtype=np.int32)
    if not len(ids):
        return np.empty(0,dtype=np.uint32)
    out = np.zeros(16 + len(ids)*(16+TILE_WORDS),dtype=np.uint32)
    out[:4] = [PATCH_MAGIC,TILE_WORDS,len(ids),len(out)]
    records = out[16:].reshape(-1,16+TILE_WORDS)
    records[:,0],records[:,1],records[:,2] = ids*TILE_WORDS,ids,scene[256+ids]
    records[:,16:] = scene[HEADER:HEADER+TILES*TILE_WORDS].reshape(TILES,TILE_WORDS)[ids]
    return out


class HardwareCompositor:
    name = 'fpga-dual+ps-incremental'

    def __init__(self, fallback, rays, scheduler=None, allocator=None):
        from projection_model import prepare_window, all_tile_vertices
        if scheduler is None:
            from dual_projector import DualProjector
            scheduler = DualProjector()
        if allocator is None:
            from pynq import allocate
            allocator = allocate
        self.prepare_window = prepare_window
        self.scheduler,self.allocate,self.fallback = scheduler,allocator,fallback
        self.rays = rays.reshape(-1,3)
        self.texture = self.scratch = self.texture_owner = None
        self.caches,self.previous_tiles = {},{}
        self.previous_order = []
        self.previous_background = self.pointer_key = None
        self.previous_pointer_tiles,self.pending_dirty = set(),set()
        self.pointer_indices = (np.empty(0,dtype=np.int64),np.empty(0,dtype=np.int64))
        self.scene = np.zeros(WORDS,dtype=np.uint32)
        initialize_scene(self.scene)
        self.pixels = self.scene[HEADER:HEADER+TILES*TILE_WORDS].view(np.uint8).reshape(TILES,1024)
        self.presentation_valid,self.last_backend = False,None
        self.total_hw_jobs = 0
        q = all_tile_vertices()
        self.cap_centers = q.mean(axis=1)
        self.cap_centers /= np.linalg.norm(self.cap_centers,axis=1)[:,None]
        q = q/np.linalg.norm(q,axis=2)[:,:,None]
        radii = np.arccos(np.clip(np.einsum('tvc,tc->tv',q,self.cap_centers).min(axis=1),-1,1))
        self.cap_threshold = np.cos(radii + math.radians(2.2) + 1e-6)
        self.metrics = dict(mode='initializing',hardware_frames=0,fallback_frames=0)

    def ack_presented(self):
        self.presentation_valid = self.last_backend == 'hardware'

    def invalidate_presentation(self):
        self.presentation_valid,self.last_backend = False,None

    def _fallback(self, windows, order, focus, pointer, background, m, reason, full):
        incremental = not full and self.last_backend == 'native' and hasattr(self.fallback,'render_update')
        if incremental:
            scene,count,kind = self.fallback.render_update(windows,order,focus,pointer,background,m)
        else:
            scene,count = self.fallback.render_packed(windows,order,focus,pointer,background,m)
            kind = 'full'
        self.presentation_valid,self.last_backend = False,'native'
        self.metrics = dict(mode='cpp-neon-fallback',reason=reason,jobs_per_core=[0,0],
            hardware_frames=self.metrics['hardware_frames'],fallback_frames=self.metrics['fallback_frames']+1)
        return scene,count,kind

    def _geometry(self, w):
        key = (w.surface_width,w.surface_height,w.azimuth,w.elevation,w.roll,w.width_deg,w.height_deg)
        desc,visible = self.prepare_window(w.surface_width,w.surface_height,dst=0,
            yaw=w.azimuth,pitch=w.elevation,roll=w.roll,fov_h=w.width_deg,fov_v=w.height_deg,clear=True)
        ids = np.flatnonzero(visible)
        lookup = np.full(TILES,-1,dtype=np.int32)
        lookup[ids] = np.arange(len(ids))
        return dict(key=key,desc=desc[visible],ids=ids,lookup=lookup,
            masks=coverage_masks(desc[visible]),pixels=np.zeros((len(ids),1024),dtype=np.uint8),
            invalid=set(range(len(ids))),revision=None,source=None)

    def _source_changes(self, cache, w):
        revision = int(w.surface_revision)
        if cache['revision'] == revision:
            return
        size = (w.surface_height,w.surface_width)
        if cache['source'] is None or cache['source'].shape != size:
            rgb = np.asarray(w.surface,dtype=np.uint32)
            cache['source'] = (rgb[:,:,0] << 16) | (rgb[:,:,1] << 8) | rgb[:,:,2]
            cache['invalid'].update(range(len(cache['ids'])))
        else:
            x,y,width,height = w.dirty_rect or (0,0,w.surface_width,w.surface_height)
            rgb = np.asarray(w.surface[y:y+height,x:x+width],dtype=np.uint32)
            packed = (rgb[:,:,0] << 16) | (rgb[:,:,1] << 8) | rgb[:,:,2]
            old = cache['source'][y:y+height,x:x+width]
            changed = packed != old
            if np.any(changed):
                rows,cols = np.flatnonzero(np.any(changed,axis=1)),np.flatnonzero(np.any(changed,axis=0))
                rect = (x+int(cols[0]),y+int(rows[0]),int(cols[-1]-cols[0]+1),int(rows[-1]-rows[0]+1))
                cache['invalid'].update(map(int,np.flatnonzero(affected_source_tiles(cache['desc'],rect))))
                old[:] = packed
        cache['revision'] = revision

    def _project(self, wid, cache):
        indices = np.asarray(sorted(cache['invalid']),dtype=np.int32)
        if not len(indices):
            return None
        source = cache['source'].reshape(-1)
        if self.texture is None or len(self.texture) < len(source):
            if self.texture is not None:
                self.texture.freebuffer();self.texture = None
            self.texture = self.allocate(shape=(len(source),),dtype=np.uint32)
            self.texture_owner = None
        owner,uploaded = (wid,cache['revision']),0
        if self.texture_owner != owner:
            self.texture[:len(source)] = source
            self.texture_owner,uploaded = owner,len(source)
        words = len(indices)*TILE_WORDS
        if self.scratch is None or len(self.scratch) < words:
            if self.scratch is not None:
                self.scratch.freebuffer();self.scratch = None
            self.scratch = self.allocate(shape=(words,),dtype=np.uint32)
        desc = cache['desc'][indices].copy()
        desc[:,1] = np.arange(len(indices),dtype=np.uint32)*TILE_WORDS
        timing = self.scheduler.run(self.texture,desc,self.scratch,workers=2,
            texture_words=len(source),scene_words=words,verify_descriptors=False)
        if timing['status'] != [0,0]:
            raise RuntimeError('FPGA projection error: '+repr(timing['status']))
        cache['pixels'][indices] = np.array(self.scratch[:words]).view(np.uint8).reshape(-1,1024)
        cache['invalid'].difference_update(map(int,indices))
        timing['texture_upload_words'] = uploaded
        return timing

    def _pointer(self, pointer):
        key = tuple(pointer) if pointer[2] else (False,)
        if key == self.pointer_key:
            return False
        if not pointer[2]:
            outer = inner = np.empty(0,dtype=np.int64)
        else:
            az,el = np.radians(pointer[:2])
            direction = np.array([math.cos(el)*math.sin(az),math.sin(el),-math.cos(el)*math.cos(az)],dtype=np.float32)
            if len(self.rays) == TILES*1024:
                ids = np.flatnonzero(self.cap_centers @ direction >= self.cap_threshold)
                dots = np.einsum('tij,j->ti',self.rays.reshape(TILES,1024,3)[ids],direction)
                t,i = np.nonzero(dots >= math.cos(math.radians(2.2)))
                outer = ids[t]*1024+i
                t,i = np.nonzero(dots >= math.cos(math.radians(1.0)))
                inner = ids[t]*1024+i
            else:
                dots = self.rays @ direction
                outer = np.flatnonzero(dots >= math.cos(math.radians(2.2)))
                inner = np.flatnonzero(dots >= math.cos(math.radians(1.0)))
        self.pointer_indices,self.pointer_key = (outer,inner),key
        return True

    def _update(self,windows,order,focus,pointer,background,m,full=False):
        if m != 32 or any(windows[i].shape or windows[i].decorated or
                not (1 <= windows[i].surface_width <= 2048 and 1 <= windows[i].surface_height <= 2048) or
                not (0 < windows[i].width_deg < 160 and 0 < windows[i].height_deg < 160) for i in order):
            return self._fallback(windows,order,focus,pointer,background,m,
                                  'shape, decoration, or dimensions require native renderer',full)
        started = time.perf_counter()
        dirty,current = self.pending_dirty,set(order)
        for wid in set(self.previous_order)-current:
            dirty.update(self.previous_tiles[wid])
        self.caches = {wid:c for wid,c in self.caches.items() if wid in windows}
        jobs,cells = [0,0],[0,0]
        hw_ms = driver_ms = 0.0
        uploaded = reused = 0
        projected_windows,footprints = [],{}
        for wid in order:
            w = windows[wid]
            key = (w.surface_width,w.surface_height,w.azimuth,w.elevation,w.roll,w.width_deg,w.height_deg)
            cache = self.caches.get(wid)
            if cache is None or cache['key'] != key:
                dirty.update(self.previous_tiles.get(wid,set()))
                old,cache = cache,self._geometry(w)
                if old is not None and old['source'] is not None and old['source'].shape == (w.surface_height,w.surface_width):
                    cache['source'],cache['revision'] = old['source'],old['revision']
                self.caches[wid] = cache
                dirty.update(map(int,cache['ids']))
            self._source_changes(cache,w)
            if wid not in self.previous_order:
                dirty.update(map(int,cache['ids']))
            indices = list(cache['invalid'])
            dirty.update(map(int,cache['ids'][indices]))
            reused += len(cache['ids'])-len(indices)
            timing = self._project(wid,cache)
            if timing:
                self.total_hw_jobs += sum(timing['jobs_per_core'])
                projected_windows.append(wid)
                jobs = [a+b for a,b in zip(jobs,timing['jobs_per_core'])]
                cells = [a+b for a,b in zip(cells,timing['written_cells_per_core'])]
                hw_ms += timing['milliseconds'];driver_ms += timing['total_call_ms']
                uploaded += timing['texture_upload_words']
            footprints[wid] = set(map(int,cache['ids']))
        old_pos = {wid:i for i,wid in enumerate(self.previous_order)}
        common = [wid for wid in order if wid in old_pos]
        for i,a in enumerate(common):
            for b in common[i+1:]:
                if old_pos[a] > old_pos[b]:
                    dirty.update(footprints[a] & footprints[b])
        bg = rgb_index(background)
        if bg != self.previous_background:
            dirty.update(range(TILES))
        pointer_changed = self._pointer(pointer)
        pointer_tiles = set(map(int,self.pointer_indices[0]//1024)) | set(map(int,self.pointer_indices[1]//1024))
        if pointer_changed:
            dirty.update(self.previous_pointer_tiles | pointer_tiles)
        ids = np.asarray(sorted(dirty),dtype=np.int32)
        changed = np.empty(0,dtype=np.int32)
        if len(ids):
            composed = np.full((len(ids),1024),bg,dtype=np.uint8)
            for wid in order:
                cache = self.caches[wid]
                local = cache['lookup'][ids]
                rows = np.flatnonzero(local >= 0)
                if len(rows):
                    old = composed[rows]
                    np.copyto(old,cache['pixels'][local[rows]],where=cache['masks'][local[rows]])
                    composed[rows] = old
            lookup = np.full(TILES,-1,dtype=np.int32)
            lookup[ids] = np.arange(len(ids))
            for indices,color in zip(self.pointer_indices,(rgb_index((10,10,10)),255)):
                rows = lookup[indices//1024]
                mask = rows >= 0
                composed[rows[mask],indices[mask]%1024] = color
            mask = np.any(composed != self.pixels[ids],axis=1)
            changed = ids[mask]
            self.pixels[changed] = composed[mask]
            nonzero = np.any(composed[mask] != 0,axis=1)
            self.scene[256+changed] = np.where(nonzero,changed*1024,0xffffffff).astype(np.uint32)
        self.previous_order,self.previous_tiles = list(order),footprints
        self.previous_background,self.previous_pointer_tiles = bg,pointer_tiles
        dirty.clear()
        for wid in order:
            windows[wid].dirty_rect = None
        if full or not self.presentation_valid:
            result,kind = self.scene.copy(),'full'
        else:
            result,kind = tile_patch(self.scene,changed),'patch'
        self.last_backend = 'hardware'
        self.metrics = dict(mode=self.name,hardware_frames=self.metrics['hardware_frames']+1,
            fallback_frames=self.metrics['fallback_frames'],windows=list(order),projected_windows=projected_windows,
            jobs_per_core=jobs,written_cells_per_core=cells,hardware_ms=hw_ms,driver_ms=driver_ms,
            texture_upload_words=uploaded,reused_window_tiles=reused,dirty_tiles=len(ids),changed_tiles=len(changed),
            total_hw_jobs=self.total_hw_jobs,cached_window_tiles=sum(len(c['ids']) for c in self.caches.values()),
            update_kind=kind,output_words=len(result),active_tiles=int(np.count_nonzero(self.scene[256:HEADER] != 0xffffffff)),
            compose_ms=(time.perf_counter()-started)*1000,sampling='fixed-point bilinear RGB332')
        return result,len(changed),kind

    def render_update(self,*args):
        return self._update(*args)

    def reference_snapshot(self):
        """Diagnostic full composition from cached layers, independent of dirty sets."""
        if self.last_backend != 'hardware' or not self.presentation_valid:
            raise RuntimeError('No acknowledged hardware snapshot')
        result=np.zeros(WORDS,dtype=np.uint32);initialize_scene(result)
        pixels=result[HEADER:HEADER+TILES*TILE_WORDS].view(np.uint8).reshape(TILES,1024)
        pixels[:]=self.previous_background
        for wid in self.previous_order:
            c=self.caches[wid]
            assert not c['invalid']
            target=pixels[c['ids']]
            np.copyto(target,c['pixels'],where=c['masks'])
            pixels[c['ids']]=target
        flat=pixels.reshape(-1)
        flat[self.pointer_indices[0]]=rgb_index((10,10,10))
        flat[self.pointer_indices[1]]=255
        active=np.any(pixels!=0,axis=1)
        result[256:HEADER]=np.where(active,np.arange(TILES)*1024,0xffffffff).astype(np.uint32)
        return result

    def render_packed(self,*args):
        scene,count,_ = self._update(*args,full=True)
        return scene,count

    def render(self,*args):
        result = self.fallback.render(*args)
        self.presentation_valid,self.last_backend = False,'native'
        self.metrics = dict(mode='cpp-neon-fallback',reason='external RGB scene composition',jobs_per_core=[0,0],
            hardware_frames=self.metrics['hardware_frames'],fallback_frames=self.metrics['fallback_frames']+1)
        return result

    def close(self):
        if self.scheduler is not None:
            self.scheduler.close();self.scheduler = None
        for name in ('texture','scratch'):
            buf = getattr(self,name,None)
            if buf is not None:
                buf.freebuffer();setattr(self,name,None)
        if self.fallback is not None:
            self.fallback.close();self.fallback = None
