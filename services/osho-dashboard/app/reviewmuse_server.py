from __future__ import annotations

import json
import urllib.error
import urllib.request

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

import live_power_server as base
import server as command_server

app = base.app
REVIEWMUSE_SUMMARY_URL = "http://192.168.0.158:8795/api/p2/summary"
COMMAND_PATHS = {
    "/", "/media", "/monitoring", "/network", "/storage", "/services",
    "/osho", "/reviewmuse", "/alerts",
}

REVIEWMUSE_STYLE = r"""
<style id="reviewmuse-style">
.rm-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:12px 0 14px}
.rm-kpi{border:1px solid var(--line);background:#0c1929;border-radius:10px;padding:12px}
.rm-kpi span{display:block;color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.07em}
.rm-kpi b{display:block;margin-top:5px;font-size:22px}
.rm-kpi small{display:block;color:var(--muted);margin-top:3px;font-size:10px}
.rm-grid{display:grid;grid-template-columns:1.3fr 1fr;gap:12px;margin-top:12px}
.rm-panel{border:1px solid var(--line);background:#0c1929;border-radius:10px;padding:12px}
.rm-panel h3{margin:0 0 10px;font-size:13px}
.rm-row{display:flex;justify-content:space-between;gap:12px;padding:8px 0;border-bottom:1px solid rgba(64,84,110,.35)}
.rm-row:last-child{border-bottom:0}.rm-row span{color:var(--muted)}.rm-row b{text-align:right}
.rm-note{margin-top:12px;padding:11px;border:1px solid rgba(90,167,255,.35);background:rgba(90,167,255,.08);border-radius:9px;color:#cfe4ff;font-size:11px;line-height:1.5}
.rm-foot{display:flex;justify-content:space-between;gap:12px;margin-top:12px;color:var(--muted);font-size:10px}
@media(max-width:1000px){.rm-kpis{grid-template-columns:repeat(2,1fr)}.rm-grid{grid-template-columns:1fr}}
@media(max-width:600px){.rm-kpis{grid-template-columns:1fr}}
</style>
"""

REVIEWMUSE_PANEL = r"""
<section class="section page-block" data-pages="reviewmuse" id="reviewmuseSection">
  <div class="section-head">
    <div><h2>ReviewMuse</h2><div class="muted">Outreach, human demo engagement, site traffic and pilot pipeline</div></div>
    <span class="badge" id="rmStatus">Loading</span>
  </div>
  <div class="rm-kpis">
    <div class="rm-kpi"><span>Outreach emails sent</span><b id="rmSent">—</b><small id="rmSent7">—</small></div>
    <div class="rm-kpi"><span>Human demo clicks</span><b id="rmHumanClicks">—</b><small id="rmClickRate">—</small></div>
    <div class="rm-kpi"><span>Human site visitors</span><b id="rmSiteVisitors">—</b><small id="rmSite24">—</small></div>
    <div class="rm-kpi"><span>Replies</span><b id="rmReplies">—</b><small id="rmReplyRate">—</small></div>
    <div class="rm-kpi"><span>Demo links sent</span><b id="rmDemoLinks">—</b><small id="rmNoLink">—</small></div>
    <div class="rm-kpi"><span>Customer-flow visitors</span><b id="rmExperience">—</b><small>Confirmed post-tracking</small></div>
    <div class="rm-kpi"><span>Pilot form submissions</span><b id="rmPilots">—</b><small id="rmQualified">—</small></div>
    <div class="rm-kpi"><span>Activation clicks</span><b id="rmActivations">—</b><small>Confirmed post-tracking</small></div>
  </div>
  <div class="rm-grid">
    <div class="rm-panel">
      <h3>Engagement funnel</h3>
      <div class="rm-row"><span>Demo links sent</span><b id="rmFunnelSent">—</b></div>
      <div class="rm-row"><span>Human-confirmed demo clicks</span><b id="rmFunnelHuman">—</b></div>
      <div class="rm-row"><span>Customer flow opened</span><b id="rmFunnelExperience">—</b></div>
      <div class="rm-row"><span>AI draft completed</span><b id="rmDrafts">—</b></div>
      <div class="rm-row"><span>Google handoff viewed</span><b id="rmHandoffs">—</b></div>
      <div class="rm-row"><span>Activation CTA clicked</span><b id="rmActivate2">—</b></div>
    </div>
    <div class="rm-panel">
      <h3>Tracking quality</h3>
      <div class="rm-row"><span>Legacy raw demo opens</span><b id="rmLegacy">—</b></div>
      <div class="rm-row"><span>Post-tracking scanner opens</span><b id="rmScanners">—</b></div>
      <div class="rm-row"><span>Site page views</span><b id="rmPageViews">—</b></div>
      <div class="rm-row"><span>Meetings booked</span><b id="rmMeetings">—</b></div>
      <div class="rm-row"><span>Unsubscribes</span><b id="rmUnsubs">—</b></div>
      <div class="rm-row"><span>Tracking started</span><b id="rmTrackingStart">—</b></div>
    </div>
  </div>
  <div class="rm-note">Human demo clicks are counted only after a trusted in-page interaction. Older preview telemetry is kept as raw/unclassified because it cannot reliably distinguish a person from email-security scanners or internal testing.</div>
  <div class="rm-foot"><span>Source: ReviewMuse production on compute-03</span><span id="rmUpdated">Waiting for first refresh…</span></div>
</section>
<script id="reviewmuse-script">
(() => {
  const $=id=>document.getElementById(id);
  const n=v=>Number(v||0).toLocaleString();
  const pct=v=>`${Number(v||0).toFixed(1)}%`;
  const when=v=>v?new Date(v).toLocaleString():'—';
  async function refreshReviewMuse(){
    try{
      const r=await fetch('/api/reviewmuse/summary',{cache:'no-store'});
      if(!r.ok) throw new Error(`HTTP ${r.status}`);
      const d=await r.json(),o=d.outreach||{},m=d.demo||{},s=d.site||{},p=d.pipeline||{};
      $('rmStatus').textContent='Healthy';$('rmStatus').className='badge';
      $('rmSent').textContent=n(o.sent_total);$('rmSent7').textContent=`${n(o.sent_last_7d)} in last 7 days`;
      $('rmHumanClicks').textContent=n(m.human_clicks);$('rmClickRate').textContent=`${pct(m.human_click_rate)} of demo links`;
      $('rmSiteVisitors').textContent=n(s.human_visitors);$('rmSite24').textContent=`${n(s.human_visitors_24h)} in last 24h`;
      $('rmReplies').textContent=n(o.replies);$('rmReplyRate').textContent=`${pct(o.reply_rate)} reply rate`;
      $('rmDemoLinks').textContent=n(o.demo_links_sent);$('rmNoLink').textContent=`${n(o.no_link_first_touch)} no-link first touches`;
      $('rmExperience').textContent=n(m.experience_visitors);$('rmPilots').textContent=n(p.pilot_form_submissions);$('rmQualified').textContent=`${n(p.qualified_pilots)} qualified`;
      $('rmActivations').textContent=n(m.activation_click_visitors);
      $('rmFunnelSent').textContent=n(o.demo_links_sent);$('rmFunnelHuman').textContent=n(m.human_clicks);$('rmFunnelExperience').textContent=n(m.experience_visitors);
      $('rmDrafts').textContent=n(m.ai_draft_visitors);$('rmHandoffs').textContent=n(m.handoff_visitors);$('rmActivate2').textContent=n(m.activation_click_visitors);
      $('rmLegacy').textContent=n(m.legacy_unclassified_opens);$('rmScanners').textContent=n(m.scanner_opens);$('rmPageViews').textContent=n(s.page_views);
      $('rmMeetings').textContent=n(o.meetings);$('rmUnsubs').textContent=n(o.unsubscribed);$('rmTrackingStart').textContent=when(d.tracking_started_at);
      $('rmUpdated').textContent='Updated '+new Date().toLocaleTimeString();
    }catch(e){$('rmStatus').textContent='Unavailable';$('rmStatus').className='badge bad';$('rmUpdated').textContent='Metrics unavailable: '+e.message;}
  }
  refreshReviewMuse();setInterval(refreshReviewMuse,30000);
})();
</script>
"""


