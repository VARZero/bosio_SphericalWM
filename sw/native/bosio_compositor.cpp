#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <string>
#include <unordered_map>
#include <vector>

#if defined(__ARM_NEON)
#include <arm_neon.h>
#endif

namespace {
constexpr float kPi = 3.14159265358979323846f;
struct Sample { uint32_t dst; float fx,fy; uint8_t flags,aa; };
struct Window {
  float az=0, el=0, roll=0, width=0, height=0;
  uint32_t sw=0, sh=0; uint64_t surface_revision=0;
  std::vector<uint8_t> surface, surface_index; std::vector<Sample> samples;
  uint32_t dirty_x=0,dirty_y=0,dirty_w=0,dirty_h=0;
};
struct Context {
  uint32_t count=0; std::vector<float> rays;
  std::unordered_map<uint64_t,Window> windows;
  float pointer_az=9999, pointer_el=9999; bool pointer_visible=false;
  std::vector<uint32_t> pointer_outer, pointer_inner;
  std::vector<uint8_t> image; std::vector<uint64_t> owner;
  std::vector<uint32_t> directory;std::vector<uint64_t> last_order;
  uint64_t last_focus=0;float last_paz=0,last_pel=0;bool last_pvisible=false;
  uint8_t last_br=0,last_bg=0,last_bb=0;uint32_t last_m=0;
  bool packed_valid=false,structural_dirty=true;
  bool projection_aa=true;
  std::string error;
};
inline float rad(float x){return x*kPi/180.0f;}
inline uint8_t rgb_index(uint8_t r,uint8_t g,uint8_t b){return (r&224)|((g>>3)&28)|(b>>6);}
inline float clampf(float v,float lo,float hi){return std::max(lo,std::min(hi,v));}
inline void bilinear_rgb(const Window&w,float fx,float fy,float& r,float& g,float& b){
  fx=clampf(fx,0.f,(float)(w.sw-1));fy=clampf(fy,0.f,(float)(w.sh-1));
  uint32_t x0=(uint32_t)std::floor(fx),y0=(uint32_t)std::floor(fy),x1=std::min(w.sw-1,x0+1),y1=std::min(w.sh-1,y0+1);
  float ax=fx-x0,ay=fy-y0,w00=(1-ax)*(1-ay),w10=ax*(1-ay),w01=(1-ax)*ay,w11=ax*ay;
  const uint8_t*p00=&w.surface[((size_t)y0*w.sw+x0)*3],*p10=&w.surface[((size_t)y0*w.sw+x1)*3],*p01=&w.surface[((size_t)y1*w.sw+x0)*3],*p11=&w.surface[((size_t)y1*w.sw+x1)*3];
  r=p00[0]*w00+p10[0]*w10+p01[0]*w01+p11[0]*w11;g=p00[1]*w00+p10[1]*w10+p01[1]*w01+p11[1]*w11;b=p00[2]*w00+p10[2]*w10+p01[2]*w01+p11[2]*w11;
}
inline uint16_t luma(const uint8_t*p){return (uint16_t)(p[0]*3+p[1]*6+p[2]);}
inline bool high_contrast(const Window&w,float fx,float fy){
  uint32_t x0=(uint32_t)clampf(std::floor(fx),0.f,(float)(w.sw-1)),y0=(uint32_t)clampf(std::floor(fy),0.f,(float)(w.sh-1)),x1=std::min(w.sw-1,x0+1),y1=std::min(w.sh-1,y0+1);
  uint16_t lo=2295,hi=0;const uint32_t ids[4]={y0*w.sw+x0,y0*w.sw+x1,y1*w.sw+x0,y1*w.sw+x1};for(auto id:ids){uint16_t v=luma(&w.surface[(size_t)id*3]);lo=std::min(lo,v);hi=std::max(hi,v);}return hi-lo>=216;
}
inline void sample_rgb(const Window&w,const Sample&s,uint8_t& r,uint8_t& g,uint8_t& b){
  if(!s.aa){long x=std::lround(s.fx),y=std::lround(s.fy);x=std::max(0l,std::min((long)w.sw-1,x));y=std::max(0l,std::min((long)w.sh-1,y));const uint8_t*p=&w.surface[((size_t)y*w.sw+x)*3];r=p[0];g=p[1];b=p[2];return;}
  float rr=0,gg=0,bb=0;if(!high_contrast(w,s.fx,s.fy)){bilinear_rgb(w,s.fx,s.fy,rr,gg,bb);}else{constexpr float o[4]={-.375f,-.125f,.125f,.375f};for(float oy:o)for(float ox:o){float tr,tg,tb;bilinear_rgb(w,s.fx+ox,s.fy+oy,tr,tg,tb);rr+=tr;gg+=tg;bb+=tb;}rr*=.0625f;gg*=.0625f;bb*=.0625f;}r=(uint8_t)clampf(std::round(rr),0.f,255.f);g=(uint8_t)clampf(std::round(gg),0.f,255.f);b=(uint8_t)clampf(std::round(bb),0.f,255.f);
}
inline uint8_t sample_index(const Window&w,const Sample&s){uint8_t r,g,b;sample_rgb(w,s,r,g,b);return rgb_index(r,g,b);}
inline bool sample_hits_dirty(const Window&w,const Sample&s,uint32_t x1,uint32_t y1){
  float radius=s.aa?.375f:0.f;int sx0=(int)std::floor(s.fx-radius),sy0=(int)std::floor(s.fy-radius),sx1=(int)std::floor(s.fx+radius)+1,sy1=(int)std::floor(s.fy+radius)+1;
  sx0=std::max(0,sx0);sy0=std::max(0,sy0);sx1=std::min((int)w.sw-1,sx1);sy1=std::min((int)w.sh-1,sy1);return sx1>=(int)w.dirty_x&&sx0<(int)x1&&sy1>=(int)w.dirty_y&&sy0<(int)y1;
}
void convert_surface(Window&w){
  size_t pixels=(size_t)w.sw*w.sh;w.surface_index.resize(pixels);size_t i=0;
#if defined(__ARM_NEON)
  for(;i+16<=pixels;i+=16){uint8x16x3_t p=vld3q_u8(w.surface.data()+i*3);uint8x16_t idx=vorrq_u8(vorrq_u8(vandq_u8(p.val[0],vdupq_n_u8(224)),vandq_u8(vshrq_n_u8(p.val[1],3),vdupq_n_u8(28))),vshrq_n_u8(p.val[2],6));vst1q_u8(w.surface_index.data()+i,idx);}
#endif
  for(;i<pixels;i++)w.surface_index[i]=rgb_index(w.surface[i*3],w.surface[i*3+1],w.surface[i*3+2]);
}
void convert_surface_rect(Window&w,const uint8_t*rgb,uint32_t x,uint32_t y,uint32_t width,uint32_t height){
  if(!width||!height)return;
  uint32_t x1=std::min(w.sw,x+width),y1=std::min(w.sh,y+height);
  for(uint32_t py=y;py<y1;py++)for(uint32_t px=x;px<x1;px++){
    size_t p=(size_t)py*w.sw+px;
    w.surface[p*3]=rgb[p*3];w.surface[p*3+1]=rgb[p*3+1];w.surface[p*3+2]=rgb[p*3+2];
    w.surface_index[p]=rgb_index(rgb[p*3],rgb[p*3+1],rgb[p*3+2]);
  }
}
void add_dirty(Window&w,uint32_t x,uint32_t y,uint32_t width,uint32_t height){
  if(!width||!height)return;
  if(!w.dirty_w){w.dirty_x=x;w.dirty_y=y;w.dirty_w=width;w.dirty_h=height;return;}
  uint32_t x0=std::min(w.dirty_x,x),y0=std::min(w.dirty_y,y);
  uint32_t x1=std::max(w.dirty_x+w.dirty_w,x+width),y1=std::max(w.dirty_y+w.dirty_h,y+height);
  w.dirty_x=x0;w.dirty_y=y0;w.dirty_w=x1-x0;w.dirty_h=y1-y0;
}
void basis(float azd,float eld,float rolld,float*c,float*r,float*u){
  float az=rad(azd),el=rad(eld),rl=rad(rolld);
  c[0]=std::cos(el)*std::sin(az);c[1]=std::sin(el);c[2]=-std::cos(el)*std::cos(az);
  float r0[3]={std::cos(az),0,std::sin(az)};
  float u0[3]={r0[1]*c[2]-r0[2]*c[1],r0[2]*c[0]-r0[0]*c[2],r0[0]*c[1]-r0[1]*c[0]};
  for(int i=0;i<3;i++){r[i]=r0[i]*std::cos(rl)+u0[i]*std::sin(rl);u[i]=u0[i]*std::cos(rl)-r0[i]*std::sin(rl);}
}
bool same_geometry(const Window&w,float az,float el,float roll,float width,float height,uint32_t sw,uint32_t sh){
  return w.az==az&&w.el==el&&w.roll==roll&&w.width==width&&w.height==height&&w.sw==sw&&w.sh==sh;
}
void rebuild(Context&ctx,Window&w){
  float c[3],r[3],u[3];basis(w.az,w.el,w.roll,c,r,u);
  float tx=std::tan(rad(w.width*.5f)),ty=std::tan(rad(w.height*.5f));
  w.samples.clear();w.samples.reserve(ctx.count/12);
#if defined(__ARM_NEON)
  float32x4_t cx=vdupq_n_f32(c[0]),cy=vdupq_n_f32(c[1]),cz=vdupq_n_f32(c[2]);
  float32x4_t rx=vdupq_n_f32(r[0]),ry=vdupq_n_f32(r[1]),rz=vdupq_n_f32(r[2]);
  float32x4_t ux=vdupq_n_f32(u[0]),uy=vdupq_n_f32(u[1]),uz=vdupq_n_f32(u[2]);
  alignas(16) float ds[4],xs[4],ys[4]; uint32_t i=0;
  for(;i+4<=ctx.count;i+=4){
    float32x4x3_t q=vld3q_f32(&ctx.rays[i*3]);
    float32x4_t d=vmlaq_f32(vmlaq_f32(vmulq_f32(q.val[0],cx),q.val[1],cy),q.val[2],cz);
    float32x4_t nx=vmlaq_f32(vmlaq_f32(vmulq_f32(q.val[0],rx),q.val[1],ry),q.val[2],rz);
    float32x4_t ny=vmlaq_f32(vmlaq_f32(vmulq_f32(q.val[0],ux),q.val[1],uy),q.val[2],uz);
    float32x4_t recip=vrecpeq_f32(d);recip=vmulq_f32(vrecpsq_f32(d,recip),recip);recip=vmulq_f32(vrecpsq_f32(d,recip),recip);
    vst1q_f32(ds,d);vst1q_f32(xs,vmulq_n_f32(vmulq_f32(nx,recip),1.0f/tx));vst1q_f32(ys,vmulq_n_f32(vmulq_f32(ny,recip),1.0f/ty));
    for(int lane=0;lane<4;lane++)if(ds[lane]>0&&std::fabs(xs[lane])<=1&&std::fabs(ys[lane])<=1){
      float fx=(xs[lane]+1.f)*.5f*(w.sw-1),fy=(1.f-ys[lane])*.5f*(w.sh-1);
      uint8_t f=(ys[lane]>.72f?1:0)|((std::fabs(xs[lane])>.94f||std::fabs(ys[lane])>.92f)?2:0);
      w.samples.push_back({i+(uint32_t)lane,fx,fy,f,(uint8_t)ctx.projection_aa});
    }
  }
#else
  uint32_t i=0;
#endif
  for(;i<ctx.count;i++){
    const float*q=&ctx.rays[i*3];float d=q[0]*c[0]+q[1]*c[1]+q[2]*c[2];if(d<=0)continue;
    float x=(q[0]*r[0]+q[1]*r[1]+q[2]*r[2])/d/tx,y=(q[0]*u[0]+q[1]*u[1]+q[2]*u[2])/d/ty;
    if(std::fabs(x)>1||std::fabs(y)>1)continue;
    float fx=(x+1.f)*.5f*(w.sw-1),fy=(1.f-y)*.5f*(w.sh-1);uint8_t f=(y>.72f?1:0)|((std::fabs(x)>.94f||std::fabs(y)>.92f)?2:0);w.samples.push_back({i,fx,fy,f,(uint8_t)ctx.projection_aa});
  }
}
void rebuild_pointer(Context&ctx,float az,float el,bool visible){
  if(ctx.pointer_az==az&&ctx.pointer_el==el&&ctx.pointer_visible==visible)return;
  ctx.pointer_az=az;ctx.pointer_el=el;ctx.pointer_visible=visible;ctx.pointer_outer.clear();ctx.pointer_inner.clear();if(!visible)return;
  float c[3],r[3],u[3];basis(az,el,0,c,r,u);float co=std::cos(rad(2.2f)),ci=std::cos(rad(1.0f));
  uint32_t i=0;
#if defined(__ARM_NEON)
  float32x4_t cx=vdupq_n_f32(c[0]),cy=vdupq_n_f32(c[1]),cz=vdupq_n_f32(c[2]);alignas(16) float ds[4];
  for(;i+4<=ctx.count;i+=4){float32x4x3_t q=vld3q_f32(&ctx.rays[i*3]);float32x4_t d=vmlaq_f32(vmlaq_f32(vmulq_f32(q.val[0],cx),q.val[1],cy),q.val[2],cz);vst1q_f32(ds,d);for(int lane=0;lane<4;lane++){if(ds[lane]>=co)ctx.pointer_outer.push_back(i+lane);if(ds[lane]>=ci)ctx.pointer_inner.push_back(i+lane);}}
#endif
  for(;i<ctx.count;i++){const float*q=&ctx.rays[i*3];float d=q[0]*c[0]+q[1]*c[1]+q[2]*c[2];if(d>=co)ctx.pointer_outer.push_back(i);if(d>=ci)ctx.pointer_inner.push_back(i);}
}
}

