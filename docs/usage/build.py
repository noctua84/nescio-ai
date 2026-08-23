# -*- coding: utf-8 -*-
"""Generate the token-usage dashboard from the scanned figures."""
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

CTX = [84, 112, 136, 159, 186, 209, 237, 266, 296, 320, 344, 371, 399, 420,
       442, 463, 493, 527, 552, 581, 606, 641, 665, 683, 706, 737, 756, 789]

DAILY = [("07-12", 1), ("07-13", 1), ("07-14", 3), ("07-15", 2), ("07-16", 9),
         ("07-17", 33), ("07-18", 19), ("07-19", 16), ("07-20", 9), ("07-21", 33),
         ("07-22", 17), ("07-23", 7), ("07-25", 25), ("07-26", 37), ("07-27", 11),
         ("07-28", 31), ("07-29", 14), ("07-30", 26), ("07-31", 9), ("08-02", 1),
         ("08-03", 9), ("08-04", 14), ("08-05", 50), ("08-06", 38), ("08-07", 36),
         ("08-08", 6), ("08-09", 29), ("08-10", 30), ("08-11", 26), ("08-12", 14),
         ("08-13", 87), ("08-14", 110), ("08-15", 10), ("08-16", 81), ("08-17", 72),
         ("08-18", 67), ("08-19", 89), ("08-20", 44), ("08-21", 21), ("08-22", 0)]

# ---------------- context growth chart ----------------
W, H = 1060, 400
ML, MR, MT, MB = 62, 26, 22, 44
pw, ph = W - ML - MR, H - MT - MB
YMAX = 800


def sx(i):
    return ML + i * pw / (len(CTX) - 1)


def sy(v):
    return MT + ph - (v / YMAX) * ph


pts = " ".join("%.1f,%.1f" % (sx(i), sy(v)) for i, v in enumerate(CTX))
area = "%d,%.1f " % (ML, sy(0)) + pts + " %.1f,%.1f" % (sx(len(CTX) - 1), sy(0))

above = [(sx(i), sy(v)) for i, v in enumerate(CTX) if v > 200]
if above:
    abv = ("%.1f,%.1f " % (above[0][0], sy(200))
           + " ".join("%.1f,%.1f" % (x, y) for x, y in above)
           + " %.1f,%.1f" % (above[-1][0], sy(200)))
else:
    abv = ""

grid = "".join(
    '<line class="grid" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/>'
    '<text class="ax" x="%d" y="%.1f" text-anchor="end">%dk</text>'
    % (ML, sy(g), W - MR, sy(g), ML - 10, sy(g) + 4, g)
    for g in [0, 200, 400, 600, 800])

xlab = "".join(
    '<text class="ax" x="%.1f" y="%d" text-anchor="middle">%d</text>'
    % (sx(i), H - MB + 20, i * 10)
    for i in range(0, len(CTX), 4))

dots = "".join(
    '<circle class="hp" cx="%.1f" cy="%.1f" r="12" data-l="request #%d&#8211;%d" '
    'data-v="%dk median context"/>' % (sx(i), sy(v), i * 10, i * 10 + 9, v)
    for i, v in enumerate(CTX))

ctx_chart = (
    '<svg viewBox="0 0 %d %d" class="chart" role="img" aria-label="Median context size '
    'grows steadily with request number within a session, crossing 200k around request 55 '
    'and reaching 789k by request 275.">' % (W, H)
    + grid
    + '<polygon class="fill-under" points="%s"/>' % area
    + '<polygon class="fill-waste" points="%s"/>' % abv
    + '<line class="thresh" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/>' % (ML, sy(200), W - MR, sy(200))
    + '<text class="thlab" x="%d" y="%.1f" text-anchor="end">200k &#8212; a standard context ceiling</text>'
      % (W - MR, sy(200) - 9)
    + '<polyline class="line" points="%s"/>' % pts
    + '<circle class="endpt" cx="%.1f" cy="%.1f" r="5"/>' % (sx(len(CTX) - 1), sy(CTX[-1]))
    + '<text class="endlab" x="%.1f" y="%.1f" text-anchor="end">789k</text>'
      % (sx(len(CTX) - 1), sy(CTX[-1]) - 14)
    + '<text class="startlab" x="%.1f" y="%.1f">84k at session start</text>'
      % (sx(0) + 8, sy(CTX[0]) - 14)
    + xlab
    + '<text class="axt" x="%.1f" y="%d" text-anchor="middle">request number within a session</text>'
      % (ML + pw / 2, H - 4)
    + dots + '</svg>')

