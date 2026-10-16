// Decode installed XNB textures using xnb.js's LZX reader (external calibration dependency).
// node tools/extract_game_textures.js <game-dir> <ids.json> <output-dir> <lzxlib.cjs>
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const [game, manifest, output, library] = process.argv.slice(2);
const L = require(path.resolve(library));
fs.mkdirSync(output, { recursive: true });
const specification = JSON.parse(fs.readFileSync(manifest, 'utf8'));
const textures = Array.isArray(specification) ? specification : specification.materials.map(m =>
  (m.kind === 'wall' ? 'Wall_' : 'Tiles_') + m.id);
for (const name of textures) {
  const file = fs.readFileSync(path.join(game, 'Content', 'Images', name + '.xnb'));
  if (file.toString('ascii', 0, 3) !== 'XNB' || file[5] !== 0x80) throw Error('Unsupported XNB');
  const reader = new L.__BufferReader(file.buffer.slice(file.byteOffset, file.byteOffset + file.byteLength));
  reader.seek(14);
  const dec = Buffer.from(L.__Presser.decompress(reader, file.length - 14, file.readUInt32LE(10)));
  let o = 0;
  function u7() { let n=0, s=0, b; do { b=dec[o++]; n|=(b & 127)<<s; s+=7; } while (b & 128); return n; }
  const count = u7();
  for (let i=0; i<count; i++) { const n=u7(); o+=n+4; }
  if (u7() !== 0 || u7() !== 1) throw Error('Unexpected shared resources / root reader');
  const [fmt, w, h, mips, size] = Array.from({length:5}, () => { const v=dec.readUInt32LE(o); o+=4; return v; });
  if (fmt !== 0 || size !== w*h*4 || o+size>dec.length) throw Error('Expected RGBA8888');
  fs.writeFileSync(path.join(output, name+'.raw'), dec.subarray(o,o+size));
  fs.writeFileSync(path.join(output, name+'.json'), JSON.stringify({fmt,w,h,mips,size,sha256:crypto.createHash('sha256').update(file).digest('hex')}));
}
console.log('Decoded all requested game textures.');