extern "C" {
int bosio_compositor_render_packed(void*ptr,const uint64_t*order,uint32_t order_count,uint64_t focus,float paz,float pel,int pvisible,uint8_t br,uint8_t bg,uint8_t bb,uint32_t m,uint32_t*out,uint32_t capacity,uint32_t*active_out){
  try{
    auto&ctx=*static_cast<Context*>(ptr);const uint32_t tiles=20*211,cells=m*m,prefix=256+tiles,max_bytes=196608;if(ctx.count!=tiles*cells||capacity<prefix+16)return -1;
    ctx.image.assign(ctx.count,rgb_index(br,bg,bb));ctx.owner.assign(ctx.count,0);
    const uint8_t tf=rgb_index(22,112,190),ti=rgb_index(55,65,81),bf=rgb_index(250,204,21),bi=rgb_index(120,130,145);
    for(uint32_t z=0;z<order_count;z++){auto it=ctx.windows.find(order[z]);if(it==ctx.windows.end())continue;const auto&w=it->second;bool focused=order[z]==focus;for(const auto&s:w.samples){uint8_t value=sample_index(w,s);if(s.flags&1)value=focused?tf:ti;if(s.flags&2)value=focused?bf:bi;ctx.image[s.dst]=value;ctx.owner[s.dst]=s.flags?UINT64_MAX:order[z];}}
    rebuild_pointer(ctx,paz,pel,pvisible!=0);for(auto i:ctx.pointer_outer){ctx.image[i]=rgb_index(10,10,10);ctx.owner[i]=UINT64_MAX;}for(auto i:ctx.pointer_inner){ctx.image[i]=rgb_index(255,255,255);ctx.owner[i]=UINT64_MAX;}
    for(uint32_t k=0;k<256;k++){uint32_t red=(k>>5)*255/7,green=((k>>2)&7)*255/7,blue=(k&3)*255/3;out[k]=(red<<16)|(blue<<8)|green;}
    std::fill(out+256,out+prefix,0xffffffffu);ctx.directory.assign(tiles,0xffffffffu);uint8_t*data=reinterpret_cast<uint8_t*>(out+prefix);uint32_t active=0,bytes=0;
    for(uint32_t tile=0;tile<tiles;tile++){const uint8_t*src=ctx.image.data()+(size_t)tile*cells;bool used=false;for(uint32_t j=0;j<cells;j++)used|=src[j]!=0;if(!used)continue;if(bytes+cells>max_bytes)return -2;out[256+tile]=bytes;ctx.directory[tile]=bytes;std::memcpy(data+bytes,src,cells);bytes+=cells;active++;}
    uint32_t padded=(bytes+63u)&~63u,words=(prefix+padded/4+15u)&~15u;if(words>capacity)return -1;std::memset(data+bytes,0,(size_t)(words-prefix)*4-bytes);
    ctx.last_order.assign(order,order+order_count);ctx.last_focus=focus;ctx.last_paz=paz;ctx.last_pel=pel;ctx.last_pvisible=pvisible!=0;ctx.last_br=br;ctx.last_bg=bg;ctx.last_bb=bb;ctx.last_m=m;ctx.packed_valid=true;ctx.structural_dirty=false;
    for(auto&kv:ctx.windows)kv.second.dirty_w=kv.second.dirty_h=0;
    if(active_out)*active_out=active;return (int)words;
  }catch(const std::exception&e){static_cast<Context*>(ptr)->error=e.what();return -1;}
}
// Returns a BPT1 partial-scene packet, 0 if quantized output did not change,
// or -3 when topology/chrome changes require a full immutable snapshot.
int bosio_compositor_render_patch(void*ptr,const uint64_t*order,uint32_t order_count,uint64_t focus,float paz,float pel,int pvisible,uint8_t br,uint8_t bg,uint8_t bb,uint32_t m,uint32_t*out,uint32_t capacity,uint32_t*tile_count_out){
 try{
  auto&ctx=*static_cast<Context*>(ptr);const uint32_t tiles=20*211,cells=m*m,tile_words=cells/4;
  bool same=ctx.packed_valid&&!ctx.structural_dirty&&ctx.last_m==m&&ctx.last_focus==focus&&ctx.last_paz==paz&&ctx.last_pel==pel&&ctx.last_pvisible==(pvisible!=0)&&ctx.last_br==br&&ctx.last_bg==bg&&ctx.last_bb==bb&&ctx.last_order.size()==order_count;
  for(uint32_t i=0;same&&i<order_count;i++)same=ctx.last_order[i]==order[i];if(!same)return -3;
  std::vector<uint8_t> dirty(tiles,0);
  for(auto&kv:ctx.windows){uint64_t id=kv.first;Window&w=kv.second;if(!w.dirty_w)continue;
   uint32_t x1=w.dirty_x+w.dirty_w,y1=w.dirty_y+w.dirty_h;
   for(const auto&s:w.samples){if(!sample_hits_dirty(w,s,x1,y1)||s.flags||ctx.owner[s.dst]!=id)continue;uint8_t value=sample_index(w,s);if(ctx.image[s.dst]!=value){ctx.image[s.dst]=value;dirty[s.dst/cells]=1;}}
   w.dirty_w=w.dirty_h=0;
  }
  uint32_t records=0;for(uint32_t t=0;t<tiles;t++)if(dirty[t]){if(ctx.directory[t]==0xffffffffu||(ctx.directory[t]&3u))return -3;records++;}
  if(!records){if(tile_count_out)*tile_count_out=0;return 0;}
  uint32_t words=16+records*(16+tile_words);if(words>capacity)return -3;std::fill(out,out+words,0);out[0]=0x42505431;out[1]=tile_words;out[2]=records;out[3]=words;
  uint32_t cursor=16;for(uint32_t t=0;t<tiles;t++)if(dirty[t]){out[cursor]=ctx.directory[t]/4;out[cursor+1]=t;cursor+=16;std::memcpy(out+cursor,ctx.image.data()+(size_t)t*cells,cells);cursor+=tile_words;}
  if(tile_count_out)*tile_count_out=records;return (int)words;
 }catch(const std::exception&e){static_cast<Context*>(ptr)->error=e.what();return -1;}
}
int bosio_pack_scene(const uint8_t*rgb,uint32_t m,uint32_t*out,uint32_t capacity,uint32_t*active_out){
  const uint32_t tiles=20*211,cells=m*m,prefix=256+tiles,max_bytes=196608;
  if((m!=8&&m!=16&&m!=32)||capacity<prefix+16)return -1;
  for(uint32_t k=0;k<256;k++){uint32_t red=(k>>5)*255/7,green=((k>>2)&7)*255/7,blue=(k&3)*255/3;out[k]=(red<<16)|(blue<<8)|green;}
  std::fill(out+256,out+prefix,0xffffffffu);uint8_t*data=reinterpret_cast<uint8_t*>(out+prefix);uint32_t active=0,bytes=0;
  std::vector<uint8_t> converted(cells);
  for(uint32_t tile=0;tile<tiles;tile++){
    const uint8_t*src=rgb+(size_t)tile*cells*3;bool used=false;uint32_t j=0;
#if defined(__ARM_NEON)
    alignas(16) uint8_t lane[16];
    for(;j+16<=cells;j+=16){uint8x16x3_t p=vld3q_u8(src+(size_t)j*3);uint8x16_t idx=vorrq_u8(vorrq_u8(vandq_u8(p.val[0],vdupq_n_u8(224)),vandq_u8(vshrq_n_u8(p.val[1],3),vdupq_n_u8(28))),vshrq_n_u8(p.val[2],6));vst1q_u8(converted.data()+j,idx);vst1q_u8(lane,idx);for(int n=0;n<16;n++)used|=lane[n]!=0;}
#endif
    for(;j<cells;j++){uint8_t idx=(src[j*3]&224)|((src[j*3+1]>>3)&28)|(src[j*3+2]>>6);converted[j]=idx;used|=idx!=0;}
    if(!used)continue;if(bytes+cells>max_bytes)return -2;out[256+tile]=bytes;std::memcpy(data+bytes,converted.data(),cells);bytes+=cells;active++;
  }
  uint32_t padded_bytes=(bytes+63u)&~63u;uint32_t words=prefix+padded_bytes/4;words=(words+15u)&~15u;if(words>capacity)return -1;
  std::memset(data+bytes,0,(size_t)(words-prefix)*4-bytes);if(active_out)*active_out=active;return (int)words;
}
void* bosio_compositor_create(const float*rays,uint32_t count){try{auto*c=new Context;c->count=count;c->rays.assign(rays,rays+(size_t)count*3);return c;}catch(...){return nullptr;}}
void bosio_compositor_set_projection_aa(void*ptr,int enabled){auto&ctx=*static_cast<Context*>(ptr);bool v=enabled!=0;if(ctx.projection_aa==v)return;ctx.projection_aa=v;for(auto&kv:ctx.windows)rebuild(ctx,kv.second);ctx.structural_dirty=true;ctx.packed_valid=false;}
void bosio_compositor_destroy(void*ptr){delete static_cast<Context*>(ptr);}
int bosio_compositor_sync_window(void*ptr,uint64_t id,float az,float el,float roll,float width,float height,uint32_t sw,uint32_t sh,uint64_t revision,const uint8_t*rgb){
  try{auto&ctx=*static_cast<Context*>(ptr);auto&w=ctx.windows[id];bool changed=!same_geometry(w,az,el,roll,width,height,sw,sh);w.az=az;w.el=el;w.roll=roll;w.width=width;w.height=height;w.sw=sw;w.sh=sh;if(changed){rebuild(ctx,w);ctx.structural_dirty=true;}if(w.surface_revision!=revision||w.surface.empty()){w.surface.assign(rgb,rgb+(size_t)sw*sh*3);convert_surface(w);add_dirty(w,0,0,sw,sh);w.surface_revision=revision;}return 0;}catch(const std::exception&e){static_cast<Context*>(ptr)->error=e.what();return -1;}}
int bosio_compositor_sync_window_dirty(void*ptr,uint64_t id,float az,float el,float roll,float width,float height,uint32_t sw,uint32_t sh,uint64_t revision,const uint8_t*rgb,uint32_t dx,uint32_t dy,uint32_t dw,uint32_t dh){
 try{auto&ctx=*static_cast<Context*>(ptr);auto&w=ctx.windows[id];bool changed=!same_geometry(w,az,el,roll,width,height,sw,sh);w.az=az;w.el=el;w.roll=roll;w.width=width;w.height=height;w.sw=sw;w.sh=sh;
  if(changed||w.surface.empty()||w.surface.size()!=(size_t)sw*sh*3){rebuild(ctx,w);w.surface.assign(rgb,rgb+(size_t)sw*sh*3);convert_surface(w);add_dirty(w,0,0,sw,sh);ctx.structural_dirty=true;}
  else if(w.surface_revision!=revision){if(dx>=sw||dy>=sh||!dw||!dh){dx=0;dy=0;dw=sw;dh=sh;}convert_surface_rect(w,rgb,dx,dy,dw,dh);add_dirty(w,dx,dy,std::min(dw,sw-dx),std::min(dh,sh-dy));}
  w.surface_revision=revision;return 0;
 }catch(const std::exception&e){static_cast<Context*>(ptr)->error=e.what();return -1;}}
void bosio_compositor_remove_window(void*ptr,uint64_t id){auto&ctx=*static_cast<Context*>(ptr);ctx.windows.erase(id);ctx.structural_dirty=true;}
int bosio_compositor_render(void*ptr,const uint64_t*order,uint32_t order_count,uint64_t focus,float paz,float pel,int pvisible,uint8_t br,uint8_t bg,uint8_t bb,uint8_t*out){
  try{auto&ctx=*static_cast<Context*>(ptr);for(uint32_t i=0;i<ctx.count;i++){out[i*3]=br;out[i*3+1]=bg;out[i*3+2]=bb;}
    for(uint32_t z=0;z<order_count;z++){auto it=ctx.windows.find(order[z]);if(it==ctx.windows.end())continue;const auto&w=it->second;for(const auto&s:w.samples){uint8_t*d=&out[(size_t)s.dst*3];sample_rgb(w,s,d[0],d[1],d[2]);if(s.flags&1){bool f=order[z]==focus;d[0]=f?22:55;d[1]=f?112:65;d[2]=f?190:81;}if(s.flags&2){bool f=order[z]==focus;d[0]=f?250:120;d[1]=f?204:130;d[2]=f?21:145;}}}
    rebuild_pointer(ctx,paz,pel,pvisible!=0);for(auto i:ctx.pointer_outer){out[i*3]=10;out[i*3+1]=10;out[i*3+2]=10;}for(auto i:ctx.pointer_inner){out[i*3]=255;out[i*3+1]=255;out[i*3+2]=255;}return 0;
  }catch(const std::exception&e){static_cast<Context*>(ptr)->error=e.what();return -1;}}
const char* bosio_compositor_error(void*ptr){return static_cast<Context*>(ptr)->error.c_str();}
}

