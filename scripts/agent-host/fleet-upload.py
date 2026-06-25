#!/usr/bin/env python3
# Fleet console — a snappy web UI to COMMAND the agents without typing into the
# laggy remote terminal. Pick an agent, type in a normal text box (instant), and
# Send -> it's delivered to that agent (tmux send-keys). Also drag/tap to upload a
# file to an agent. Bound to localhost, exposed ONLY via `tailscale serve`
# (tailnet-private) — nothing leaves your own encrypted network.
import http.server, socketserver, os, re, subprocess, urllib.parse

PORT = 8088
HOME = os.path.expanduser("~")
UP = os.path.join(HOME, "work", "uploads"); os.makedirs(UP, exist_ok=True)
PANES = os.path.join(HOME, "fleet", "assign", "panes.txt")

def agents():
    out = []
    try:
        for line in open(PANES):
            p = line.split()
            if len(p) >= 3:
                task = ""
                try: task = open(os.path.join(HOME, "fleet", "assign", p[0] + ".txt")).read().strip()[:40]
                except Exception: pass
                out.append((p[0], p[1], p[2], task))
    except FileNotFoundError:
        pass
    return out

def pane_for(agent):
    return next((p for a, p, _, _ in agents() if a == agent), None)

PAGE = """<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>fleet console</title>
<style>
body{font:16px -apple-system,system-ui;background:#0d1117;color:#c9d1d9;margin:0;padding:16px}
h2{margin:0 0 10px} label{font-size:13px;color:#8b949e}
select,button,textarea{font:16px system-ui;padding:12px;border-radius:10px;border:1px solid #30363d;background:#161b22;color:#c9d1d9;width:100%;box-sizing:border-box;margin:6px 0}
textarea{min-height:120px;resize:vertical} button{background:#238636;color:#fff;border:0;font-weight:600}
#z{border:2px dashed #2ea043;border-radius:12px;padding:26px;text-align:center;color:#8b949e;margin:10px 0}
#z.drag{background:#161b22;border-color:#3fb950} #log{white-space:pre-wrap;color:#8b949e;font-size:13px;margin-top:10px}
.row{display:flex;gap:8px} .row button{margin:0}
</style>
<h2>🛰 fleet console</h2>
<label>agent</label>
<select id=agent>{opts}</select>
<label>message</label>
<textarea id=msg placeholder="tell this agent what to do… (sends instantly, no terminal lag)"></textarea>
<div class=row><button onclick="send()">Send ▶</button><button onclick="send(true)" style="background:#8957e5">Send + Enter</button></div>
<label>or drop a file for this agent</label>
<div id=z>tap to pick a file — or drag one here</div>
<input id=f type=file style=display:none>
<div id=log></div>
<script>
const ag=document.getElementById('agent'),msg=document.getElementById('msg'),log=document.getElementById('log'),z=document.getElementById('z'),f=document.getElementById('f');
async function send(){ const t=msg.value; if(!t.trim()){return;} log.textContent='sending…';
 try{ const r=await fetch('/send?agent='+encodeURIComponent(ag.value),{method:'POST',body:t}); log.textContent=await r.text(); msg.value=''; }catch(e){log.textContent='error: '+e;} }
z.onclick=()=>f.click(); f.onchange=()=>up(f.files[0]);
z.ondragover=e=>{e.preventDefault();z.classList.add('drag')}; z.ondragleave=()=>z.classList.remove('drag');
z.ondrop=e=>{e.preventDefault();z.classList.remove('drag');up(e.dataTransfer.files[0])};
async function up(file){ if(!file){return;} log.textContent='uploading '+file.name+'…';
 try{ const r=await fetch('/upload?name='+encodeURIComponent(file.name)+'&agent='+encodeURIComponent(ag.value),{method:'POST',body:file}); log.textContent=await r.text(); }catch(e){log.textContent='error: '+e;} }
</script>"""

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body, ctype="text/plain"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code); self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if urllib.parse.urlparse(self.path).path != "/":
            self.send_error(404); return
        opts = "".join('<option value="%s">%s · %s%s</option>' % (a, a, r, (" · " + t) if t else "") for a, _, r, t in agents()) or "<option value=''>(no agents yet)</option>"
        self._send(200, PAGE.replace("{opts}", opts), "text/html")
    def do_POST(self):
        u = urllib.parse.urlparse(self.path); q = urllib.parse.parse_qs(u.query)
        agent = q.get("agent", [""])[0]; pane = pane_for(agent)
        n = int(self.headers.get("content-length", 0)); data = self.rfile.read(n) if n else b""
        if u.path == "/send":
            if not pane: self._send(400, "no such agent"); return
            text = data.decode("utf-8", "replace")
            subprocess.run(["tmux", "send-keys", "-t", pane, "-l", text], check=False)  # -l = literal
            subprocess.run(["tmux", "send-keys", "-t", pane, "Enter"], check=False)
            subprocess.run(["tmux", "send-keys", "-t", pane, "Enter"], check=False)     # beat paste-submit quirk
            self._send(200, "sent to %s ✓" % agent); return
        if u.path == "/upload":
            name = re.sub(r"[^A-Za-z0-9._-]", "_", q.get("name", ["file"])[0])[:100] or "file"
            dest = os.path.join(UP, name)
            with open(dest, "wb") as out: out.write(data)
            msg = "saved %s (%d bytes)" % (dest, n)
            if pane:
                subprocess.run(["tmux", "send-keys", "-t", pane, "-l", "I uploaded a file at %s — please look at it and use it." % dest], check=False)
                subprocess.run(["tmux", "send-keys", "-t", pane, "Enter"], check=False)
                subprocess.run(["tmux", "send-keys", "-t", pane, "Enter"], check=False)
                msg += " · told %s" % agent
            self._send(200, msg); return
        self.send_error(404)

socketserver.ThreadingTCPServer.allow_reuse_address = True
with socketserver.ThreadingTCPServer(("127.0.0.1", PORT), H) as s:
    print("fleet-console on 127.0.0.1:%d" % PORT); s.serve_forever()