# ---------------- daily bars ----------------
W2, H2 = 1060, 260
ML2, MR2, MT2, MB2 = 62, 20, 18, 42
pw2, ph2 = W2 - ML2 - MR2, H2 - MT2 - MB2
DMAX = 120
bw = pw2 / len(DAILY)

bars = []
for i, (d, v) in enumerate(DAILY):
    h = (v / DMAX) * ph2
    x = ML2 + i * bw
    late = "late" if d >= "08-13" else ""
    bars.append('<rect class="bar %s" x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="2.5" '
                'data-l="%s" data-v="%dM weighted tokens"/>'
                % (late, x + 1.2, MT2 + ph2 - h, bw - 2.4, max(h, 0.8), d, v))

g2 = "".join(
    '<line class="grid" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/>'
    '<text class="ax" x="%d" y="%.1f" text-anchor="end">%dM</text>'
    % (ML2, MT2 + ph2 - (g / DMAX) * ph2, W2 - MR2, MT2 + ph2 - (g / DMAX) * ph2,
       ML2 - 10, MT2 + ph2 - (g / DMAX) * ph2 + 4, g)
    for g in [0, 40, 80, 120])

xl2 = "".join(
    '<text class="ax" x="%.1f" y="%d" text-anchor="middle">%s</text>'
    % (ML2 + i * bw + bw / 2, H2 - MB2 + 20, DAILY[i][0])
    for i in range(0, len(DAILY), 5))

infl_x = ML2 + 30 * bw
daily_chart = (
    '<svg viewBox="0 0 %d %d" class="chart" role="img" aria-label="Daily weighted token '
    'spend. The step change on August 13 is a subscription upgrade from Max-5 to '
    'Max-20, not a change in behaviour.">' % (W2, H2)
    + g2 + "".join(bars)
    + '<line class="infl" x1="%.1f" y1="%d" x2="%.1f" y2="%.1f"/>' % (infl_x, MT2, infl_x, MT2 + ph2)
    + '<text class="thlab" x="%.1f" y="%d" text-anchor="end">Aug 13 &#8212; Max-5 to Max-20</text>'
      % (infl_x - 8, MT2 + 13)
    + xl2 + '</svg>')

# ---------------- proportion bar ----------------
SEG = [("Cache reads", "re-sending the conversation", 61.1, "s1"),
       ("Cache writes", "context churn", 26.0, "s2"),
       ("Output", "text Claude actually generates", 12.9, "s3")]

prop = ('<div class="propbar">'
        + "".join('<div class="seg %s" style="flex:%s"><span class="segp">%s%%</span></div>'
                  % (c, p, p) for _, _, p, c in SEG)
        + '</div>')

key = ('<div class="key">'
       + "".join('<div class="ki"><span class="sw %s"></span><div><b>%s</b> '
                 '<span class="kp">%s%%</span><em>%s</em></div></div>' % (c, n, p, s)
                 for n, s, p, c in SEG)
       + '</div>')

