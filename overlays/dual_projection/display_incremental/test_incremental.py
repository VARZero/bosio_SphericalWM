"""Incremental results vs full CPU recomposition, and immutable output snapshots."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'hw/ip_repo/bosio_projection_core/sw'))
import unittest
from types import SimpleNamespace
import numpy as np
from projection_model import prepare_window,reference_job,all_tile_vertices
from bosio_hw_compositor import HardwareCompositor,initialize_scene,tile_patch,HEADER,TILES,TILE_WORDS,WORDS
from partition_jobs import split_by_tile
from bosio_driver_v2 import BosioV2


class Buffer(np.ndarray):
    next_address = 0x10000000
    flush_log = []
    def __new__(cls,shape,dtype):
        obj = np.zeros(shape,dtype=dtype).view(cls)
        obj.physical_address = cls.next_address
        cls.next_address += 0x800000
        return obj
    def freebuffer(self): pass
    def flush(self): Buffer.flush_log.append(self.nbytes)


class Scheduler:
    def __init__(self): self.calls=[];self.fail=False
    def run(self,texture,desc,scene,workers,**kw):
        if self.fail:
            self.fail=False
            raise RuntimeError('injected projection failure')
        queues=split_by_tile(desc,workers)
        cells=[sum(reference_job(texture,scene,d) for d in q) for q in queues]
        jobs=list(map(len,queues));self.calls.append(jobs)
        return dict(status=[0,0],jobs_per_core=jobs,written_cells_per_core=cells,milliseconds=0,total_call_ms=0)
    def close(self): pass


class Fallback:
    def render_packed(self,*args): return np.array([123],dtype=np.uint32),1
    def render_update(self,*args): return np.empty(0,dtype=np.uint32),0,'patch'
    def close(self): pass


def window(color,fov=24,yaw=0):
    return SimpleNamespace(surface_width=128,surface_height=96,azimuth=yaw,elevation=0,
        roll=0,width_deg=fov,height_deg=fov,shape=[],decorated=False,surface_revision=1,
        surface=np.full((96,128,3),color,dtype=np.uint8),dirty_rect=(0,0,128,96))


class CompositorTests(unittest.TestCase):
    def setUp(self):
        self.scheduler=Scheduler()
        self.rays=np.array([[0,0,-1],[0,0,1]],dtype=np.float32)
        self.hw=HardwareCompositor(Fallback(),self.rays,self.scheduler,Buffer)
        self.windows={1:window((255,0,0)),2:window((0,0,255),12,3)}
        self.order=[1,2];self.pointer=(0,0,False)
    def tearDown(self): self.hw.close()
    def render(self):
        result=self.hw.render_update(self.windows,self.order,2,self.pointer,(0,0,0),32)
        self.hw.ack_presented()
        return result
    def expected(self):
        scene=np.zeros(WORDS,dtype=np.uint32);initialize_scene(scene)
        for wid in self.order:
            w=self.windows[wid];rgb=w.surface.astype(np.uint32)
            texture=((rgb[:,:,0]<<16)|(rgb[:,:,1]<<8)|rgb[:,:,2]).reshape(-1)
            desc,mask=prepare_window(w.surface_width,w.surface_height,dst=HEADER,yaw=w.azimuth,
                pitch=w.elevation,roll=w.roll,fov_h=w.width_deg,fov_v=w.height_deg,clear=False)
            for d in desc[mask]:reference_job(texture,scene,d)
        if self.pointer[2]:
            az,el=np.radians(self.pointer[:2]);v=np.array([np.cos(el)*np.sin(az),np.sin(el),-np.cos(el)*np.cos(az)],dtype=np.float32)
            dots=self.rays@v;pixels=scene[HEADER:HEADER+TILES*TILE_WORDS].view(np.uint8)
            pixels[np.flatnonzero(dots>=np.cos(np.radians(2.2)))]=0
            pixels[np.flatnonzero(dots>=np.cos(np.radians(1.0)))]=255
        active=np.any(scene[HEADER:HEADER+TILES*TILE_WORDS].reshape(TILES,TILE_WORDS)!=0,axis=1)
        scene[256:HEADER]=np.where(active,np.arange(TILES)*1024,0xffffffff).astype(np.uint32)
        return scene
    def assert_full_equal(self):
        np.testing.assert_array_equal(self.hw.scene,self.expected())
        np.testing.assert_array_equal(self.hw.reference_snapshot(),self.expected())
    def change(self,wid,x,y,width,height,color):
        w=self.windows[wid];w.surface[y:y+height,x:x+width]=color
        w.surface_revision+=1;w.dirty_rect=(x,y,width,height)
    def test_unchanged_and_identical_upload_are_zero_jobs_zero_patch(self):
        self.render();self.assert_full_equal()
        for repeat in range(2):
            if repeat:
                w=self.windows[1];w.surface_revision+=1;w.dirty_rect=(0,0,128,96)
            patch,count,kind=self.render()
            self.assertEqual((len(patch),count,kind),(0,0,'patch'))
            self.assertEqual(self.hw.metrics['jobs_per_core'],[0,0])
            self.assertEqual(self.hw.metrics['texture_upload_words'],0)
    def test_partial_edges_and_unchanged_overlapping_layer_reuse(self):
        self.render();full_jobs=len(self.hw.caches[1]['ids'])
        for x,y in [(30,40),(0,0),(126,94),(63,45)]:
            self.change(1,x,y,2,2,(0,255,0))
            patch,_,kind=self.render()
            self.assertEqual(kind,'patch')
            self.assertEqual(self.hw.metrics['projected_windows'],[1])
            self.assertGreater(sum(self.hw.metrics['jobs_per_core']),0)
            self.assertLess(sum(self.hw.metrics['jobs_per_core']),full_jobs)
            self.assert_full_equal()
    def test_geometry_order_hide_reveal_remove(self):
        self.render();self.windows[1].azimuth=8
        self.render();self.assertEqual(self.hw.metrics['projected_windows'],[1]);self.assert_full_equal()
        self.order=[2,1];self.render()
        self.assertEqual(self.hw.metrics['jobs_per_core'],[0,0]);self.assert_full_equal()
        self.order=[2];self.render()
        self.assertEqual(self.hw.metrics['jobs_per_core'],[0,0]);self.assert_full_equal()
        self.order=[2,1];self.render()
        self.assertEqual(self.hw.metrics['jobs_per_core'],[0,0]);self.assert_full_equal()
        del self.windows[1];self.order=[2];self.render();self.assert_full_equal()
    def test_cursor_uses_cached_layers(self):
        self.render()
        for pointer in [(0,0,True),(180,0,True),(0,0,False)]:
            self.pointer=pointer;self.render()
            self.assertEqual(self.hw.metrics['jobs_per_core'],[0,0]);self.assert_full_equal()
            self.assertLessEqual(self.hw.metrics['dirty_tiles'],1)
    def test_fallback_return_and_failed_commit_reuse_projection(self):
        self.render();self.windows[1].shape=[[0,0,128,96,4]]
        self.assertEqual(self.render()[2],'full')
        self.assertEqual(self.render()[2],'patch')
        self.windows[1].shape=[]
        self.assertEqual(self.render()[2],'full')
        self.assertEqual(self.hw.metrics['jobs_per_core'],[0,0]);self.assert_full_equal()
        self.hw.invalidate_presentation()
        self.assertEqual(self.render()[2],'full')
        self.assertEqual(self.hw.metrics['jobs_per_core'],[0,0])
    def test_projection_failure_retries_invalid_tiles(self):
        self.render();self.change(1,25,25,3,3,(255,255,255))
        self.scheduler.fail=True
        with self.assertRaises(RuntimeError):self.render()
        self.render();self.assertGreater(sum(self.hw.metrics['jobs_per_core']),0);self.assert_full_equal()
    def test_broad_app_dirty_rect_only_reprojects_actual_changes(self):
        self.render();self.change(1,20,20,3,3,(255,255,255))
        self.windows[1].dirty_rect=(0,0,128,96)
        self.render();self.assertLess(sum(self.hw.metrics['jobs_per_core']),len(self.hw.caches[1]['ids']))
        self.assert_full_equal()
    def test_opaque_black_layer_still_occludes_cached_underlay(self):
        self.render();self.change(2,0,0,128,96,(0,0,0))
        self.render();self.assertEqual(self.hw.metrics['projected_windows'],[2]);self.assert_full_equal()
    def test_pointer_tile_caps_cover_full_scan(self):
        from geometry_reference import triangle_centers
        q=np.einsum('ic,tcd->tid',triangle_centers(32),all_tile_vertices())
        q/=np.linalg.norm(q,axis=2)[:,:,None]
        self.hw.rays=q.astype(np.float32).reshape(-1,3)
        for az,el in [(0,0),(179,20),(72,89),(-130,-70)]:
            self.hw._pointer((az,el,True))
            a,e=np.radians([az,el]);direction=np.array([np.cos(e)*np.sin(a),np.sin(e),-np.cos(e)*np.cos(a)],dtype=np.float32)
            dots=np.einsum('ij,j->i',self.hw.rays,direction)
            for indices,degrees in zip(self.hw.pointer_indices,(2.2,1.0)):
                np.testing.assert_array_equal(indices,np.flatnonzero(dots>=np.cos(np.radians(degrees))))


class Registers:
    def __init__(self): self.reg={0:0,0x44:0};self.pending=False;self.commits=0
    def write(self,offset,value):
        self.reg[offset]=value
        if offset==0x6c:self.pending=True;self.commits+=1
        if self.pending and self.reg[0]:self.reg[0x44]=self.reg[8];self.pending=False
    def read(self,offset): return self.reg.get(offset,0)


class DriverTests(unittest.TestCase):
    def setUp(self):
        d=self.driver=BosioV2.__new__(BosioV2)
        d.core=Registers();d.allocate=Buffer;d.ddr_cache=True;d.running=False;d.m=32
        d._ddr_buffers=[None,None];d._ddr_current=0;d._ddr_pending=None;d._scene_shadow=None
        def wait(predicate,timeout=3):
            state=dict(scene_pending=d.core.pending,dma_busy=d.core.pending,scene_valid=bool(d.core.read(0x44)),pose_pending=False)
            self.assertTrue(predicate(state));return state
        d._wait=wait
        self.scene=np.zeros(WORDS,dtype=np.uint32);initialize_scene(self.scene)
        d.upload_words(self.scene);d.start()
    def test_slot_activate_clear_and_mirror_with_unchanged_tiles(self):
        d=self.driver
        for tile,color in [(9,224),(0,28),(9,0),(4219,3)]:
            self.scene[HEADER+tile*256:HEADER+(tile+1)*256]=np.uint32(color*0x01010101)
            self.scene[256+tile]=tile*1024 if color else 0xffffffff
            previous=d._ddr_current
            self.assertEqual(d.upload_patch(tile_patch(self.scene,[tile])),1)
            self.assertNotEqual(previous,d._ddr_current)
            self.assertEqual(d.core.read(0x44),d._ddr_buffers[d._ddr_current].physical_address)
            for buf in d._ddr_buffers:np.testing.assert_array_equal(buf[:WORDS],self.scene)
    def test_empty_patch_does_not_commit(self):
        d=self.driver;before=d.core.commits
        d.upload_patch(np.empty(0,dtype=np.uint32))
        self.assertEqual(d.core.commits,before)
    def test_adjacent_tile_flushes_are_coalesced_on_both_buffers(self):
        ids=np.arange(10,82)
        self.scene[256+ids]=ids*1024
        self.scene[HEADER+10*256:HEADER+82*256]=0xeeeeeeee
        Buffer.flush_log=[]
        self.driver.upload_patch(tile_patch(self.scene,ids))
        self.assertEqual(len(Buffer.flush_log),4)  # metadata+payload, both buffers
        self.assertLess(sum(Buffer.flush_log),self.scene.nbytes//4)
        for buf in self.driver._ddr_buffers:np.testing.assert_array_equal(buf[:WORDS],self.scene)
    def test_malformed_second_record_cannot_partially_mutate(self):
        d=self.driver;before=d.core.commits
        packet=tile_patch(self.scene,[0,1]);packet[16+272+2]=123
        with self.assertRaises(ValueError):d.upload_patch(packet)
        self.assertEqual(d.core.commits,before)
        np.testing.assert_array_equal(d._scene_shadow,self.scene)
        for buf in d._ddr_buffers:np.testing.assert_array_equal(buf[:WORDS],self.scene)


if __name__=='__main__': unittest.main()
