(()=>{
  const esc=(v)=>String(v??'').replace(/[&<>'"]/g,(c)=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  const byId=(id)=>document.getElementById(id);
  let issueState={items:[],filter:'all'};

  function currentDiagnostics(){
    try{return typeof diagnostics!=='undefined'?diagnostics:null;}catch(_){return null;}
  }
  function currentInstances(){
    try{return typeof instances!=='undefined'?instances:[];}catch(_){return [];}
  }
  function apiLocal(url,options={}){
    return fetch(url,{credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json',...(options.headers||{})},...options}).then(async r=>{const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||`Request failed (${r.status})`);return d;});
  }
  function issueSeverity(status){return status==='fail'?'critical':status==='warn'?'warning':'info';}
  function issueTitle(check){return check?.title||check?.code||'Detected issue';}

  function flattenIssues(summary){
    const out=[];
    (summary?.instances||[]).forEach((report)=>{
      const recommendations=report.recommendations||[];
      const recByCode=new Map(recommendations.map((r)=>[r.code,r]));
      (report.checks||[]).forEach((check)=>{
        if(!['warn','fail'].includes(check.status))return;
        const code=String(check.code||'issue');
        let recommendation=recommendations.find((r)=>String(r.code||'').includes(code.replace(/^check_/,'').replace(/^fix_/,'')))||null;
        if(!recommendation&&code==='connection')recommendation=recByCode.get('fix_connection')||recommendations.find((r)=>r.priority==='high');
        out.push({
          id:`${report.instanceId}:${code}`,
          instanceId:Number(report.instanceId),service:report.name,kind:report.kind,url:report.url,
          severity:issueSeverity(check.status),code,title:issueTitle(check),message:check.message||'Needs attention',
          recommendation
        });
      });
      Object.entries(report.doctors||{}).forEach(([doctor,info])=>{
        if(!['warn','fail'].includes(info?.status))return;
        const id=`${report.instanceId}:doctor:${doctor}`;
        if(out.some((x)=>x.id===id))return;
        const recommendation=recommendations.find((r)=>String(r.code||'').includes(doctor))||null;
        out.push({id,instanceId:Number(report.instanceId),service:report.name,kind:report.kind,url:report.url,severity:issueSeverity(info.status),code:`${doctor}_doctor`,title:`${doctor.charAt(0).toUpperCase()+doctor.slice(1)} Doctor`,message:info.message||'Needs attention',recommendation});
      });
    });
    const rank={critical:0,warning:1,info:2};
    return out.sort((a,b)=>rank[a.severity]-rank[b.severity]||a.service.localeCompare(b.service));
  }

  function ensureModal(){
    if(byId('issueCenterModal'))return;
    document.body.insertAdjacentHTML('beforeend',`
      <div id="issueCenterModal" class="issue-center-modal hidden" aria-hidden="true">
        <div class="issue-center-panel glass" role="dialog" aria-modal="true" aria-labelledby="issueCenterTitle">
          <header class="issue-center-head">
            <div><span class="kicker">ISSUE CENTER</span><h2 id="issueCenterTitle">Detected problems</h2><p>Review what ArrMedic found and follow the safest fix for each issue.</p></div>
            <button id="closeIssueCenter" class="close-button" aria-label="Close">×</button>
          </header>
          <div class="issue-toolbar">
            <div class="issue-filters">
              <button class="issue-filter active" data-issue-filter="all">All <span id="issueAllCount">0</span></button>
              <button class="issue-filter" data-issue-filter="critical">Critical <span id="issueCriticalCount">0</span></button>
              <button class="issue-filter" data-issue-filter="warning">Warnings <span id="issueWarningCount">0</span></button>
            </div>
            <button id="issueRescan" class="button secondary small">Run new scan</button>
          </div>
          <div id="issueCenterList" class="issue-center-list"></div>
        </div>
      </div>
      <div id="issueFixModal" class="issue-fix-modal hidden" aria-hidden="true">
        <div class="issue-fix-panel glass" role="dialog" aria-modal="true">
          <header class="issue-center-head"><div><span class="kicker">FIX ISSUE</span><h2 id="issueFixTitle">Guided fix</h2><p id="issueFixSubtitle"></p></div><button id="closeIssueFix" class="close-button">×</button></header>
          <div id="issueFixBody"></div>
        </div>
      </div>`);
  }

  function renderIssues(){
    ensureModal();
    const items=issueState.filter==='all'?issueState.items:issueState.items.filter((i)=>i.severity===issueState.filter);
    byId('issueAllCount').textContent=issueState.items.length;
    byId('issueCriticalCount').textContent=issueState.items.filter((i)=>i.severity==='critical').length;
    byId('issueWarningCount').textContent=issueState.items.filter((i)=>i.severity==='warning').length;
    document.querySelectorAll('[data-issue-filter]').forEach((b)=>b.classList.toggle('active',b.dataset.issueFilter===issueState.filter));
    const list=byId('issueCenterList');
    if(!items.length){list.innerHTML='<div class="issue-empty"><span>✓</span><strong>No issues in this view</strong><p>Run a new diagnostic scan if you want to refresh the result.</p></div>';return;}
    list.innerHTML=items.map((item)=>`<article class="issue-item ${item.severity}" data-issue-id="${esc(item.id)}">
      <div class="issue-severity"><span></span>${esc(item.severity)}</div>
      <div class="issue-main"><div class="issue-service">${esc(item.service)} <span>${esc(String(item.kind||'').toUpperCase())}</span></div><h3>${esc(item.title)}</h3><p>${esc(item.message)}</p></div>
      <div class="issue-actions"><button class="button primary small" data-fix-issue="${esc(item.id)}">Fix</button><button class="button secondary small" data-recheck-issue="${esc(item.instanceId)}">Re-check</button></div>
    </article>`).join('');
  }

  async function loadIssueData(force=false){
    let summary=currentDiagnostics();
    if(force||!summary||summary.status==='empty'){
      try{const latest=await apiLocal('/api/diagnostics/latest');summary=latest?.result||latest;}catch(_){summary=null;}
    }
    issueState.items=flattenIssues(summary);
    renderIssues();
  }

  function openIssueCenter(){
    ensureModal();
    const modal=byId('issueCenterModal');modal.classList.remove('hidden');modal.setAttribute('aria-hidden','false');
    loadIssueData(false).catch(()=>{});
  }
  function closeIssueCenter(){const m=byId('issueCenterModal');if(m){m.classList.add('hidden');m.setAttribute('aria-hidden','true');}}
  function closeFix(){const m=byId('issueFixModal');if(m){m.classList.add('hidden');m.setAttribute('aria-hidden','true');}}

  function serviceFor(issue){return currentInstances().find((i)=>Number(i.id)===Number(issue.instanceId));}
  function stepsFor(issue){
    if(issue.recommendation?.steps?.length)return issue.recommendation.steps;
    const code=String(issue.code||'').toLowerCase();
    if(code.includes('connection'))return ['Confirm the service URL and port are reachable from the ArrMedic container.','Confirm the API key is valid.','Use Edit connection, save it, then re-run the diagnostic scan.'];
    if(code.includes('path'))return ['Compare the path shown in the *Arr app with the path visible inside ArrMedic.','If you want filesystem diagnostics, mount the same container path into ArrMedic read-only.','Re-run the scan after changing the mount or remote-path mapping.'];
    if(code.includes('permission'))return ['Confirm the path is mounted into ArrMedic.','Check host ownership and read permissions for that mount.','Keep diagnostic media mounts read-only unless write access is explicitly required.'];
    if(code.includes('hardlink'))return ['Keep downloads and media on the same filesystem when hardlinks are desired.','Prefer one common Docker mount such as /data instead of separate mounts that cross filesystems.','Re-run the scan after changing the layout.'];
    if(code.includes('queue'))return ['Open the affected *Arr queue and inspect the failed item.','Resolve the reported path, category, permission, or download-client problem.','Re-check the service in ArrMedic.'];
    if(code.includes('space')||code.includes('storage'))return ['Free space on the reported root filesystem.','Remove or move unneeded files, or expand the storage volume.','Re-run diagnostics to confirm the warning clears.'];
    return ['Review the detected message and the affected service configuration.','Make the required change outside ArrMedic if it changes Docker, filesystem, or service configuration.','Re-run the diagnostic scan to verify the issue is resolved.'];
  }

  function openFix(issueId){
    const issue=issueState.items.find((i)=>i.id===issueId);if(!issue)return;
    ensureModal();
    byId('issueFixTitle').textContent=issue.title;
    byId('issueFixSubtitle').textContent=`${issue.service} · ${String(issue.kind||'').toUpperCase()} · ${issue.severity}`;
    const steps=stepsFor(issue);
    const canEdit=String(issue.code).includes('connection');
    byId('issueFixBody').innerHTML=`<div class="fix-explanation"><strong>What ArrMedic found</strong><p>${esc(issue.message)}</p></div>
      <div class="fix-safety"><span>SAFE MODE</span><p>ArrMedic will not silently change Docker mounts, filesystem permissions, media files, or another app's settings. Those changes are shown as guided steps.</p></div>
      <ol class="fix-step-list">${steps.map((s)=>`<li>${esc(s)}</li>`).join('')}</ol>
      <div class="fix-action-row">${canEdit?`<button class="button primary" data-edit-problem="${issue.instanceId}">Edit connection</button>`:''}<button class="button secondary" data-open-service="${esc(issue.url||'')}">Open service</button><button class="button secondary" data-copy-fix="${esc(issue.id)}">Copy steps</button><button class="button primary" data-recheck-issue="${issue.instanceId}">Re-check now</button></div>`;
    const m=byId('issueFixModal');m.classList.remove('hidden');m.setAttribute('aria-hidden','false');
  }

  async function recheck(instanceId,button){
    const old=button?.textContent;if(button){button.disabled=true;button.textContent='Checking…';}
    try{
      const report=await apiLocal(`/api/instances/${instanceId}/diagnostics`);
      const summary=currentDiagnostics();
      if(summary?.instances){const idx=summary.instances.findIndex((r)=>Number(r.instanceId)===Number(instanceId));if(idx>=0)summary.instances[idx]=report;}
      issueState.items=flattenIssues(summary||{instances:[report]});renderIssues();
      const remaining=issueState.items.filter((i)=>Number(i.instanceId)===Number(instanceId)).length;
      alert(remaining?`Re-check complete. ${remaining} issue${remaining===1?'':'s'} still need attention.`:'Re-check complete. No issues remain for this service.');
    }catch(error){alert(error.message);}finally{if(button){button.disabled=false;button.textContent=old||'Re-check';}}
  }

  document.addEventListener('DOMContentLoaded',()=>{
    ensureModal();
    const issueMetric=byId('criticalCount')?.closest('.metric-card');
    if(issueMetric){issueMetric.classList.add('metric-clickable');issueMetric.setAttribute('role','button');issueMetric.setAttribute('tabindex','0');issueMetric.setAttribute('aria-label','Open issue center');issueMetric.addEventListener('click',openIssueCenter);issueMetric.addEventListener('keydown',(e)=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openIssueCenter();}});}
  });

  document.addEventListener('click',async(e)=>{
    const close=e.target.closest('#closeIssueCenter');if(close)return closeIssueCenter();
    const closeF=e.target.closest('#closeIssueFix');if(closeF)return closeFix();
    if(e.target===byId('issueCenterModal'))return closeIssueCenter();
    if(e.target===byId('issueFixModal'))return closeFix();
    const filter=e.target.closest('[data-issue-filter]');if(filter){issueState.filter=filter.dataset.issueFilter;return renderIssues();}
    const fix=e.target.closest('[data-fix-issue]');if(fix)return openFix(fix.dataset.fixIssue);
    const recheck=e.target.closest('[data-recheck-issue]');if(recheck)return recheckIssueAction(recheck);
    const edit=e.target.closest('[data-edit-problem]');if(edit){closeFix();closeIssueCenter();try{if(typeof openEdit==='function')openEdit(Number(edit.dataset.editProblem));}catch(_){}}
    const open=e.target.closest('[data-open-service]');if(open&&open.dataset.openService){window.open(open.dataset.openService,'_blank','noopener');}
    const copy=e.target.closest('[data-copy-fix]');if(copy){const issue=issueState.items.find((i)=>i.id===copy.dataset.copyFix);if(issue){await navigator.clipboard.writeText(stepsFor(issue).map((s,i)=>`${i+1}. ${s}`).join('\n'));const old=copy.textContent;copy.textContent='Copied';setTimeout(()=>copy.textContent=old,1200);}}
    const rescan=e.target.closest('#issueRescan');if(rescan){rescan.disabled=true;rescan.textContent='Scanning…';try{const summary=await apiLocal('/api/diagnostics/run',{method:'POST'});try{diagnostics=summary;}catch(_){}issueState.items=flattenIssues(summary);renderIssues();}catch(error){alert(error.message);}finally{rescan.disabled=false;rescan.textContent='Run new scan';}}
  });

  async function recheckIssueAction(button){await recheck(Number(button.dataset.recheckIssue),button);}
})();
