const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../src/www/wifiap.html'), 'utf8');
const script = html.split('<script>')[1].split('</script>')[0];

(async () => {
    const table = { innerHTML: 'Scanning...' };
    const requests = [], timers = [];
    const responses = [202, 202, 200];
    const context = {
        document: { getElementById: id => { assert.equal(id, 'wifinets'); return table; } },
        console: { error: () => {} },
        fetch: async (url, options) => {
            requests.push([url, options?.method]);
            const status = url === 'rescan' ? 202 : responses.shift();
            return { status, ok: true, text: async () => '<tr>fresh scan</tr>' };
        },
        setTimeout: (callback, milliseconds) => { assert.equal(milliseconds, 500); timers.push(callback); }
    };
    vm.createContext(context);
    vm.runInContext(script, context);
    await new Promise(setImmediate);
    assert.equal(table.innerHTML, 'Scanning...');
    assert.equal(timers.length, 1);
    await timers.shift()();
    assert.equal(table.innerHTML, 'Scanning...');
    await timers.shift()();
    assert.equal(table.innerHTML, '<tr>fresh scan</tr>');
    assert.equal(requests.filter(([url]) => url === 'rescan').length, 1);
    assert.equal(requests.filter(([url]) => url === 'wifinets').length, 3);
    assert.equal(timers.length, 0);
    context.fetch = async () => ({status: 503, ok: false, text: async () => 'scan failed'});
    await context.loadNetworks();
    assert.match(table.innerHTML, /Scan failed/);
    assert.match(table.innerHTML, /name='userSSID'/);
    assert.equal(timers.length, 0);
    console.log('WiFi page waits for completed scan and stops polling after failure');
})().catch(error => { console.error(error); process.exitCode = 1; });
