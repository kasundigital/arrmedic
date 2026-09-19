(()=>{
  const $=(id)=>document.getElementById(id);
  let instances=[],items=[],reportId=null,reportExpiresAt=null,lastReport=null,cleanupRunning=false,stopRequested=false;
  const selected=new Set();
  const esc=(v)=>String(v??'').replace(/[&<>'\"]/g,(c)=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));
  async function api(url,options={}){const r=await fetch(url,{credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json',...(options.headers||{})},...options});const d=await r.json().catch(()=>({}));if(!r.ok){if(r.status===401){location.href='/';throw new Error('Please sign in to ArrMedic first.');}throw new Error(d.detail||`Request failed (${r.status})`);}return d;}
  const key=(item)=>`${item.instanceId}:${item.itemId}`;
  function notice(message,ok=false){const el=$('scanNotice');el.className=`notice ${ok?'success':'error'}`;el.textContent=message;}
  function selectedItems(){return items.filter((item)=>selected.has(key(item)));}
  function setScanEnabled(){$('scanCleanup').disabled=cleanupRunning||!document.querySelector('[data-instance-check]:checked');}
  function statusLabel(status){return status==='safe'?'Safe to clean':status==='review'?'Review first':"Don't auto-clean";}
  function statusClass(status){return status==='safe'?'good':status==='review'?'warning':'danger';}
  function destructiveSelectionIsSafe(){const chosen=selectedItems();return chosen.length>0&&chosen.every((item)=>!item.hasMedia&&item.cleanupStatus!=='manual_only');}
  function updateSelected(){
    $('selectedCount').textContent=selected.size;
    const reviewed=Boolean(reportId);
    $('removeSelected').disabled=cleanupRunning||!reviewed||selected.size===0;
    $('removeSelectedAndFiles').disabled=cleanupRunning||!reviewed||!destructiveSelectionIsSafe();
    document.querySelectorAll('[data-row-check]').forEach((el)=>el.disabled=cleanupRunning);
  }
  function renderInstances(){
    const root=$('instanceChoices');
    if(!instances.length){root.innerHTML='<div class="empty-mini">No Radarr or Sonarr apps are configured.</div>';setScanEnabled();return;}
    root.innerHTML=instances.map((i)=>`<label class="instance-choice"><input type="checkbox" data-instance-check value="${i.id}" /><span class="instance-mark">${i.kind==='radarr'?'R':'S'}</span><div><strong>${esc(i.name)}</strong><small>${esc(i.kind.toUpperCase())} · ${esc(i.url)}</small></div></label>`).join('');
    setScanEnabled();
  }
  function filteredItems(){
    const q=$('cleanupSearch').value.trim().toLowerCase(),filter=$('cleanupFilter').value;
    return items.filter((item)=>{
      if(['safe','review','manual_only'].includes(filter)&&item.cleanupStatus!==filter)return false;
      if(filter==='stale'&&!item.staleMetadata)return false;
      if(filter==='missing'&&item.hasMedia)return false;
      if(q&&!([item.title,item.instanceName,item.externalId,item.path,item.kind,item.reason].join(' ').toLowerCase().includes(q)))return false;
      return true;
    });
  }
  function renderRows(){
    const rows=filteredItems(),body=$('cleanupRows');
    if(!rows.length){body.innerHTML='<tr><td colspan="6"><div class="empty-mini">No candidates match this view.</div></td></tr>';updateSelected();return;}
    body.innerHTML=rows.map((item)=>{
      const id=key(item),checked=selected.has(id)?'checked':'';
      return `<tr><td><input type="checkbox" data-row-check="${esc(id)}" ${checked} /></td><td><strong>${esc(item.title)}</strong><small>${item.year?esc(item.year):''} · ${esc(item.kind.toUpperCase())}</small></td><td><strong>${esc(item.instanceName)}</strong></td><td><span class="pill ${statusClass(item.cleanupStatus)}">${esc(statusLabel(item.cleanupStatus))}</span><small>${esc(item.recommendation||'')}</small></td><td><span class="reason-text">${esc(item.reason||'')}</span><small>${item.staleMetadata?'Removed metadata · ':''}${item.hasMedia?'Media present':'No media file'}</small></td><td><code title="${esc(item.path||'')}">${esc(item.path||'—')}</code></td></tr>`;
    }).join('');
    updateSelected();
  }
  function setSelection(predicate){if(cleanupRunning)return;selected.clear();filteredItems().forEach((item)=>{if(predicate(item))selected.add(key(item));});renderRows();}
  function downloadReport(){
    if(!lastReport)return;
    const blob=new Blob([JSON.stringify(lastReport,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');
    a.href=url;a.download=`arrmedic-cleanup-dry-run-${new Date().toISOString().replace(/[:.]/g,'-')}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),500);
  }
  async function scan(){
    if(cleanupRunning)return;
    const ids=[...document.querySelectorAll('[data-instance-check]:checked')].map((el)=>Number(el.value));if(!ids.length)return;
    const b=$('scanCleanup');b.disabled=true;b.textContent='Running dry scan…';
    reportId=null;selected.clear();updateSelected();
    try{
      const data=await api('/api/cleanup/scan',{method:'POST',body:JSON.stringify({instance_ids:ids})});
      lastReport=data;reportId=data.reportId;reportExpiresAt=data.expiresAt;items=data.items||[];
      $('candidateCount').textContent=data.totalCandidates||0;$('safeCount').textContent=data.safeCount||0;$('reviewCount').textContent=data.reviewCount||0;$('manualCount').textContent=data.manualOnlyCount||0;
      $('exportReport').disabled=false;$('resultsPanel').classList.remove('hidden');renderRows();
      $('reportState').innerHTML=`<strong>Dry run complete.</strong> ${data.totalCandidates||0} candidate(s) found. Review the report before selecting anything. Report expires at ${new Date(data.expiresAt).toLocaleTimeString()}.`;
      notice('Dry run complete. No changes were made.',true);
    }catch(error){notice(error.message,false);}finally{b.textContent='Run Dry Run — No Changes';setScanEnabled();}
  }
  function confirmCleanup(chosen,deleteFiles){
    const safe=chosen.filter(i=>i.cleanupStatus==='safe').length,review=chosen.filter(i=>i.cleanupStatus==='review').length,manual=chosen.filter(i=>i.cleanupStatus==='manual_only').length;
    const action=deleteFiles?'remove the selected app records and ask Radarr/Sonarr to delete missing folders':'remove the selected records from Radarr/Sonarr only';
    const msg=`Final review\n\nSelected: ${chosen.length}\nSafe: ${safe}\nReview first: ${review}\nDon't auto-clean: ${manual}\n\nArrMedic will ${action}.\n\nNothing happens unless you confirm now.`;
    if(!confirm(msg))return false;
    if(deleteFiles){const typed=prompt('Type CLEANUP to confirm folder deletion.');return typed==='CLEANUP';}
    return true;
  }
  function setProgress({total=0,done=0,removed=0,failed=0,current='',status='running'}={}){
    const panel=$('cleanupProgress');panel.classList.remove('hidden');const pct=total?Math.round(done/total*100):0;
    $('cleanupProgressBar').style.width=`${pct}%`;$('cleanupProgressPercent').textContent=`${pct}%`;$('cleanupProgressDone').textContent=done;$('cleanupProgressTotal').textContent=total;$('cleanupProgressRemoved').textContent=removed;$('cleanupProgressFailed').textContent=failed;$('cleanupProgressCurrent').textContent=current||'Waiting to start';$('cleanupProgressTitle').textContent=status==='done'?'Cleanup complete':status==='stopped'?'Cleanup stopped':status==='stopping'?'Stopping…':'Cleanup in progress';$('stopCleanup').disabled=status!=='running';
  }
  function refreshCounts(){
    $('candidateCount').textContent=items.length;$('safeCount').textContent=items.filter(i=>i.cleanupStatus==='safe').length;$('reviewCount').textContent=items.filter(i=>i.cleanupStatus==='review').length;$('manualCount').textContent=items.filter(i=>i.cleanupStatus==='manual_only').length;
  }
  async function removeSelected(deleteFiles=false){
    if(cleanupRunning||!reportId){notice('Run Dry Run again before cleanup.',false);return;}
    const chosen=selectedItems();if(!chosen.length)return;
    if(deleteFiles&&chosen.some(i=>i.hasMedia)){notice('Folder deletion is blocked because one or more selected items still have media.',false);return;}
    if(!confirmCleanup(chosen,deleteFiles))return;
    cleanupRunning=true;stopRequested=false;updateSelected();setScanEnabled();
    let removed=0,failed=0,done=0;const removedKeys=new Set();
    setProgress({total:chosen.length,current:'Starting cleanup…'});
    for(const item of chosen){
      if(stopRequested)break;
      setProgress({total:chosen.length,done,removed,failed,current:`Processing ${item.title}`});
      try{
        const result=await api('/api/cleanup/remove',{method:'POST',body:JSON.stringify({report_id:reportId,items:[{instance_id:item.instanceId,item_id:item.itemId}],delete_files:deleteFiles,add_import_exclusion:$('addExclusion').checked})});
        if((result.removedCount||0)>0){removed+=result.removedCount;removedKeys.add(key(item));}
        failed+=result.failedCount||0;
      }catch(error){failed++;notice(`${item.title}: ${error.message}`,false);if(String(error.message).includes('Dry-run report')){reportId=null;break;}}
      done++;setProgress({total:chosen.length,done,removed,failed,current:`Finished ${item.title}`,status:stopRequested?'stopping':'running'});
    }
    items=items.filter(i=>!removedKeys.has(key(i)));selected.clear();refreshCounts();renderRows();
    const stopped=stopRequested&&done<chosen.length;setProgress({total:chosen.length,done,removed,failed,current:stopped?'Some items were not started.':`Processed ${done} item(s).`,status:stopped?'stopped':'done'});
    notice(`Cleanup finished. ${removed} removed.${failed?` ${failed} blocked/failed.`:''}`,failed===0);
    cleanupRunning=false;stopRequested=false;updateSelected();setScanEnabled();
  }
  document.addEventListener('DOMContentLoaded',async()=>{
    try{const data=await api('/api/cleanup/instances');instances=data.items||[];renderInstances();}catch(error){notice(error.message,false);}
    document.addEventListener('change',(e)=>{if(e.target.matches('[data-instance-check]'))setScanEnabled();if(e.target.matches('[data-row-check]')){e.target.checked?selected.add(e.target.dataset.rowCheck):selected.delete(e.target.dataset.rowCheck);updateSelected();}});
    $('selectAllInstances').addEventListener('click',()=>{document.querySelectorAll('[data-instance-check]').forEach(x=>x.checked=true);setScanEnabled();});
    $('scanCleanup').addEventListener('click',scan);$('exportReport').addEventListener('click',downloadReport);
    $('selectSafeRows').addEventListener('click',()=>setSelection(i=>i.cleanupStatus==='safe'));$('selectAllRows').addEventListener('click',()=>setSelection(()=>true));$('selectMissingRows').addEventListener('click',()=>setSelection(i=>!i.hasMedia));$('selectStaleRows').addEventListener('click',()=>setSelection(i=>i.staleMetadata));$('clearRows').addEventListener('click',()=>setSelection(()=>false));
    $('cleanupSearch').addEventListener('input',renderRows);$('cleanupFilter').addEventListener('change',renderRows);
    $('removeSelected').addEventListener('click',()=>removeSelected(false));$('removeSelectedAndFiles').addEventListener('click',()=>removeSelected(true));
    $('stopCleanup').addEventListener('click',()=>{if(!cleanupRunning||stopRequested)return;stopRequested=true;$('stopCleanup').disabled=true;});
  });
})();
