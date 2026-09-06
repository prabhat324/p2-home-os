(() => {
  // The outer ReviewMuse command-center middleware serves index.html directly,
  // so the older storage middleware cannot inject storage01.js. Load the
  // existing infrastructure overlay from this script, which is already present
  // on every command-center page. The overlay adds media-01 and storage telemetry.
  if (!document.querySelector('script[src^="/assets/storage01.js"]')) {
    const infrastructureScript = document.createElement('script');
    infrastructureScript.src = '/assets/storage01.js?v=20260906-media01';
    infrastructureScript.async = false;
    document.head.appendChild(infrastructureScript);
  }

  const path = location.pathname;
  if (!['/', '/monitoring'].includes(path)) return;

  const style = document.createElement('style');
  style.textContent = `
    .power-grid{margin-bottom:16px}
    .power-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-bottom:12px}
    .power-summary>div,.g50-card{border:1px solid var(--line);background:#0c1929;border-radius:10px;padding:11px}
    .power-summary span,.g50-metric span{display:block;color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.06em}
    .power-summary b{display:block;margin-top:5px;font-size:15px}
    .g50-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
    .g50-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}
    .g50-head h3{margin:0;font-size:14px}
    .g50-head p{margin:3px 0 0;color:var(--muted);font-size:10px}
    .g50-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:12px}
    .g50-metric b{display:block;margin-top:4px;font-size:12px;overflow-wrap:anywhere}
    .g50-note{margin-top:10px;color:var(--muted);font-size:10px;line-height:1.45}
    .power-foot{margin-top:10px;color:var(--muted);font-size:10px;display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap}
    @media(max-width:900px){.power-summary{grid-template-columns:repeat(2,1fr)}.g50-list{grid-template-columns:1fr}}
    @media(max-width:520px){.g50-metrics{grid-template-columns:repeat(2,1fr)}}
  `;
  document.head.appendChild(style);

  const section = document.createElement('section');
  section.className = 'section power-grid';
  section.id = 'powerGridSection';
  section.innerHTML = `
    <div class="section-head">
      <div>
        <h2>⚡ Power & Grid Cost</h2>
        <div class="muted">G50 #1 + G50 #2 · Wasaga Distribution · Ontario Time-of-Use</div>
      </div>
      <span class="badge" id="powerGridBadge">Checking</span>
    </div>
    <div class="power-summary">
      <div><span>Current TOU period</span><b id="powerTouPeriod">—</b></div>
      <div><span>TOU energy rate</span><b id="powerTouRate">—</b></div>
      <div><span>Incremental grid cost today</span><b id="powerCostToday">—</b></div>
      <div><span>Grid cost this month</span><b id="powerCostMonth">—</b></div>
    </div>
    <div class="g50-list" id="g50List">
      <div class="empty-note">Loading G50 telemetry…</div>
    </div>
    <div class="power-foot">
      <span id="powerTariffDetail">Loading tariff details…</span>
      <span id="powerUpdated">Waiting for telemetry</span>
    </div>
  `;

  const anchor = document.getElementById('cardsSection') || document.getElementById('oshoSection');
  if (anchor) anchor.parentNode.insertBefore(section, anchor);
  else document.querySelector('main')?.appendChild(section);

  const money = v => Number.isFinite(Number(v)) ? '$' + Number(v).toFixed(3) : '—';
  const kwh = v => Number.isFinite(Number(v)) ? Number(v).toFixed(3) + ' kWh' : '—';
  const watts = v => Number.isFinite(Number(v)) ? Math.round(Number(v)).toLocaleString() + ' W' : '—';
  const amps = v => Number.isFinite(Number(v)) ? Number(v).toFixed(1) + ' A' : '—';

  function stateBadge(d){
    if (d.telemetry === 'metered') return ['Metered',''];
    if (d.online && d.snmp) return ['Online · meter pending','warn'];
    return ['Setup needed','warn'];
  }

  function g50Card(d){
    const badge = stateBadge(d);
    const detail = d.message || (d.telemetry === 'metered' ? 'Live meter telemetry is being integrated into kWh and incremental grid-cost totals.' : '');
    const identity = [d.model, d.serial ? `SN ${d.serial}` : null].filter(Boolean).join(' · ') || 'APC G50';
    return `<article class="g50-card">
      <div class="g50-head">
        <div><h3>${d.label || d.id}</h3><p>${d.ip} · ${identity}</p></div>
        <span class="badge ${badge[1]}">${badge[0]}</span>
      </div>
      <div class="g50-metrics">
        <div class="g50-metric"><span>Live power</span><b>${watts(d.watts)}</b></div>
        <div class="g50-metric"><span>Current</span><b>${amps(d.current_a)}</b></div>
        <div class="g50-metric"><span>Energy today</span><b>${kwh(d.kwh_today)}</b></div>
        <div class="g50-metric"><span>Grid cost today</span><b>${money(d.bill_cost_today_cad)}</b></div>
      </div>
      <div class="g50-note">${detail || 'No active warning.'}</div>
    </article>`;
  }

  async function refreshPower(){
    const badge = document.getElementById('powerGridBadge');
    try {
      const r = await fetch('/api/power/g50', {cache:'no-store'});
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      const t = d.tariff || {}, total = d.totals || {};
      document.getElementById('powerTouPeriod').textContent = `${t.label || '—'} · ${t.season || '—'}`;
      document.getElementById('powerTouRate').textContent =
        t.rate_cents_per_kwh != null ? `${Number(t.rate_cents_per_kwh).toFixed(1)}¢/kWh` : '—';
      document.getElementById('powerCostToday').textContent = money(total.bill_cost_today_cad);
      document.getElementById('powerCostMonth').textContent = money(total.bill_cost_month_cad);
      document.getElementById('g50List').innerHTML = (d.devices || []).map(g50Card).join('') ||
        '<div class="empty-note">No G50 devices configured.</div>';
      document.getElementById('powerTariffDetail').textContent =
        `Incremental all-in variable rate ${Number(t.bill_equivalent_variable_rate_cents_per_kwh || 0).toFixed(2)}¢/kWh now · fixed household charges ignored`;
      document.getElementById('powerUpdated').textContent =
        `Updated ${new Date(d.updated_at).toLocaleTimeString([], {hour:'numeric', minute:'2-digit', second:'2-digit'})}`;
      const metered = Number(total.metered_devices || 0);
      badge.textContent = metered === 2 ? 'Live' : metered === 1 ? '1/2 Metered' : 'Meter setup';
      badge.className = 'badge' + (metered === 2 ? '' : ' warn');
    } catch (e) {
      badge.textContent = 'Unavailable';
      badge.className = 'badge bad';
      document.getElementById('g50List').innerHTML =
        `<div class="empty-note">Power telemetry unavailable: ${String(e.message || e)}</div>`;
    }
  }

  refreshPower();
  setInterval(refreshPower, 15000);
})();