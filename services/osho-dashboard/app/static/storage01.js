(() => {
  if (typeof NODES === 'undefined' || typeof pollNode === 'undefined') return;

  const originalPollNode = pollNode;
  const originalNodeHTML = nodeHTML;
  const originalRenderLists = renderLists;

  pollNode = async function(n){
    if(n.kind !== 'qnap') return originalPollNode(n);
    try{
      const d = await j('/api/storage/storage-01', 6500);
      const volume = Array.isArray(d.volumes) && d.volumes.length ? d.volumes[0] : null;
      nodeState[n.name] = {
        online: Boolean(d.online),
        qnap: true,
        status: d.status || 'unknown',
        cpu: d.cpu_percent,
        volume,
        capacity: volume?.total || n.capacity,
        free: volume?.free || null,
        usedPercent: volume?.used_percent,
        populated: d.populated_bays,
        bays: d.bay_count,
        empty: d.empty_bays,
        goodDisks: d.good_disks,
        temp: d.max_disk_temperature_c,
        disks: d.disks || [],
        message: d.message || '',
        snmpConfigured: Boolean(d.snmp_configured),
        qtsReachable: Boolean(d.qts_reachable)
      };
    }catch(e){
      nodeState[n.name] = {online:false,qnap:true,status:'offline',message:e.message};
    }
  };

  nodeHTML = function(n){
    if(n.kind !== 'qnap') return originalNodeHTML(n);
    const s = nodeState[n.name] || {};
    const healthy = s.status === 'healthy';
    const badge = !s.online ? ['Offline','bad'] : healthy ? ['Healthy',''] : s.status === 'unconfigured' ? ['Needs secret','warn'] : ['Degraded','warn'];
    const diskText = s.populated != null ? `${s.goodDisks ?? 0}/${s.populated} GOOD` : '—';
    const poolText = s.volume?.status || (s.snmpConfigured ? 'Unknown' : 'Pending');
    return `<article class="node"><div class="node-head"><div><h3>${n.label}</h3><div class="role">${n.role} · ${n.ip}</div></div><span class="badge ${badge[1]}">${badge[0]}</span></div><div class="metrics"><div class="metric"><span>CPU</span><b>${s.cpu!=null?Math.round(s.cpu)+'%':'—'}</b><div class="bar"><i style="width:${clamp(s.cpu)}%"></i></div></div><div class="metric"><span>Volume free</span><b>${s.free||'—'}</b><div class="bar"><i style="width:${clamp(s.usedPercent)}%"></i></div></div><div class="metric"><span>Disks</span><b>${diskText}</b></div><div class="metric"><span>Max temp</span><b>${s.temp!=null?s.temp.toFixed(0)+'°C':'—'}</b></div><div class="metric"><span>Pool</span><b>${poolText}</b></div></div></article>`;
  };

  function storageSummaryHTML(s){
    if(!s || !s.online){
      return `<div><div class="storage-line"><div><b>storage-01 NAS</b><div><small>QNAP TS-831X · 192.168.0.53<br>${s?.message||'SNMP telemetry unavailable'}</small></div></div><span class="badge bad">Unavailable</span></div><div class="bar"><i style="width:0%"></i></div></div>`;
    }
    if(!s.snmpConfigured){
      return `<div><div class="storage-line"><div><b>storage-01 NAS</b><div><small>QNAP TS-831X · 192.168.0.53<br>QTS reachable · SNMP secret not installed on compute-02</small></div></div><span class="badge warn">Setup</span></div><div class="bar"><i style="width:0%"></i></div></div>`;
    }
    const v=s.volume||{};
    const pct=v.used_percent!=null?v.used_percent:(s.usedPercent||0);
    const diskLine = `${s.goodDisks ?? 0}/${s.populated ?? 0} populated disks GOOD · ${s.empty ?? 0} empty bays`;
    return `<div><div class="storage-line"><div><b>storage-01 NAS</b><div><small>${v.name||'DataVol1 / Pool 1'} · ${v.filesystem||'EXT4'} · ${v.status||'Unknown'}<br>${v.free||'—'} free of ${v.total||'—'} · ${diskLine} · max ${s.temp!=null?s.temp.toFixed(0)+'°C':'—'}</small></div></div><b>${Math.round(pct)}%</b></div><div class="bar"><i style="width:${clamp(pct)}%"></i></div></div>`;
  }

  renderLists = function(){
    originalRenderLists();
    const list = document.getElementById('storageList');
    if(!list) return;
    const first = list.firstElementChild;
    if(first && first.textContent.includes('storage-01 NAS')){
      first.outerHTML = storageSummaryHTML(nodeState['storage-01']);
    }
  };

  // Re-run immediately so the enhanced QNAP card does not wait for the next 15s cycle.
  refresh();
})();
