import * as T from 'three/webgpu';
import {seeded} from './geography.js';
const localCanvas=(size=512)=>{const c=document.createElement('canvas');c.width=c.height=size;return [c,c.getContext('2d')];};
function tex(canvas,rx=1,ry=1){const t=new T.CanvasTexture(canvas);t.wrapS=t.wrapT=T.RepeatWrapping;t.repeat.set(rx,ry);t.colorSpace=T.SRGBColorSpace;t.anisotropy=8;return t;}
function brickTex(){const [c,ctx]=localCanvas(512);const rng=seeded(32);ctx.fillStyle='#ae8d77';ctx.fillRect(0,0,512,512);for(let row=0;row<25;row++){const y=row*21;for(let col=-1;col<16;col++){const x=col*36+(row%2)*18;let b=100+rng()*45;ctx.fillStyle=`rgb(${Math.round(b+35)},${Math.round(b+16)},${Math.round(b)})`;ctx.fillRect(x+1,y+1,34,19);ctx.fillStyle='rgba(255,255,255,.07)';ctx.fillRect(x+2,y+2,32,2);}}return tex(c);}
function stoneTex(){const [c,ctx]=localCanvas(512);const r=seeded(88);ctx.fillStyle='#c9beb0';ctx.fillRect(0,0,512,512);for(let i=0;i<3200;i++){const a=Math.round(r()*55+148);ctx.fillStyle=`rgba(${a},${a-7},${a-17},${r()*.18})`;ctx.fillRect(r()*512,r()*512,2+r()*13,1+r()*4);}return tex(c);}
function glassTex(){const [c,ctx]=localCanvas(512);ctx.fillStyle='#54768a';ctx.fillRect(0,0,512,512);for(let i=0;i<20;i++){ctx.fillStyle=i%3===0?'#7996a4':'#39576b';ctx.fillRect(i*27,0,16,512);ctx.fillStyle='rgba(230,239,242,.34)';ctx.fillRect(i*27+17,0,2,512);}for(let y=0;y<512;y+=44){ctx.fillStyle='rgba(232,239,234,.42)';ctx.fillRect(0,y,512,3);}return tex(c);}
function asphaltTex(){const [c,ctx]=localCanvas(512),r=seeded(5);ctx.fillStyle='#414748';ctx.fillRect(0,0,512,512);for(let i=0;i<24000;i++){const g=70+Math.round(r()*65);ctx.fillStyle=`rgba(${g},${g},${g},.25)`;ctx.fillRect(r()*512,r()*512,1+r()*2,1+r()*2)}return tex(c);}
export function createMaterials(){const brick=brickTex(),stone=stoneTex(),glass=glassTex(),asphalt=asphaltTex();return {
 brick:new T.MeshStandardMaterial({map:brick,roughness:.88,color:0xf0d3b5}),
 redbrick:new T.MeshStandardMaterial({map:brick,roughness:.91,color:0xb77c6a}),
 stone:new T.MeshStandardMaterial({map:stone,roughness:.8,color:0xefeadc}),
 concrete:new T.MeshStandardMaterial({map:stone,roughness:.82,color:0xa2a7a2}),
 glass:new T.MeshPhysicalMaterial({map:glass,metalness:.58,roughness:.22,clearcoat:.85,clearcoatRoughness:.12,color:0x9db6c0}),
 blueglass:new T.MeshPhysicalMaterial({map:glass,metalness:.65,roughness:.15,clearcoat:.9,color:0x89b6d0}),
 darkglass:new T.MeshPhysicalMaterial({color:0x1e3b4b,metalness:.5,roughness:.14,clearcoat:.8}),
 windows:new T.MeshPhysicalMaterial({color:0x4d7184,metalness:.65,roughness:.17,clearcoat:.8,side:T.DoubleSide}),
 nightwindow:new T.MeshStandardMaterial({color:0xffd6a1,emissive:0xffb35c,emissiveIntensity:1.5,roughness:.6,side:T.DoubleSide}),
 asphalt:new T.MeshStandardMaterial({map:asphalt,color:0x8e9494,roughness:1}),
 roadmark:new T.MeshStandardMaterial({color:0xe9e8d5,roughness:1}),
 sidewalk:new T.MeshStandardMaterial({map:stone,color:0xc4c4be,roughness:1}),
 grass:new T.MeshStandardMaterial({color:0x526b4c,roughness:1}),
 parks:new T.MeshStandardMaterial({color:0x66865b,roughness:1}),
 steel:new T.MeshStandardMaterial({color:0x87959a,metalness:.74,roughness:.4}),
 steelDark:new T.MeshStandardMaterial({color:0x2d454e,metalness:.6,roughness:.42}),
 copper:new T.MeshStandardMaterial({color:0x8f755c,metalness:.48,roughness:.43}),
 gold:new T.MeshStandardMaterial({color:0xc6a06e,metalness:.68,roughness:.33}),
 water:new T.MeshPhysicalMaterial({color:0x136187,metalness:.22,roughness:.18,clearcoat:1,clearcoatRoughness:.07,side:T.DoubleSide,transparent:false,depthWrite:true}),
 tree:new T.MeshStandardMaterial({color:0x496d48,roughness:1}),
 tree2:new T.MeshStandardMaterial({color:0x759260,roughness:1}),
 trunk:new T.MeshStandardMaterial({color:0x6f5948,roughness:1}),
 glow:new T.MeshStandardMaterial({color:0x56c1e7,emissive:0x319bc4,emissiveIntensity:1.4,metalness:.4}),
 }};
