import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

import QRCode from 'qrcode';

const [urlValue, outputValue] = process.argv.slice(2);
if (!urlValue || !outputValue) {
  throw new Error('Usage: node generate-url-qr.mjs <https-url> <output.png>');
}

const url = new URL(urlValue);
if (url.protocol !== 'https:' || url.username || url.password || urlValue.length > 2048) {
  throw new Error('Only credential-free HTTPS URLs can be encoded');
}

const output = path.resolve(outputValue);
await fs.mkdir(path.dirname(output), { recursive: true });
await QRCode.toFile(output, url.toString(), {
  type: 'png',
  width: 512,
  margin: 2,
  errorCorrectionLevel: 'M',
  color: { dark: '#03131dff', light: '#f5fdffff' },
});

process.stdout.write(`${output}\n`);
