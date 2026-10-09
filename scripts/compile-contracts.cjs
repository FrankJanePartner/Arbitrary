const fs=require('fs'),path=require('path'),solc=require('solc');
const sources={};
function walk(dir){for(const f of fs.readdirSync(dir)){const p=path.join(dir,f);if(fs.statSync(p).isDirectory())walk(p);else if(p.endsWith('.sol'))sources[p]={content:fs.readFileSync(p,'utf8')};}}
walk('contracts/src');
const input={language:'Solidity',sources,settings:{optimizer:{enabled:true,runs:200},viaIR:true,evmVersion:'paris',outputSelection:{'*':{'*':['abi','evm.bytecode.object','evm.deployedBytecode.object','evm.deployedBytecode.immutableReferences']}}}};
const output=JSON.parse(solc.compile(JSON.stringify(input),{import:(p)=>{try{return {contents:fs.readFileSync(p.startsWith('@')?'node_modules/'+p:p,'utf8')}}catch{return {error:'missing '+p}}}}));
for(const e of output.errors||[])console.error(e.formattedMessage);
if((output.errors||[]).some(e=>e.severity==='error'))process.exit(1);
const c=output.contracts['contracts/src/FlashArbitrageExecutor.sol'].FlashArbitrageExecutor;
fs.mkdirSync('src/flasharb/artifacts',{recursive:true});
fs.writeFileSync('src/flasharb/artifacts/FlashArbitrageExecutor.json',JSON.stringify({compiler:solc.version(),settings:input.settings,abi:c.abi,bytecode:'0x'+c.evm.bytecode.object,runtime:'0x'+c.evm.deployedBytecode.object,immutableReferences:c.evm.deployedBytecode.immutableReferences},null,2)+'\n');
console.log('Executor artifact compiled: '+(c.evm.deployedBytecode.object.length/2)+' runtime bytes');