# ---------------- levers ----------------
LEVERS = [
    ("Cap or clear context near 200k", "31&#8211;43%", "high",
     "49% of every context token you have ever sent &#8212; 3,566M of 7,245M &#8212; is the portion "
     "sitting above the 200k mark. 66% of all requests carry more than 200k. This is not a tuning "
     "knob; it is half the bill.",
     "Drop <code>opus[1m]</code> to a 200k model, or <code>/clear</code> on task boundaries instead "
     "of running one long session."),
    ("Break up marathon sessions", "up to 17%", "high",
     "Your two largest sessions &#8212; 1,300 and 1,198 requests &#8212; together burned 195M weighted "
     "tokens: 17% of six weeks of spend, from two sittings. Median session is 78 requests; p90 is 284.",
     "A session past roughly 80 requests is carrying far more history than it is using."),
    ("Trim the session preamble", "&#8776;6%", "medium",
     "Every session opens at 72k tokens before you type &#8212; MCP tool schemas, 7 plugins, the skills "
     "listing, and a 12.8k-character orchestrator prompt. That floor is re-sent on all 20,903 requests: "
     "1,505M tokens, 21% of all context.",
     "Halving the preamble to ~36k returns roughly 6% of weighted spend. Disable MCP servers you are "
     "not using in a given project."),
    ("Tier the model", "unquantified", "medium",
     "100% of spend is Opus &#8212; 80% opus-4-8, 19% opus-5. Bash alone is 12,921 of ~16,700 tool calls, "
     "and mechanical shell work does not need the frontier model. The crew has since moved to "
     "<code>claude-opus-5</code>, which is priced identically to 4.8 &#8212; so that was a free upgrade, "
     "not a saving.",
     "The lever is the <em>main loop</em>, not the subagents. Route routine sessions to Sonnet."),
    ("Reconsider always-high effort", "&#8776;2% direct", "low",
     "Every one of 18,432 recorded requests ran at <code>effort: high</code>. Thinking is 4.87M of "
     "29.53M output tokens.",
     "Direct cost is small. The indirect cost &#8212; longer outputs, more tool loops &#8212; is real "
     "but not measurable from this data."),
]

lev = "".join(
    '<article class="lev"><div class="levhead"><span class="rank">%d</span><h3>%s</h3>'
    '<span class="save">%s<em>est. saving</em></span>'
    '<span class="conf c-%s">%s confidence</span></div>'
    '<p>%s</p><p class="do">%s</p></article>'
    % (i + 1, t, s, c, c, b, d)
    for i, (t, s, c, b, d) in enumerate(LEVERS))

# ---------------- agent audit ----------------
AGENTS = [
    ("general-purpose", "inherits Opus", 1111, "warn",
     "60% of all subagent calls and the only one with no model set."),
    ("explore", "haiku-4-5", 322, "ok", "Correctly cheap for a search role, and the second-most used."),
    ("socrates", "opus-4-8", 62, "ok", "Adversarial reasoning earns the frontier model."),
    ("validator", "opus-4-8", 53, "warn",
     "Its own brief says <em>blocker-finder, not perfectionist</em>, in a 2.4k prompt. Sonnet work."),
    ("pyrrho", "opus-4-8", 37, "ok", "Code audit; justified."),
    ("aristotle", "opus-4-8", 35, "ok", "Architecture reasoning; justified."),
    ("plato", "opus-4-8", 30, "ok", "Planning; justified."),
    ("librarian", "sonnet-5", 19, "ok", "Aligned."),
    ("scout", "opus-4-8", 2, "warn", "Pre-plan triage on the most expensive model."),
    ("vision", "sonnet-5", 0, "ok", "Aligned."),
]

arows = "".join(
    '<tr><td class="mono">%s</td><td class="mono">%s</td><td class="mono num">%s</td>'
    '<td><span class="pill p-%s">%s</span></td><td>%s</td></tr>'
    % (n, m, c if c else "&#8212;", s, "aligned" if s == "ok" else "review", note)
    for n, m, c, s, note in AGENTS)

DUPES = [("advisor", "aristotle", "99.5%"), ("critic", "socrates", "99.1%"),
         ("planner", "plato", "99.6%"), ("reviewer", "pyrrho", "87.2%")]

drows = "".join(
    '<tr><td class="mono">%s</td><td class="mono">%s</td>'
    '<td class="mono num">%s</td></tr>' % (a, b, s) for a, b, s in DUPES)

