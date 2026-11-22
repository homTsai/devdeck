import json, os, pathlib, queue, shutil, subprocess, threading, time

ROOT = pathlib.Path(__file__).resolve().parent
HOME = ROOT / 'home'
MARKET = ROOT / 'market'
PLUGIN = MARKET / 'plugins' / 'path-probe'
for d in [HOME, PLUGIN / '.codex-plugin', MARKET / '.agents/plugins']:
    d.mkdir(parents=True, exist_ok=True)
def put(path, value):
    path.write_text(json.dumps(value, indent=2), encoding='utf-8')
put(MARKET / '.agents/plugins/marketplace.json', {
    'name': 'dph127-probe', 'plugins': [{'name': 'path-probe',
    'source': './plugins/path-probe', 'policy': {'installation': 'AVAILABLE', 'authentication': 'ON_INSTALL'}}]})
put(PLUGIN / '.codex-plugin/plugin.json', {'name': 'path-probe', 'version': '1.0.0',
    'description': 'Isolated path probe', 'mcpServers': './.codex.mcp.json'})
put(PLUGIN / '.codex.mcp.json', {'mcpServers': {'path-probe': {
    'command': shutil.which('node'), 'args': ['./server.mjs'], 'cwd': '.'}}})
(PLUGIN / 'server.mjs').write_text(r"""
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
""", encoding='utf-8')
env = os.environ.copy()
env['CODEX_HOME'] = str(HOME)
proc = subprocess.Popen([shutil.which('codex'), 'app-server', '--stdio'], cwd=ROOT,
    env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, encoding='utf-8')
messages = queue.Queue()
errors = []
threading.Thread(target=lambda: [messages.put(json.loads(s)) for s in proc.stdout], daemon=True).start()
threading.Thread(target=lambda: [errors.append(s) for s in proc.stderr], daemon=True).start()
counter = 0
transcript = []
def rpc(method, params):
    global counter
    counter += 1
    proc.stdin.write(json.dumps({'jsonrpc':'2.0','id':counter,'method':method,'params':params})+'\n')
    proc.stdin.flush()
    deadline = time.monotonic()+25
    while time.monotonic() < deadline:
        m = messages.get(timeout=max(.1, deadline-time.monotonic()))
        transcript.append(m)
        if m.get('id') == counter:
            print(method, json.dumps(m)[:7000], flush=True)
            if 'error' in m: raise RuntimeError(m['error'])
            return m['result']
    raise TimeoutError(method)
try:
    rpc('initialize', {'clientInfo':{'name':'dph127-probe','version':'1.0.0'},'capabilities':{'experimentalApi':True}})
    rpc('plugin/install', {'pluginName':'path-probe','marketplacePath':str(MARKET / '.agents/plugins/marketplace.json')})
    rpc('mcpServerStatus/list', {})
finally:
    proc.terminate()
    proc.wait(timeout=5)
    put(ROOT / 'transcript.json', transcript)
    (ROOT / 'stderr.txt').write_text(''.join(errors), encoding='utf-8')
    print('STARTED', [(str(p),p.read_text(encoding='utf-8')) for p in HOME.rglob('started.json')])
