"""Generates the AWS-style architecture diagram (SVG)."""
from html import escape

W, H = 1900, 1330
out = []
A = out.append

C = {
    "compute": "#ED7100", "network": "#8C4FFF", "db": "#C925D1", "storage": "#7AA116",
    "integration": "#E7157B", "mgmt": "#E7157B", "security": "#DD344C", "ai": "#01A88D",
    "external": "#545B64", "ink": "#16191F", "muted": "#545B64", "line": "#232F3E",
}

def text(x, y, s, size=12, weight=400, fill=C["ink"], anchor="start", italic=False):
    st = ' font-style="italic"' if italic else ""
    A(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
      f'text-anchor="{anchor}"{st}>{escape(s)}</text>')

def group(x, y, w, h, label, stroke, fill="none", dash=None, tile=None, label_color=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    A(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{stroke}" stroke-width="1.6"{d}/>')
    tx = x + 10
    if tile:
        A(f'<rect x="{x}" y="{y}" width="26" height="26" fill="{stroke}"/>')
        text(x + 13, y + 17.5, tile, 10, 700, "#fff", "middle")
        tx = x + 34
    text(tx, y + 18, label, 13, 600, label_color or stroke)

def card(x, y, w, h, title, lines, color, glyph, dashed=False, title_size=14):
    d = ' stroke-dasharray="6 4"' if dashed else ""
    A(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="#FFFFFF" stroke="{color}" stroke-width="1.4"{d}/>')
    A(f'<rect x="{x+10}" y="{y+10}" width="34" height="34" rx="5" fill="{color}"/>')
    text(x + 27, y + 32, glyph, 11 if len(glyph) > 2 else 13, 700, "#fff", "middle")
    text(x + 54, y + 24, title, title_size, 700)
    for i, ln in enumerate(lines):
        text(x + 54, y + 41 + i * 15, ln, 11.5, 400, C["muted"])

def arrow(points, label=None, lx=None, ly=None, dashed=False, color=None, both=False, lanchor="middle"):
    color = color or C["line"]
    d = ' stroke-dasharray="5 4"' if dashed else ""
    pts = " ".join(f"{x},{y}" for x, y in points)
    ms = ' marker-start="url(#arrowStart)"' if both else ""
    A(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.6"{d} '
      f'marker-end="url(#arrow)"{ms}/>')
    if label:
        if lx is None:
            (x1, y1), (x2, y2) = points[0], points[-1]
            lx, ly = (x1 + x2) / 2, (y1 + y2) / 2 - 6
        w = len(label) * 6.1 + 10
        bx = lx - w / 2 if lanchor == "middle" else lx - 5
        A(f'<rect x="{bx}" y="{ly-11}" width="{w}" height="15" rx="3" fill="#FFFFFF" opacity="0.92"/>')
        text(lx, ly, label, 10.5, 500, C["muted"], lanchor)

def badge(x, y, n):
    A(f'<circle cx="{x}" cy="{y}" r="11" fill="#232F3E"/>')
    text(x, y + 4, str(n), 11.5, 700, "#fff", "middle")

A(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
  f'font-family="Inter, \'Helvetica Neue\', Arial, sans-serif">')
A('<defs>'
  '<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
  '<path d="M0,0 L10,5 L0,10 z" fill="#232F3E"/></marker>'
  '<marker id="arrowStart" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
  '<path d="M0,0 L10,5 L0,10 z" fill="#232F3E"/></marker>'
  '</defs>')
A(f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>')

# ---------- title ----------
text(40, 46, "AI-Powered Stock Market Research & Analysis Platform: AWS Architecture", 24, 700)
text(40, 72, "Phase 1: single EC2 host running Docker Compose (same stack as local development) · NASDAQ-listed securities only", 13.5, 400, C["muted"])

# ---------- groups ----------
group(280, 100, 1240, 985, "AWS Cloud", "#232F3E", tile="AWS")
group(298, 140, 1202, 925, "Region: us-east-1", "#00A4A6", dash="7 5")
group(470, 172, 850, 748, "VPC  10.0.0.0/16", "#8C4FFF", tile="VPC")
group(488, 212, 817, 693, "Public subnet · Security group: inbound 443/80 only", "#7AA116", fill="#F2F8EF")
group(508, 252, 782, 638, "EC2  ·  m7i-flex.large (8 GB RAM)  ·  Docker Compose", "#ED7100", fill="#FFFFFF", tile="EC2")

# ---------- left: users + github ----------
card(40, 300, 190, 80, "Users", ["Browser · React SPA", "Simple / Detailed mode"], C["external"], "USR")
card(40, 945, 190, 95, "GitHub", ["Repo + Pull Requests", "Actions: lint · test · build"], C["external"], "GH")

# ---------- route 53 ----------
card(315, 300, 145, 80, "Route 53", ["DNS · domain"], C["network"], "R53", title_size=13)

# ---------- EC2 containers ----------
c1, c2, c3, cw = 530, 790, 1050, 220
card(c1, 300, cw, 80, "Nginx", ["TLS · React static files", "reverse proxy /api"], C["network"], "NGX")
card(c2, 300, cw, 80, "FastAPI API", ["REST + SSE stream", "JWT auth · rate limits"], C["compute"], "API")
card(c3, 300, cw, 115, "Agent Harness", ["context · planner loop", "permissions · approvals", "grounding validator", "sources + disclaimer"], C["ai"], "AI")

card(c1, 430, cw, 75, "Celery Beat", ["scheduled data refresh"], C["integration"], "BEAT")
card(c2, 430, cw, 75, "Redis", ["Celery broker · cache", "progress pub/sub"], C["db"], "RDS")
card(c3, 440, cw, 75, "LLM Gateway", ["LiteLLM · OpenAI API", "provider set in .env"], C["ai"], "LLM")

card(c1, 545, cw, 150, "PostgreSQL", ["users · conversations", "tool-call audit log", "approvals · jobs", "job results (JSONB)", "OHLCV + XBRL cache"], C["db"], "PG")
A(f'<rect x="{c1}" y="705" width="{cw}" height="30" rx="4" fill="#F2F8EF" stroke="{C["storage"]}" stroke-width="1.2"/>')
text(c1 + cw/2, 724, "EBS gp3 volume · daily snapshots", 11, 600, C["storage"], "middle")
card(c2, 545, cw, 95, "Celery Workers", ["queues: analysis, ingest,", "sandbox · auto retries", "idempotent tasks"], C["integration"], "WRK")
card(c3, 545, cw, 112, "Financial Analysis MCP", ["custom MCP server", "prices · indicators", "statements · compare", "scenario · run_python"], C["ai"], "MCP", title_size=12.5)

card(c2, 665, cw, 70, "Sandbox Runner", ["only service with", "access to Docker socket"], C["compute"], "SBX")
card(c3, 685, cw, 70, "Flower", ["queue monitoring", "(internal only)"], C["integration"], "FLW")

card(c2, 770, cw, 105, "Python sandboxes", ["1 container per run", "no network · read-only FS", "512 MB · 1 CPU · 30 s", "non-root · caps dropped"], C["security"], "PY", dashed=True)
text(c1, 795, "Private Docker network:", 11.5, 700, C["muted"])
text(c1, 811, "only Nginx publishes ports.", 11.5, 400, C["muted"])
text(c1, 827, "Redis, Postgres, MCP and", 11.5, 400, C["muted"])
text(c1, 843, "Sandbox Runner stay internal.", 11.5, 400, C["muted"])

# ---------- region services row ----------
rs_y, rs_w, rs_h = 950, 180, 92
regions = [
    (312, "Amazon ECR", ["container images"], C["compute"], "ECR"),
    (508, "Systems Manager", ["Run Command deploy", "Session Manager"], C["mgmt"], "SSM"),
    (706, "Parameter Store", ["API keys · secrets", "loaded at startup"], C["mgmt"], "PS"),
    (904, "Amazon S3", ["reports · exports", "results · backups"], C["storage"], "S3"),
    (1102, "CloudWatch", ["container logs", "metrics · alarms"], C["mgmt"], "CW"),
    (1300, "IAM role", ["instance profile", "least privilege"], C["security"], "IAM"),
]
for x, t, ls, col, g in regions:
    card(x, rs_y, rs_w, rs_h, t, ls, col, g, title_size=13)

# ---------- external services ----------
ex = 1555
text(ex, 282, "External services", 14, 700, C["muted"])
A(f'<rect x="{ex-12}" y="262" width="335" height="508" rx="8" fill="#F7F8F8" stroke="#D5DBDB" stroke-width="1.2"/>')
text(ex, 282, "External services", 14, 700, C["muted"])
ext = [
    (300, "Alpha Vantage MCP", ["official remote MCP server", "quotes · time series · indicators"], "AV"),
    (395, "LLM providers", ["Ollama (local dev)", "hosted API (demo)"], "LLM"),
    (490, "SEC EDGAR XBRL API", ["statements · filings (official)", "≤10 req/s · User-Agent"], "SEC"),
    (585, "Yahoo Finance (yfinance)", ["OHLCV prices · dev source", "unofficial → cached"], "YF"),
    (680, "Nasdaq symbol directory", ["nasdaqlisted.txt", "NASDAQ-only ticker universe"], "NDQ"),
]
for y, t, ls, g in ext:
    card(ex, y, 310, 78, t, ls, C["external"], g, title_size=13)

# ---------- arrows: request path ----------
arrow([(230, 340), (315, 340)])
text(254, 333, "DNS", 10.5, 500, C["muted"], "middle")
badge(250, 362, 1)
arrow([(460, 340), (530, 340)], "HTTPS", 495, 333)
arrow([(c1+cw, 340), (c2, 340)], both=True)
badge((c1+cw+c2)/2, 318, 2)
arrow([(c2+cw, 340), (c3, 340)])
badge((c2+cw+c3)/2, 318, 3)

hx = c3 + cw/2
arrow([(hx, 415), (hx, 440)])
arrow([(c3+cw, 477), (1555, 434)], "prompt + tool schemas", 1410, 446)
badge(c3+cw+20, 498, 4)
arrow([(c3+cw, 330), (1555, 339)], "MCP (HTTP)", 1410, 327)
badge(c3+cw+20, 312, 5)
arrow([(c3, 395), (c3-18, 395), (c3-18, 565), (c3, 565)])
arrow([(c3+cw, 580), (1555, 529)])
arrow([(c3+cw, 600), (1555, 624)])
arrow([(c3+cw, 620), (1555, 719)])
text(1400, 590, "fetch + cache", 10.5, 500, C["muted"], "middle")

mx = c2 + cw/2
arrow([(mx, 380), (mx, 430)], both=True)
text(mx + 9, 409, "enqueue · progress", 10.5, 500, C["muted"])
badge(mx - 16, 405, 6)
arrow([(c1+cw, 467), (c2, 467)])
arrow([(mx, 505), (mx, 545)])
text(mx + 9, 530, "consume", 10.5, 500, C["muted"])
badge(mx - 16, 525, 7)
arrow([(c2+cw, 605), (c3, 605)])
arrow([(c2, 590), (c1+cw, 590)])
badge((c1+cw+c2)/2, 614, 8)
arrow([(mx, 640), (mx, 665)])
arrow([(mx, 735), (mx, 770)])
text(mx + 9, 757, "docker run", 10.5, 500, C["muted"])

# ---------- arrows: platform services ----------
arrow([(230, 992), (312, 992)])
text(258, 984, "push", 10.5, 500, C["muted"], "middle")
badge(250, 1016, 9)
arrow([(402, 950), (402, 870), (508, 870)], "pull", 440, 862)
for cx, lab, up in [(598, "deploy", True), (796, "secrets", True), (994, "results · backups", None), (1192, "logs", False)]:
    if up is None:
        arrow([(cx, 950), (cx, 890)], dashed=True, both=True)
    elif up:
        arrow([(cx, 950), (cx, 890)], dashed=True)
    else:
        arrow([(cx, 890), (cx, 950)], dashed=True)
    text(cx + 6, 925, lab, 10.5, 500, C["muted"])

# ---------- legend ----------
ly = 1110
A(f'<rect x="40" y="{ly}" width="1820" height="200" rx="8" fill="#F7F8F8" stroke="#D5DBDB" stroke-width="1.2"/>')
text(60, ly + 30, "Request and data flow", 15, 700)
steps = [
    "User opens the app; Route 53 resolves the domain and Nginx terminates TLS.",
    "Nginx serves the React app and proxies /api to FastAPI; answers stream back over SSE.",
    "FastAPI hands the message to the Agent Harness (context, planner loop, policy engine).",
    "The harness calls the LLM through the gateway; the provider is a .env setting.",
    "Tool calls go through MCP: the custom Financial Analysis server (SEC EDGAR, yfinance, Nasdaq list) and Alpha Vantage MCP.",
    "Long or approval-required analyses become Celery jobs in Redis; progress returns via Redis pub/sub → SSE.",
    "Workers fetch data through MCP and send code to the Sandbox Runner, which starts an isolated, no-network container.",
    "Results are saved in Postgres (small) or S3 (large); the grounding validator checks every number before the answer is sent.",
    "CI/CD: GitHub Actions tests and builds images → ECR → Systems Manager deploys to EC2 (docker compose pull + up).",
]
colw = 900
for i, s in enumerate(steps):
    col = 0 if i < 5 else 1
    row = i if i < 5 else i - 5
    x = 70 + col * colw
    y = ly + 62 + row * 27
    badge(x, y - 4, i + 1)
    text(x + 20, y, s, 12.5, 400, C["ink"])

# category key
kx, ky = 70 + colw, ly + 62 + 4 * 27 + 4
keys = [("AI / agent", C["ai"]), ("Compute", C["compute"]), ("Networking", C["network"]), ("Database", C["db"]),
        ("Storage", C["storage"]), ("Integration / mgmt", C["integration"]), ("Security", C["security"]), ("External", C["external"])]
x = kx - 10
for name, col in keys:
    A(f'<rect x="{x}" y="{ky-11}" width="14" height="14" rx="3" fill="{col}"/>')
    text(x + 20, ky, name, 11.5, 500, C["muted"])
    x += 20 + len(name) * 6.6 + 18

A("</svg>")
import os, sys
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "aws-architecture.svg")
open(OUT, "w").write("\n".join(out))
print("ok")