# ---------------- page ----------------
CSS = """
:root{
 --paper:#F2F4F6; --surface:#FFFFFF; --ink:#141A22; --ink2:#4A5566; --muted:#77839A;
 --line:#DCE2EA; --line2:#EAEEF3; --accent:#4553C7;
 --s1:#5A6AE8; --s2:#12A594; --s3:#D97706;
 --waste:rgba(90,106,232,.20); --under:rgba(90,106,232,.07);
 --warnbg:#FDF3E3; --warnfg:#8A5A08; --okbg:#E7F4F1; --okfg:#0C6E62;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
 --paper:#0F1319; --surface:#161C25; --ink:#E8ECF3; --ink2:#AEB9C9; --muted:#7F8B9E;
 --line:#242C38; --line2:#1C232E; --accent:#8A95F0;
 --s1:#5C6BE0; --s2:#0E9182; --s3:#B87A15;
 --waste:rgba(92,107,224,.30); --under:rgba(92,107,224,.10);
 --warnbg:#2E2410; --warnfg:#E0AC55; --okbg:#0F2A26; --okfg:#4FC0AE;
}}
:root[data-theme="dark"]{
 --paper:#0F1319; --surface:#161C25; --ink:#E8ECF3; --ink2:#AEB9C9; --muted:#7F8B9E;
 --line:#242C38; --line2:#1C232E; --accent:#8A95F0;
 --s1:#5C6BE0; --s2:#0E9182; --s3:#B87A15;
 --waste:rgba(92,107,224,.30); --under:rgba(92,107,224,.10);
 --warnbg:#2E2410; --warnfg:#E0AC55; --okbg:#0F2A26; --okfg:#4FC0AE;
}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
 font-family:Archivo,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
 font-size:16px;line-height:1.6;-webkit-font-smoothing:antialiased}
.wrap{max-width:1120px;margin:0 auto;padding:56px 28px 96px;display:flex;flex-direction:column;gap:52px}
.mono{font-family:"IBM Plex Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums}
.num{font-variant-numeric:tabular-nums;text-align:right}
header{display:flex;flex-direction:column;gap:14px}
.eyebrow{font-family:"IBM Plex Mono",monospace;font-size:12px;letter-spacing:.14em;
 text-transform:uppercase;color:var(--muted)}
h1{font-size:clamp(38px,6vw,62px);line-height:1.02;font-weight:800;letter-spacing:-.028em;
 margin:0;text-wrap:balance}
.lede{font-size:19px;color:var(--ink2);max-width:66ch;margin:0}
.thesis{font-size:clamp(21px,2.6vw,27px);line-height:1.4;font-weight:600;letter-spacing:-.015em;
 margin:0;padding:24px 0 24px 26px;border-left:3px solid var(--accent);max-width:60ch;text-wrap:balance}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));gap:1px;
 background:var(--line);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.stat{background:var(--surface);padding:18px 20px;display:flex;flex-direction:column;gap:3px}
.stat b{font-family:"IBM Plex Mono",monospace;font-size:27px;font-weight:600;
 letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.stat span{font-size:12.5px;color:var(--muted);letter-spacing:.02em}
section{display:flex;flex-direction:column;gap:18px}
h2{font-size:13px;font-family:"IBM Plex Mono",monospace;letter-spacing:.15em;text-transform:uppercase;
 color:var(--muted);margin:0;padding-bottom:11px;border-bottom:1px solid var(--line);font-weight:500}
h3{margin:0;font-size:18.5px;font-weight:700;letter-spacing:-.012em}
p{margin:0;max-width:70ch;color:var(--ink2)}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:22px}
.chartwrap{overflow-x:auto}
.chart{width:100%;min-width:620px;display:block}
.grid{stroke:var(--line2);stroke-width:1}
.ax{fill:var(--muted);font-family:"IBM Plex Mono",monospace;font-size:11px}
.axt{fill:var(--muted);font-family:Archivo,sans-serif;font-size:12px}
.fill-under{fill:var(--under)}
.fill-waste{fill:var(--waste)}
.line{fill:none;stroke:var(--s1);stroke-width:2.5;stroke-linejoin:round;stroke-linecap:round}
.thresh{stroke:var(--ink2);stroke-width:1.5;stroke-dasharray:5 4;opacity:.75}
.infl{stroke:var(--s3);stroke-width:1.5;stroke-dasharray:4 4}
.thlab{fill:var(--ink2);font-family:"IBM Plex Mono",monospace;font-size:11.5px}
.endpt{fill:var(--s1);stroke:var(--surface);stroke-width:2}
.endlab{fill:var(--ink);font-family:"IBM Plex Mono",monospace;font-size:13px;font-weight:600}
.startlab{fill:var(--muted);font-family:"IBM Plex Mono",monospace;font-size:11.5px}
.hp{fill:transparent;cursor:crosshair}
.bar{fill:var(--s1);opacity:.65}
.bar.late{opacity:1}
.bar:hover{fill:var(--accent);opacity:1}
.propbar{display:flex;gap:2px;height:60px;border-radius:8px;overflow:hidden}
.seg{display:flex;align-items:center;justify-content:center}
.seg.s1{background:var(--s1)}
.seg.s2{background:var(--s2)}
.seg.s3{background:var(--s3)}
.segp{font-family:"IBM Plex Mono",monospace;font-weight:600;font-size:15px;color:#fff}
.key{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:14px}
.ki{display:flex;gap:10px;align-items:flex-start}
.sw{width:12px;height:12px;border-radius:3px;flex:none;margin-top:5px}
.sw.s1{background:var(--s1)}
.sw.s2{background:var(--s2)}
.sw.s3{background:var(--s3)}
.ki b{font-size:14.5px;color:var(--ink)}
.kp{font-family:"IBM Plex Mono",monospace;color:var(--muted);font-size:13px}
.ki em{display:block;font-style:normal;font-size:13px;color:var(--muted);line-height:1.45}
.levs{display:flex;flex-direction:column;gap:12px}
.lev{background:var(--surface);border:1px solid var(--line);border-radius:12px;
 padding:20px 22px;display:flex;flex-direction:column;gap:9px}
.levhead{display:flex;align-items:center;gap:13px;flex-wrap:wrap}
.rank{font-family:"IBM Plex Mono",monospace;font-size:12px;font-weight:600;color:var(--surface);
 background:var(--ink);width:23px;height:23px;border-radius:50%;display:grid;place-items:center;flex:none}
.levhead h3{flex:1;min-width:210px}
.save{font-family:"IBM Plex Mono",monospace;font-size:19px;font-weight:600;color:var(--accent);
 display:flex;flex-direction:column;align-items:flex-end;line-height:1.15}
.save em{font-style:normal;font-size:10.5px;letter-spacing:.09em;text-transform:uppercase;
 color:var(--muted);font-family:Archivo,sans-serif}
.conf{font-size:11px;font-family:"IBM Plex Mono",monospace;padding:3px 9px;border-radius:20px;
 border:1px solid var(--line);color:var(--muted)}
.do{font-size:14.5px;color:var(--ink);border-top:1px dashed var(--line);padding-top:9px}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;font-family:"IBM Plex Mono",monospace;font-size:11px;letter-spacing:.09em;
 text-transform:uppercase;color:var(--muted);font-weight:500;padding:0 12px 9px;
 border-bottom:1px solid var(--line)}
th.num{text-align:right}
td{padding:11px 12px;border-bottom:1px solid var(--line2);color:var(--ink2);vertical-align:top}
td.mono{color:var(--ink);font-size:13px}
.pill{font-size:11px;font-family:"IBM Plex Mono",monospace;padding:2.5px 9px;
 border-radius:20px;white-space:nowrap}
.p-ok{background:var(--okbg);color:var(--okfg)}
.p-warn{background:var(--warnbg);color:var(--warnfg)}
code{font-family:"IBM Plex Mono",monospace;font-size:.9em;background:var(--line2);
 padding:1.5px 5px;border-radius:4px;color:var(--ink)}
.blind{border-left:3px solid var(--s3);padding-left:22px;display:flex;flex-direction:column;gap:15px}
.blind h3{font-size:16px}
.tip{position:fixed;pointer-events:none;background:var(--ink);color:var(--paper);
 padding:7px 11px;border-radius:7px;font-family:"IBM Plex Mono",monospace;font-size:12px;
 opacity:0;transition:opacity .12s;z-index:9;white-space:nowrap}
.tip b{display:block;font-weight:600}
footer{color:var(--muted);font-size:13px;border-top:1px solid var(--line);
 padding-top:20px;max-width:78ch}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""

JS = """
const tip=document.getElementById('tip');
document.querySelectorAll('[data-l]').forEach(function(el){
 el.addEventListener('mouseenter',function(){
   tip.innerHTML='<b>'+el.dataset.l+'</b>'+el.dataset.v; tip.style.opacity='1';});
 el.addEventListener('mousemove',function(e){
   tip.style.left=Math.min(e.clientX+14,window.innerWidth-190)+'px';
   tip.style.top=(e.clientY-46)+'px';});
 el.addEventListener('mouseleave',function(){tip.style.opacity='0';});
});
"""

BODY = """
<div class="wrap">
<header>
 <div class="eyebrow">Claude Code &middot; 169 sessions &middot; 12 Jul &#8211; 22 Aug 2026</div>
 <h1>Where the Tokens Went</h1>
 <p class="lede">A forensic read of 20,903 requests across every transcript on this machine &#8212;
 reconstructing why the weekly budget drains, before changing a single setting.</p>
