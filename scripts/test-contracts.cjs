const {spawnSync} = require('node:child_process');
const result = spawnSync('node_modules/.bin/forge', ['test','--root','contracts'], {encoding:'utf8'});
const output = (result.stdout || '') + (result.stderr || '');
process.stdout.write(output);
// Some npm launchers do not propagate the binary exit status. Require an explicit green summary.
if (result.error || result.status !== 0 || !/0 failed/.test(output) || /\[FAIL/.test(output)) process.exit(1);