def _command_center_html(path: str) -> str:
    html = (command_server.base.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    nav_anchor = '<a data-page="osho" href="/osho">◈ Project Osho</a>'
    if 'data-page="reviewmuse"' not in html:
        html = html.replace(nav_anchor, nav_anchor + '\n<a data-page="reviewmuse" href="/reviewmuse">✦ ReviewMuse</a>', 1)
    html = html.replace("'/osho':'osho','/alerts':'alerts'", "'/osho':'osho','/reviewmuse':'reviewmuse','/alerts':'alerts'", 1)
    html = html.replace(" alerts:['Alerts','Items that currently need attention and recent Osho activity']", " reviewmuse:['ReviewMuse','Outreach, human demo engagement, site traffic and pilot pipeline'],\n alerts:['Alerts','Items that currently need attention and recent Osho activity']", 1)
    if 'id="reviewmuse-style"' not in html:
        html = html.replace('</head>', REVIEWMUSE_STYLE + '\n</head>', 1)
    if 'id="reviewmuseSection"' not in html:
        html = html.replace('</main>', REVIEWMUSE_PANEL + '\n</main>', 1)
    if path == '/osho':
        if 'id="osho-progress-style"' not in html:
            html = html.replace('</head>', command_server.OSHO_PROGRESS_STYLE + '\n</head>', 1)
        if 'id="oshoLiveProcessing"' not in html:
            html = html.replace('</main>', command_server.OSHO_PROGRESS_PANEL + '\n</main>', 1)
    return html


@app.middleware('http')
async def reviewmuse_command_center_middleware(request: Request, call_next):
    if request.url.path in COMMAND_PATHS:
        return HTMLResponse(_command_center_html(request.url.path), headers={'Cache-Control':'no-store'})
    return await call_next(request)


@app.get('/api/reviewmuse/summary')
def reviewmuse_summary():
    try:
        req = urllib.request.Request(REVIEWMUSE_SUMMARY_URL, headers={'User-Agent':'P2-Dashboard-ReviewMuse/1.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f'ReviewMuse metrics returned HTTP {exc.code}') from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise HTTPException(status_code=502, detail='ReviewMuse metrics unavailable') from exc