</header>

<div class="stats">
 <div class="stat"><b>7.24B</b><span>tokens sent</span></div>
 <div class="stat"><b>20,903</b><span>model requests</span></div>
 <div class="stat"><b>169</b><span>sessions</span></div>
 <div class="stat"><b>289k</b><span>median context / request</span></div>
 <div class="stat"><b>96.7%</b><span>of input is cache re-reads</span></div>
</div>

<p class="thesis">Only 13% of the bill is Claude writing things. The other 87% is Claude re-reading
the conversation &#8212; 7.0 billion cache-read tokens, one accumulating context at a time.</p>

<section>
 <h2>What the spend is made of</h2>
 __PROP__
 __KEY__
 <p style="font-size:14px">Weighted by API-relative cost &#8212; cache reads &times;0.1, cache writes
 &times;1.25, output &times;5. Input tokens are 0.24M of 7,245M and too small to plot.</p>
</section>

<section>
 <h2>The cause &#8212; context compounds with every turn</h2>
 <p>Context grows about <b>2.4k tokens per request</b> and never shrinks. A session opens at 84k and
 crosses the 200k line around request 55. Every request re-sends the whole accumulation, so the shaded
 band is not a rate &#8212; it is volume paid for again on every single turn.</p>
 <div class="card chartwrap">__CTX__</div>
 <p style="font-size:14px">Median context by request position, pooled across all 169 sessions.
 Truncated at request 279; beyond that the sample thins and the tail distorts.</p>
