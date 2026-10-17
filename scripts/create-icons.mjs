import fs from 'node:fs';
import { Resvg } from '@resvg/resvg-js';
const svg = fs.readFileSync('public/saturn.svg', 'utf8');
fs.mkdirSync('assets', { recursive: true });
const frames = [];
for (const size of [16, 24, 32, 48, 64, 128, 256, 512]) {
  const png = new Resvg(svg, { fitTo: { mode: 'width', value: size } }).render().asPng();
  if (size >= 256) fs.writeFileSync(`assets/saturn-${size}.png`, png);
  if (size <= 256) frames.push({ size, png });
  if (size === 256) {
    fs.writeFileSync('public/saturn-icon.png', png);
  }
}
const header = Buffer.alloc(6 + frames.length * 16);
header.writeUInt16LE(1, 2); header.writeUInt16LE(frames.length, 4);
let offset = header.length;
frames.forEach(({ size, png }, index) => {
  const entry = 6 + index * 16;
  header[entry] = header[entry + 1] = size === 256 ? 0 : size;
  header.writeUInt16LE(1, entry + 4); header.writeUInt16LE(32, entry + 6);
  header.writeUInt32LE(png.length, entry + 8); header.writeUInt32LE(offset, entry + 12);
  offset += png.length;
});
const ico = Buffer.concat([header, ...frames.map(frame => frame.png)]);
fs.writeFileSync('assets/saturn.ico', ico);
// A distinct filename also refreshes Windows shortcut icon caches.
fs.writeFileSync('assets/saturn-stars.ico', ico);
for (const [source, destination] of [['public/saturn.svg', 'public/slime.svg'], ['public/saturn-icon.png', 'public/slime-icon.png'], ['assets/saturn.ico', 'assets/slime.ico'], ['assets/saturn-256.png', 'assets/slime-256.png'], ['assets/saturn-512.png', 'assets/slime-512.png']]) fs.copyFileSync(source, destination);
console.log('Saturn PNG / ICO generated from original SVG.');
