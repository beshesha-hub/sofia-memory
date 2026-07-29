// Test which SearXNG instances are working
const https = require('https');
const http = require('http');

const instances = [
  'https://search.sapti.me',
  'https://searx.tiekoetter.com',
  'https://search.bus-hit.me',
  'https://searx.be',
  'https://search.ononoki.org',
  'https://searx.oxen.ai',
  'https://priv.au',
  'https://searx.work',
  'https://search.hbubli.cc',
  'https://searx.daetalytica.io',
  'https://search.mdosch.de',
  'https://searx.dresden.network',
];

const query = encodeURIComponent('distance Tainan Taiwan to Los Angeles');

async function testInstance(instance) {
  const url = `${instance}/search?q=${query}&format=json&language=en-US`;
  return new Promise((resolve) => {
    const start = Date.now();
    const mod = instance.startsWith('https') ? https : http;
    const req = mod.get(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
        'Accept': 'application/json'
      }
    }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        const elapsed = Date.now() - start;
        if (res.statusCode !== 200) {
          resolve({ instance, status: 'FAIL', reason: `HTTP ${res.statusCode}`, elapsed });
          return;
        }
        try {
          const json = JSON.parse(data);
          const count = json.results ? json.results.length : 0;
          if (count > 0) {
            resolve({ instance, status: 'OK', results: count, elapsed, sample: json.results[0].title });
          } else {
            resolve({ instance, status: 'EMPTY', results: 0, elapsed });
          }
        } catch {
          resolve({ instance, status: 'FAIL', reason: 'Invalid JSON', elapsed });
        }
      });
    });
    req.on('error', (e) => {
      resolve({ instance, status: 'FAIL', reason: e.message, elapsed: Date.now() - start });
    });
    req.setTimeout(15000, () => {
      req.destroy();
      resolve({ instance, status: 'FAIL', reason: 'Timeout', elapsed: 15000 });
    });
  });
}

async function main() {
  console.log('Testing SearXNG instances...\n');

  for (const instance of instances) {
    const result = await testInstance(instance);
    const icon = result.status === 'OK' ? '✅' : result.status === 'EMPTY' ? '⚠️' : '❌';
    const detail = result.status === 'OK'
      ? `${result.results} results in ${result.elapsed}ms — "${result.sample}"`
      : result.status === 'EMPTY'
        ? `No results (${result.elapsed}ms)`
        : `${result.reason} (${result.elapsed}ms)`;
    console.log(`${icon} ${instance}`);
    console.log(`   ${detail}\n`);

    // Small delay between tests to be polite
    await new Promise(r => setTimeout(r, 1000));
  }

  console.log('Done. Use the ✅ instances in the SEARXNG_INSTANCES array.');
}

main();