</section>

<section>
 <h2>Daily burn</h2>
 <p>The threefold step change on <b>13 August</b> is a plan change, not a behaviour change &#8212;
 a Max-5 subscription became Max-20. Daily requests went from 300&#8211;700 to 1,400&#8211;2,000 because
 the ceiling moved; the 14th alone cost 110M weighted tokens. Read this as capacity being taken up,
 not as a regression.</p>
 <p>It does sharpen everything above, though. The inefficiencies are ratios &#8212; they do not care how
 many requests you make &#8212; so the same 289k median context now costs roughly three times as much
 in absolute terms as it did in July.</p>
 <div class="card chartwrap">__DAILY__</div>
</section>

<section>
 <h2>The levers, ranked by what they return</h2>
 <div class="levs">__LEV__</div>
</section>

<section>
 <h2>Agent configuration audit</h2>
 <p>You suspected model misalignment was driving cost. <b>It is not</b> &#8212; subagents are roughly
 1% of measured spend, so these are correctness and latency findings, not budget findings. Two are
 worth fixing anyway.</p>
 <div class="card" style="overflow-x:auto">
 <table><thead><tr><th>Agent</th><th>Model</th><th class="num">Calls</th><th>Status</th>
 <th>Note</th></tr></thead><tbody>__AROWS__</tbody></table>
 </div>
 <h3 style="margin-top:12px">Two vocabularies, one crew</h3>
 <p><b>Correction.</b> An earlier version of this page called these duplicates. They are not. The
 public framework ships functional names and the private instance runs the same crew under a
 <code>philosophers</code> theme, applied by a supported script &#8212; a documented feature, not drift.
 The similarity figures below measure how closely the two vocabularies track each other.</p>
 <div class="card" style="overflow-x:auto">
 <table><thead><tr><th>Functional</th><th>Themed</th><th class="num">Similarity</th></tr></thead>
 <tbody>__DROWS__</tbody></table>
 </div>
 <p style="margin-top:6px">One pair is worth a look: <code>reviewer</code>&#8202;/&#8202;<code>pyrrho</code>
 sits at 87%, against 99%+ for the others. That is either a deliberate divergence or real drift.</p>
 <p style="margin-top:6px">Two settings never vary across the whole corpus: <code>agentSetting</code>
 is <code>orchestrator</code> in all 3,815 records, and <code>effort</code> is <code>high</code> in all
 18,432. Every session runs a 12.8k-character coordinator prompt at maximum effort on Opus &#8212;
 including the ones that turn out to be a one-line question.</p>
