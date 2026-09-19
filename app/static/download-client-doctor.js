(()=>{
  const $=(id)=>document.getElementById(id);
  const esc=(v)=>String(v??'').replace(/[&<>'\"]/g,(c)=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));
  async function api(url){const r=await fetch(url,{credentials:'same-origin',cache:'no-store'});const d=await r.json().catch(()=>({}));if(!r.ok){if(r.status===401){location.href='/';throw new Error('Please sign in first.');}throw new Error(d.detail||`Request failed (${r.status})`);}return d;}
  function setNotice(message,ok=false){const n=$('notice');n.className=`notice ${ok?'success':'error'}`;n.textContent=message;}
  function suggestionBox(s){if(!s)return '';let body=`<p>${esc(s.message||'')}</p>`;if(s.remoteHost||s.remotePath){body+=`<small>Remote Path Mapping</small><code>Host: ${esc(s.remoteHost||'—')} · Remote: ${esc(s.remotePath||'—')}</code>`;}if(s.hostPath||s.containerPath){body+=`<small>Verified host ↔ container path</small><code>${esc(s.hostPath||'—')} → ${esc(s.containerPath||'—')}</code>`;}if(s.dockerMount){body+=`<small>Docker mount</small><code>${esc(s.dockerMount)}</code>`;}if(s.remotePathMapping){body+=`<small>Active Radarr/Sonarr mapping</small><code>${esc(s.remotePathMapping.host||'—')} : ${esc(s.remotePathMapping.remotePath||'—')} → ${esc(s.remotePathMapping.localPath||'—')}</code>`;}return `<div class="fix-hint"><strong>${s.verified?'Verified technical fix':'Technical mapping details'}</strong>${body}</div>`;}
  function guideBox(i){
    const f=i.friendly;
    if(!f)return `<p>${esc(i.message)}</p>${i.path?`<code>${esc(i.path)}</code>`:''}${suggestionBox(i.suggestion)}`;
    const steps=(f.steps||[]).map((s,n)=>`<li><span>${n+1}</span><p>${esc(s)}</p></li>`).join('');
    const a=f.advanced||{};
    const advanced=[
      i.rawMessage?`<p><b>Original app message</b><br><code>${esc(i.rawMessage)}</code></p>`:'',
      a.reportedPath?`<p><b>Downloader reported</b><br><code>${esc(a.reportedPath)}</code></p>`:'',
      a.mappedPath && a.mappedPath!==a.reportedPath?`<p><b>Radarr/Sonarr mapped path</b><br><code>${esc(a.mappedPath)}</code></p>`:'',
      a.dockerMount?`<p><b>Suggested Docker mount</b><br><code>${esc(a.dockerMount)}</code></p>`:''
    ].join('');
    return `<p class="plain-message">${esc(f.message)}</p><div class="impact"><strong>Why this matters</strong><p>${esc(f.impact||'')}</p></div><div class="recommended"><strong>Recommended fix</strong><p>${esc(f.recommended||'')}</p><ol class="fix-steps">${steps}</ol>${f.note?`<p class="friendly-note">${esc(f.note)}</p>`:''}</div><details class="advanced"><summary>Advanced details</summary><div>${advanced}${suggestionBox(i.suggestion)}</div></details>`;
  }
  function fixHint(p){return suggestionBox(p.suggestion);}
  function render(data){
    const items=data.items||[];const clients=items.flatMap(i=>i.clients||[]);const paths=items.flatMap(i=>i.queuePaths||[]);
    $('instanceCount').textContent=items.length;$('clientCount').textContent=clients.length;$('issueCount').textContent=data.issueCount||0;$('pathCount').textContent=paths.length;
    if(!items.length){$('results').innerHTML='<div class="surface empty"><strong>No Radarr/Sonarr instances</strong><p>Add Radarr or Sonarr first.</p></div>';return;}
    $('results').innerHTML=items.map(item=>{const issues=item.issues||[];
      const clientCards=(item.clients||[]).map(c=>`<div class="client-card"><div><strong>${esc(c.name)}</strong><small>${esc(c.implementation)} · ${c.enabled?'Enabled':'Disabled'}</small></div><code>${esc(c.host||'host unknown')}${c.port?`:${esc(c.port)}`:''}</code>${c.category?`<span>Category: ${esc(c.category)}</span>`:''}</div>`).join('')||'<div class="empty-mini">No download clients reported.</div>';
      const issueCards=issues.map(i=>`<article class="issue ${i.severity||'warning'}"><div class="issue-title"><span class="problem-dot">!</span><strong>${esc(i.title)}</strong></div>${guideBox(i)}</article>`).join('')||'<article class="issue ok"><strong>No download-folder problem detected</strong><p>ArrMedic did not receive a current path error from Radarr/Sonarr. If there is no active queue item, some paths cannot be fully verified yet.</p></article>';
      const pathRows=(item.queuePaths||[]).slice(0,30).map(p=>{const visible=p.visibility?.visible;return `<tr><td>${esc(p.title)}</td><td>${esc(p.downloadClient||'—')}</td><td><code>${esc(p.reportedPath||'—')}</code></td><td><code>${esc(p.mappedPath||'—')}</code>${fixHint(p)}</td><td>${p.remoteMapping?'Remote mapped':visible?'Host visible':'NOT MAPPED'}</td></tr>`;}).join('')||'<tr><td colspan="5">No active queue paths right now. ArrMedic will still show native Radarr/Sonarr path warnings above.</td></tr>';
      const mappings=(item.remotePathMappings||[]).map(m=>`<div class="mapping"><span>${esc(m.host||'host')}</span><code>${esc(m.remotePath||'—')}</code><b>→</b><code>${esc(m.localPath||'—')}</code></div>`).join('')||'<div class="empty-mini">No Remote Path Mappings configured.</div>';
      return `<section class="surface instance-block"><div class="instance-head"><div><span class="kicker">${esc(String(item.kind||'').toUpperCase())}</span><h2>${esc(item.instanceName||'Service')}</h2></div><span class="state ${issues.length?'bad':'good'}">${issues.length?`${issues.length} problem${issues.length===1?'':'s'}`:'Looks good'}</span></div><div class="tip beginner-tip"><strong>Simple rule</strong><p>Your download client and Radarr/Sonarr should normally see completed downloads at the same path, such as <code>/data/downloads</code>.</p></div><h3>Problems to fix</h3><div class="issue-grid">${issueCards}</div><details class="technical-section"><summary>Technical information</summary><h3>Download clients</h3><div class="client-grid">${clientCards}</div><h3>Remote Path Mappings</h3><div class="mapping-list">${mappings}</div><h3>Current queue paths</h3><div class="table-wrap"><table><thead><tr><th>Item</th><th>Client</th><th>Downloader reports</th><th>Radarr/Sonarr path + fix</th><th>Result</th></tr></thead><tbody>${pathRows}</tbody></table></div><div class="tip"><strong>Advanced path rule</strong><p>${esc(item.help?.samePathRule||'Use the same common path in the download client and *Arr containers.')}</p><p>${esc(item.help?.remotePathRule||'')}</p></div></details></section>`;
    }).join('');
  }
  async function scan(){const b=$('scanButton');b.disabled=true;b.textContent='Checking…';try{const data=await api('/api/doctors/download-clients');render(data);setNotice(data.issueCount?`Check complete. ${data.issueCount} problem(s) need attention.`:'Check complete. No current download-folder problem detected.',true);}catch(e){setNotice(e.message,false);}finally{b.disabled=false;b.textContent='Run checks';}}
  document.addEventListener('DOMContentLoaded',()=>{$('scanButton').addEventListener('click',scan);scan();});
})();
