const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ deviceScaleFactor: 1 });
  const plan = [[256,'large'],[128,'large'],[64,'large'],[48,'medium'],[32,'medium'],[24,'small'],[20,'small'],[16,'small']];
  for (const [n, lv] of plan) {
    const svg = fs.readFileSync(`datapiler-${lv}.svg`, 'utf8').replace('width="256" height="256"', `width="${n}" height="${n}"`);
    await p.setViewportSize({ width: n, height: n });
    await p.setContent(`<html><body style="margin:0;background:transparent">${svg}</body></html>`);
    await p.screenshot({ path: `png/${n}.png`, omitBackground: true, clip: { x: 0, y: 0, width: n, height: n } });
  }
  await b.close();
  console.log('rendered');
})();