</section>

<section>
 <h2>What this cannot tell you</h2>
 <div class="blind">
  <div><h3>Subagent spend is unmeasured</h3><p>1,842 <code>Agent</code> calls appear in the transcripts
  and <b>not one</b> records its internal token count. At a plausible 20&#8211;50k each that is
  37&#8211;92M tokens, 0.5&#8211;1.3% of the total &#8212; an estimate, not a measurement. It is the one
  number here that could not be verified.</p></div>
  <div><h3>The weighting is published, the accounting is not</h3><p>Since this page was first
  built, the multipliers have been checked against Anthropic's own pricing rather than inferred: Opus is
  $5.00/1M in and $25.00/1M out (the &times;5), with cache writes at &asymp;&times;1.25 and cache reads
  at &asymp;&times;0.1. What remains undocumented is whether <em>subscription weekly limits</em> use the
  same accounting as API billing. If they count <em>raw</em> tokens, cache reads are 96.7% of everything
  and lever 1 gets bigger, not smaller.</p></div>
  <div><h3>The source format is unofficial</h3><p>These figures are parsed from session
  <code>.jsonl</code> files that Anthropic documents as internal and version-unstable. The numbers are
  right today; the parser can break on any release.</p></div>
 </div>
</section>

<footer>Compiled from 172 transcript files (407&nbsp;MB) under <span class="mono">~/.claude/projects</span>.
Requests deduplicated by <span class="mono">requestId</span> &#8212; streaming writes each request several
times, and naive summing inflates every total by roughly 3&times;.</footer>
</div>
<div class="tip" id="tip"></div>
"""

body = (BODY.replace("__PROP__", prop).replace("__KEY__", key)
        .replace("__CTX__", ctx_chart).replace("__DAILY__", daily_chart)
        .replace("__LEV__", lev).replace("__AROWS__", arows).replace("__DROWS__", drows))

page = ('<title>Where the Tokens Went</title>\n'
        '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        'family=Archivo:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600&display=swap">\n'
        '<style>' + CSS + '</style>\n'
        + body
        + '<script>' + JS + '</script>\n')

with open(os.path.join(SCRIPT_DIR, 'dashboard.html'), 'w', encoding='utf-8') as fh:
    fh.write(page)
print("wrote %d bytes" % len(page))
