import os, glob, json, collections, datetime, sys

root = os.path.expanduser(r'~\.claude\projects')
files = glob.glob(os.path.join(root, '*', '*.jsonl'))

seen = set()
by_day = collections.defaultdict(lambda: collections.Counter())
by_proj = collections.defaultdict(lambda: collections.Counter())
by_model = collections.defaultdict(lambda: collections.Counter())
by_chain = collections.defaultdict(lambda: collections.Counter())
sessions = collections.defaultdict(lambda: collections.Counter())
sess_meta = {}
first_req = []   # cache_creation on the first request of each session
req_ctx = []     # context size per request

def proj_of(path):
    return os.path.basename(os.path.dirname(path))

for f in files:
    pj = proj_of(f)
    sid = os.path.basename(f)[:-6]
    local_first = True
    try:
        fh = open(f, encoding='utf-8', errors='replace')
    except OSError:
        continue
    with fh:
        for line in fh:
            if '"usage"' not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            m = d.get('message') or {}
            u = m.get('usage')
            if not isinstance(u, dict):
                continue
            rid = d.get('requestId') or m.get('id')
            if not rid or rid in seen:
                continue
            seen.add(rid)

            inp  = u.get('input_tokens', 0) or 0
            out  = u.get('output_tokens', 0) or 0
            cw   = u.get('cache_creation_input_tokens', 0) or 0
            cr   = u.get('cache_read_input_tokens', 0) or 0
            think = (u.get('output_tokens_details') or {}).get('thinking_tokens', 0) or 0
            model = m.get('model', '?')
            side  = bool(d.get('isSidechain'))
            ts    = d.get('timestamp', '')
            day   = ts[:10] if ts else '?'

            rec = dict(inp=inp, out=out, cw=cw, cr=cr, think=think, req=1)
            for bucket, key in ((by_day, day), (by_proj, pj), (by_model, model),
                                (by_chain, 'subagent' if side else 'main'),
                                (sessions, (pj, sid))):
                bucket[key].update(rec)
            sess_meta.setdefault((pj, sid), ts)
            req_ctx.append(cw + cr + inp)
            if local_first and not side:
                first_req.append(cw + cr)
                local_first = False

def wtot(c):
    # weighted tokens: cache read 0.1x, cache write 1.25x, output 5x (API-relative)
    return c['cr']*0.1 + c['cw']*1.25 + c['inp']*1.0 + c['out']*5.0

def fmt(c):
    return (f"req={c['req']:>6}  in={c['inp']/1e6:>7.2f}M  out={c['out']/1e6:>6.2f}M  "
            f"cw={c['cw']/1e6:>8.2f}M  cr={c['cr']/1e6:>9.2f}M  think={c['think']/1e6:>5.2f}M")

grand = collections.Counter()
for c in by_proj.values():
    grand.update(c)

print("="*100)
print("GRAND TOTAL (deduped by requestId)")
print(" ", fmt(grand))
print(f"  raw tokens: {(grand['inp']+grand['out']+grand['cw']+grand['cr'])/1e6:.1f}M")
print(f"  cache read share of all input: {grand['cr']/max(1,grand['cr']+grand['cw']+grand['inp'])*100:.1f}%")
print(f"  cache WRITE share of all input: {grand['cw']/max(1,grand['cr']+grand['cw']+grand['inp'])*100:.1f}%")
print(f"  weighted (API-relative units): {wtot(grand)/1e6:.1f}M")

print("\n" + "="*100)
print("MAIN vs SUBAGENT")
for k, c in sorted(by_chain.items(), key=lambda x: -wtot(x[1])):
    print(f"  {k:>9}  {fmt(c)}  weighted={wtot(c)/1e6:>7.1f}M  ({wtot(c)/max(1,wtot(grand))*100:>4.1f}%)")

print("\n" + "="*100)
print("BY MODEL")
for k, c in sorted(by_model.items(), key=lambda x: -wtot(x[1]))[:8]:
    print(f"  {k:<28} {fmt(c)}  weighted={wtot(c)/1e6:>7.1f}M ({wtot(c)/max(1,wtot(grand))*100:>4.1f}%)")

print("\n" + "="*100)
print("BY DAY")
for k in sorted(by_day):
    c = by_day[k]
    print(f"  {k}  {fmt(c)}  weighted={wtot(c)/1e6:>7.1f}M")

print("\n" + "="*100)
print("TOP 12 PROJECTS by weighted spend")
for k, c in sorted(by_proj.items(), key=lambda x: -wtot(x[1]))[:12]:
    print(f"  {wtot(c)/1e6:>7.1f}M  ({wtot(c)/max(1,wtot(grand))*100:>4.1f}%)  {fmt(c)}  {k[:62]}")

print("\n" + "="*100)
print("TOP 12 SESSIONS by weighted spend")
for k, c in sorted(sessions.items(), key=lambda x: -wtot(x[1]))[:12]:
    print(f"  {wtot(c)/1e6:>7.1f}M  {fmt(c)}  {sess_meta.get(k,'')[:10]}  {k[0][:48]}")

print("\n" + "="*100)
req_ctx.sort()
n = len(req_ctx)
if n:
    def pct(p): return req_ctx[min(n-1, int(n*p/100))]
    print(f"CONTEXT SIZE PER REQUEST (n={n})")
    print(f"  p50={pct(50)/1000:.0f}k  p75={pct(75)/1000:.0f}k  p90={pct(90)/1000:.0f}k  p99={pct(99)/1000:.0f}k  max={req_ctx[-1]/1000:.0f}k")
first_req.sort()
m = len(first_req)
if m:
    def fpct(p): return first_req[min(m-1, int(m*p/100))]
    print(f"\nSESSION STARTUP COST (cache write+read on first main request, n={m})")
    print(f"  p50={fpct(50)/1000:.0f}k  p90={fpct(90)/1000:.0f}k  max={first_req[-1]/1000:.0f}k")
    print(f"  total spent just starting sessions: {sum(first_req)/1e6:.1f}M tokens")
