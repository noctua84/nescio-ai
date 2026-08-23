import argparse, os, glob, json, collections, re, statistics

ap = argparse.ArgumentParser(
    description="Deep scan of Claude Code session transcripts for token-usage analysis.")
ap.add_argument('--raw', action='store_true',
                 help="Keep real project-directory slugs (machine-local paths, usernames) in "
                      "the output instead of anonymized pseudonyms. Output produced with --raw "
                      "must NEVER be committed to a public repo.")
ap.add_argument('-o', '--output', default=None,
                 help="Output path for data.json (default: alongside this script).")
args = ap.parse_args()

OUT_PATH = args.output or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data.json')

root=os.path.expanduser(r'~\.claude\projects')
files=glob.glob(os.path.join(root,'*','*.jsonl'))
seen=set()
tools=collections.Counter(); tool_res_bytes=collections.Counter()
sub_calls=0; sub_tokens=0; sub_by_type=collections.Counter(); sub_tok_by_type=collections.Counter()
ctx_by_idx=collections.defaultdict(list)
daily=collections.defaultdict(lambda: collections.Counter())
proj=collections.defaultdict(lambda: collections.Counter())
models=collections.defaultdict(lambda: collections.Counter())
sess=collections.defaultdict(lambda: collections.Counter())
reqs=[]           # (ctx, out, think, model)
over200=0; excess200=0; over200_cr=0
sess_reqcount=[]
startup=[]

SUB_RE=re.compile(r'subagent_tokens:\s*(\d+)')
TYPE_RE=re.compile(r'"subagent_type"\s*:\s*"([^"]+)"')

for f in files:
    pj=os.path.basename(os.path.dirname(f)); sid=os.path.basename(f)[:-6]
    idx=0; first=True
    try: fh=open(f,encoding='utf-8',errors='replace')
    except OSError: continue
    with fh:
        for line in fh:
            if 'subagent_tokens' in line:
                for m in SUB_RE.finditer(line):
                    sub_tokens+=int(m.group(1))
            try: d=json.loads(line)
            except: continue
            t=d.get('type')
            if t=='assistant':
                m=d.get('message') or {}
                for blk in (m.get('content') or []):
                    if isinstance(blk,dict) and blk.get('type')=='tool_use':
                        nm=blk.get('name','?'); tools[nm]+=1
                        if nm in ('Agent','Task'):
                            sub_calls+=1
                            st=(blk.get('input') or {}).get('subagent_type','(default)')
                            sub_by_type[st]+=1
                u=m.get('usage')
                rid=d.get('requestId') or m.get('id')
                if isinstance(u,dict) and rid and rid not in seen:
                    seen.add(rid)
                    inp=u.get('input_tokens',0) or 0; out=u.get('output_tokens',0) or 0
                    cw=u.get('cache_creation_input_tokens',0) or 0; cr=u.get('cache_read_input_tokens',0) or 0
                    th=(u.get('output_tokens_details') or {}).get('thinking_tokens',0) or 0
                    ctx=inp+cw+cr; mdl=m.get('model','?'); day=(d.get('timestamp') or '')[:10]
                    rec=dict(req=1,inp=inp,out=out,cw=cw,cr=cr,think=th,ctx=ctx)
                    daily[day].update(rec); proj[pj].update(rec); models[mdl].update(rec); sess[(pj,sid)].update(rec)
                    reqs.append((ctx,out,th))
                    ctx_by_idx[min(idx//10,29)].append(ctx)
                    if ctx>200_000:
                        over200+=1; excess200+=ctx-200_000; over200_cr+=cr
                    if first: startup.append(ctx); first=False
                    idx+=1
            elif t=='user':
                tr=d.get('toolUseResult')
                if tr is not None:
                    tool_res_bytes[ (d.get('sourceToolAssistantUUID') or '')[:0] or 'all' ]+=len(json.dumps(tr))
    if idx: sess_reqcount.append(idx)

def W(c): return c['cr']*0.1+c['cw']*1.25+c['inp']+c['out']*5
grand=collections.Counter()
for c in proj.values(): grand.update(c)

# Project directory slugs (e.g. "C--Users-alice-code-some-client-app") embed the
# local username and every private repo name on this machine. They MUST NOT ship in a public
# repo. Anonymize to stable pseudonyms by default, assigned in descending order of weighted
# spend so the relative shape of the data (which project dominates, the long tail, etc.) is
# preserved without revealing what any of it actually is. `--raw` opts out for local use only.
projects_sorted = sorted([(k,W(v),dict(v)) for k,v in proj.items()],key=lambda x:-x[1])[:15]
if args.raw:
    projects_out = projects_sorted
else:
    projects_out = [(f"project-{i+1:02d}", w, stats)
                     for i, (_slug, w, stats) in enumerate(projects_sorted)]

out={
 'grand':dict(grand),'grand_weighted':W(grand),
 'daily':{k:dict(v) for k,v in sorted(daily.items()) if k>='2026-07-01'},
 'daily_w':{k:W(v) for k,v in sorted(daily.items()) if k>='2026-07-01'},
 'models':{k:dict(v)|{'w':W(v)} for k,v in models.items()},
 'projects':projects_out,
 'tools':tools.most_common(25),
 'sub_calls':sub_calls,'sub_tokens':sub_tokens,'sub_by_type':sub_by_type.most_common(20),
 'ctx_by_idx':{k:int(statistics.median(v)) for k,v in sorted(ctx_by_idx.items()) if v},
 'ctx_by_idx_n':{k:len(v) for k,v in sorted(ctx_by_idx.items())},
 'over200':over200,'excess200':excess200,'total_req':len(seen),
 'sess_reqcount':sorted(sess_reqcount),
 'startup':sorted(startup),
}
json.dump(out,open(OUT_PATH,'w'),indent=1)
if args.raw:
    print("WARNING: --raw output contains real project paths/usernames. Do NOT commit this file.")

print(f"requests={len(seen)}  weighted={W(grand)/1e6:.0f}M")
print(f"\n=== SUBAGENT SPEND (from Agent tool results) ===")
print(f"  Agent/Task calls: {sub_calls}   reported subagent_tokens total: {sub_tokens/1e6:.1f}M")
print(f"  by subagent_type:"); [print(f"    {v:>5}  {k}") for k,v in sub_by_type.most_common(14)]
print(f"\n=== CONTEXT GROWTH (median ctx by request # within session) ===")
for k,v in sorted(ctx_by_idx.items()):
    if len(ctx_by_idx[k])>20: print(f"  req {k*10:>3}-{k*10+9:<3}  median ctx {statistics.median(ctx_by_idx[k])/1000:>6.0f}k   (n={len(ctx_by_idx[k])})")
print(f"\n=== 200k CAP SIMULATION ===")
print(f"  requests over 200k ctx: {over200}/{len(seen)} ({over200/max(1,len(seen))*100:.0f}%)")
print(f"  tokens carried ABOVE 200k: {excess200/1e6:.0f}M  ({excess200/max(1,grand['ctx'])*100:.0f}% of all context)")
print(f"\n=== TOP TOOLS ==="); [print(f"  {v:>6}  {k}") for k,v in tools.most_common(16)]
print(f"\n=== SESSION LENGTH ===")
s=sorted(sess_reqcount); n=len(s)
print(f"  sessions={n}  median={s[n//2]} req  p90={s[int(n*.9)]}  max={s[-1]}")
