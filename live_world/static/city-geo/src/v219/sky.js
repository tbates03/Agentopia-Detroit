import * as T from 'three/webgpu';
// Sovereign, original procedural sky / environment map: no external HDRI or image service.
export function createSky(mode='golden'){
 const c=document.createElement('canvas');c.width=1024;c.height=512;
 const g=c.getContext('2d');const scheme={
 golden:['#526d86','#879da9','#eec5a0','#e6a66b','#667579'],
 day:['#416a99','#75a7c6','#c0d5d8','#d9d8bd','#668da0'],
 night:['#080f26','#192945','#4e617e','#996f63','#213345']
 }[mode]||['#526d86','#879da9','#eec5a0','#e6a66b','#667579'];
 const bg=g.createLinearGradient(0,0,0,512);for(const [i,color] of scheme.entries())bg.addColorStop(i/4,color);
 g.fillStyle=bg;g.fillRect(0,0,1024,512);
 if(mode!=='night'){
  const sx=222,sy=258;const glow=g.createRadialGradient(sx,sy,4,sx,sy,180);
  glow.addColorStop(0,'rgba(255,245,214,.99)');glow.addColorStop(.05,'rgba(255,238,193,.96)');glow.addColorStop(.20,'rgba(255,216,162,.32)');glow.addColorStop(1,'rgba(255,206,152,0)');g.fillStyle=glow;g.fillRect(0,0,1024,512);
 }else {for(let i=0;i<400;i++){const x=(i*173+39)%1024,y=(i*97+12)%300;g.fillStyle='rgba(220,235,247,.48)';g.fillRect(x,y,1,1);}}
 const out=new T.CanvasTexture(c);out.mapping=T.EquirectangularReflectionMapping;out.colorSpace=T.SRGBColorSpace;out.needsUpdate=true;return out;
}
