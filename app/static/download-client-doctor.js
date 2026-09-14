(()=>{
  const $=(id)=>document.getElementById(id);
  const esc=(v)=>String(v??'').replace(/[&<>'\"]/g,(c)=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));
  async function api(url){const r=await fetch(url,{credentials:'same-origin',cache:'no-store'});const d=await r.json().catch(()=>({}));if(!r.ok){if(r.status===401){location.href='/';throw new Error('Please sign in first.');}throw new Error(d.detail||`Request failed (${r.status})`);}return d;}
  function setNotice(message,ok=false){const n=$('notice');n.className=`notice ${ok?'success':'error'}`;n.textContent=message;}
  function render(data){
    const items=data.items||[];
    const clients=items.flatMap(i=>i.clients||[]);
    const paths=items.flatMap(i=>i.queuePaths||[]);
    $('instanceCount').textContent=items.length;
    $('clientCount').textContent=clients.length;
    $('issueCount').textContent=data.issueCount||0;
    $('pathCount').textContent=paths.length;
    if(!items.length){$('results').innerHTML='<div class="surface empty"><strong>No Radarr/Sonarr instances</strong><p>Add Radarr or Sonarr first.</p></div>';return;}
    $('results').innerHTML=items.map(item=>{
      const issues=item.issues||[];
      const clientCards=(item.clients||[]).map(c=>`<div class="client-card"><div><strong>${esc(c.name)}</strong><small>${esc(c.implementation)} · ${c.enabled?'Enabled':'Disabled'}</small></div><code>${esc(c.host||'host unknown')}${c.port?`:${esc(c.port)}`:''}</code>${c.category?`<span>Category: ${esc(c.category)}</span>`:''}</div>`).join('')||'<div class="empty-mini">No download clients reported.</div>';
      const issueCards=issues.map(i=>`<article class="issue ${i.severity||'warning'}"><strong>${esc(i.title)}</strong><p>${esc(i.message)}</p>${i.path?`<code>${esc(i.path)}</code>`:''}</article>`).join('')||'<article class="issue ok"><strong>No path problem detected</strong><p>Current queue paths and mappings look consistent from the *Arr API view.</p></article>';
      const pathRows=(item.queuePaths||[]).slice(0,30).map(p=>`<tr><td>${esc(p.title)}</td><td>${esc(p.downloadClient||'—')}</td><td><code>${esc(p.reportedPath||'—')}</code></td><td><code>${esc(p.mappedPath||'—')}</code></td><td>${p.remoteMapping?'Mapped':'Direct'}</td></tr>`).join('')||'<tr><td colspan="5">No active queue paths to inspect.</td></tr>';
      const mappings=(item.remotePathMappings||[]).map(m=>`<div class="mapping"><span>${esc(m.host||'host')}</span><code>${esc(m.remotePath||'—')}</code><b>→</b><code>${esc(m.localPath||'—')}</code></div>`).join('')||'<div class="empty-mini">No Remote Path Mappings configured.</div>';
      return `<section class="surface instance-block"><div class="instance-head"><div><span class="kicker">${esc(String(item.kind||'').toUpperCase())}</span><h2>${esc(item.instanceName||'Service')}</h2></div><span class="state ${issues.length?'bad':'good'}">${issues.length?`${issues.length} issue${issues.length===1?'':'s'}`:'Looks good'}</span></div><h3>Download clients</h3><div class="client-grid">${clientCards}</div><h3>Detected problems</h3><div class="issue-grid">${issueCards}</div><h3>Remote Path Mappings</h3><div class="mapping-list">${mappings}</div><h3>Current queue paths</h3><div class="table-wrap"><table><thead><tr><th>Item</th><th>Client</th><th>Reported path</th><th>Path Radarr/Sonarr uses</th><th>Mode</th></tr></thead><tbody>${pathRows}</tbody></table></div><div class="tip"><strong>Recommended layout</strong><p>${esc(item.help?.samePathRule||'Use the same common path in the download client and *Arr containers.')}</p></div></section>`;
    }).join('');
  }
  async function scan(){const b=$('scanButton');b.disabled=true;b.textContent='Checking…';try{const data=await api('/api/doctors/download-clients');render(data);setNotice(`Check complete. ${data.issueCount||0} path/configuration issue(s) found.`,true);}catch(e){setNotice(e.message,false);}finally{b.disabled=false;b.textContent='Run checks';}}
  document.addEventListener('DOMContentLoaded',()=>{$('scanButton').addEventListener('click',scan);scan();});
})();
