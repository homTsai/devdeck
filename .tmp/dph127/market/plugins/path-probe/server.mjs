
import fs from 'node:fs';
import readline from 'node:readline';
const info = {cwd: process.cwd(), script: import.meta.url};
fs.writeFileSync(new URL('./started.json', import.meta.url), JSON.stringify(info));
for await (const line of readline.createInterface({input: process.stdin})) {
  const m = JSON.parse(line);
  if (m.id === undefined) continue;
  let result = {};
  if (m.method === 'initialize') result = {protocolVersion:m.params.protocolVersion, capabilities:{tools:{}}, serverInfo:{name:'path-probe',version:'1.0.0'}};
  if (m.method === 'tools/list') result = {tools:[{name:'probe',description:'Read cwd',inputSchema:{type:'object',properties:{}}}]};
  if (m.method === 'tools/call') result = {content:[{type:'text',text:JSON.stringify(info)}]};
  process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:m.id,result})+'\n');
}
