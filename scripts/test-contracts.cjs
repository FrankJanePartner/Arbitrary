const {spawnSync} = require('node:child_process');
const result = spawnSync(process.execPath, ['node_modules/@foundry-rs/forge/bin.mjs','test','--root','contracts'], {encoding:'utf8'});
const output = (result.stdout || '') + (result.stderr || '');
process.stdout.write(output);
if (result.error) console.error('Unable to start Forge:', result.error.message);
if (result.signal) console.error('Forge terminated by signal:', result.signal);
if (!/0 failed/.test(output)) console.error('Contract tests did not produce a passing summary. Do not continue to Python integration tests yet.');
// Some npm launchers do not propagate the binary exit status. Require an explicit green summary.
if (result.error || result.status !== 0 || !/0 failed/.test(output) || /\[FAIL/.test(output)) process.exit(1);
