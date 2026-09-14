(()=>{
  const $=(id)=>document.getElementById(id);
  let instances=[];
  let items=[];
  const selected=new Set();
  let cleanupRunning=false;
  let stopRequested=false;

  const esc=(v)=>String(v??'').replace(/[&<>'\"]/g,(c)=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));
  async function api(url,options={}){const r=await fetch(url,{credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json',...(options.headers||{})},...options});const d=await r.json().catch(()=>({}));if(!r.ok){if(r.status===401){location.href='/';throw new Error('Please sign in to ArrMedic first.');}throw new Error(d.detail||`Request failed (${r.status})`);}return d;}
  function key(item){return `${item.instanceId}:${item.itemId}`;}
  function notice(message,ok=false){const el=$('scanNotice');el.className=`notice ${ok?'success':'error'}`;el.textContent=message;}
  function setScanEnabled(){$('scanCleanup').disabled=cleanupRunning||!document.querySelector('[data-instance-check]:checked');}
  function selectedItems(){return items.filter((item)=>selected.has(key(item)));}
  function destructiveSelectionIsSafe(){const chosen=selectedItems();return chosen.length>0&&chosen.every((item)=>!item.hasMedia);}
  function updateSelected(){
    $('selectedCount').textContent=selected.size;
    $('removeSelected').disabled=cleanupRunning||selected.size===0;
    const safe=destructiveSelectionIsSafe();
    $('removeSelectedAndFiles').disabled=cleanupRunning||!safe;
    $('removeSelectedAndFiles').title=safe?'Delete selected missing-media records and their managed folders':'Only available when every selected item is marked Missing';
    document.querySelectorAll('[data-row-check]').forEach((el)=>el.disabled=cleanupRunning);
    ['selectAllRows','selectMissingRows','selectStaleRows','clearRows'].forEach((id)=>{$(id).disabled=cleanupRunning;});
  }

  function renderInstances(){
    const el=$('instanceChoices');
    if(!instances.length){el.innerHTML='<div class="empty-mini">No Radarr or Sonarr instances are configured yet.</div>';$('scanCleanup').disabled=true;return;}
    el.innerHTML=instances.map((i)=>`<label class="instance-choice"><input type="checkbox" data-instance-check value="${i.id}" /><span class="instance-mark">${i.kind==='radarr'?'R':'S'}</span><div><strong>${esc(i.name)}</strong><small>${esc(i.kind.toUpperCase())} · ${esc(i.url)}</small></div></label>`).join('');
    setScanEnabled();
  }

  function filteredItems(){
    const q=$('cleanupSearch').value.trim().toLowerCase();
    const filter=$('cleanupFilter').value;
    return items.filter((item)=>{
      if(filter==='stale'&&!item.staleMetadata)return false;
      if(filter==='missing'&&item.hasMedia)return false;
      if(filter==='both'&&(!item.staleMetadata||item.hasMedia))return false;
      if(!q)return true;
      const hay=[item.title,item.instanceName,item.externalId,item.path,item.mediaPath,item.kind].join(' ').toLowerCase();
      return hay.includes(q);
    });
  }

  function mediaLabel(item){
    if(item.kind==='sonarr')return item.hasMedia?`${item.mediaCount||0} episode files`:'No episode files';
    return item.hasMedia?'Movie file present':'No movie file';
  }

  function renderRows(){
    const rows=filteredItems();
    const body=$('cleanupRows');
    if(!rows.length){body.innerHTML='<tr><td colspan="6"><div class="empty-mini">No cleanup candidates match this view.</div></td></tr>';updateSelected();return;}
    body.innerHTML=rows.map((item)=>{
      const id=key(item);const checked=selected.has(id)?'checked':'';
      return `<tr class="${item.staleMetadata?'is-stale':''} ${!item.hasMedia?'is-missing':''}">
        <td><input type="checkbox" data-row-check="${esc(id)}" ${checked} ${cleanupRunning?'disabled':''} /></td>
        <td><strong>${esc(item.title)}</strong><small>${item.year?esc(item.year):''} · ${esc(item.kind.toUpperCase())}</small></td>
        <td><strong>${esc(item.instanceName)}</strong></td>
        <td>${item.staleMetadata?'<span class="pill danger">Removed</span>':'<span class="pill muted">Valid</span>'}<small>${esc(item.externalProvider)} ${esc(item.externalId||'—')}</small></td>
        <td>${item.hasMedia?'<span class="pill good">Present</span>':'<span class="pill warning">Missing</span>'}<small>${esc(mediaLabel(item))}</small></td>
        <td><code title="${esc(item.path||'')}">${esc(item.path||'—')}</code></td>
      </tr>`;
    }).join('');
    updateSelected();
  }

  function setSelection(predicate){if(cleanupRunning)return;selected.clear();items.forEach((item)=>{if(predicate(item))selected.add(key(item));});renderRows();}

  async function scan(){
    if(cleanupRunning)return;
    const ids=[...document.querySelectorAll('[data-instance-check]:checked')].map((el)=>Number(el.value));
    if(!ids.length)return;
    const button=$('scanCleanup');button.disabled=true;button.textContent='Scanning…';
    try{
      const data=await api('/api/cleanup/scan',{method:'POST',body:JSON.stringify({instance_ids:ids})});
      items=data.items||[];selected.clear();
      $('candidateCount').textContent=data.totalCandidates||0;$('staleCount').textContent=data.staleCount||0;$('missingCount').textContent=data.missingMediaCount||0;
      $('resultsPanel').classList.remove('hidden');renderRows();
      notice(`Scan complete. ${data.totalCandidates||0} cleanup candidate(s) found.`,true);
    }catch(error){notice(error.message,false);}finally{button.disabled=false;button.textContent='Scan selected instances';setScanEnabled();}
  }

  function confirmRemoval(chosen,deleteFiles){
    if(!deleteFiles){
      const withMedia=chosen.filter((item)=>item.hasMedia).length;
      const message=`Remove ${chosen.length} selected record(s) from Radarr/Sonarr?\n\nMedia files and folders will NOT be deleted.${withMedia?`\n${withMedia} selected item(s) currently have media files; those files will stay on disk.`:''}`;
      return confirm(message);
    }

    if(chosen.some((item)=>item.hasMedia)){
      notice('Safety block: file/folder deletion is only allowed for items marked Missing. Use “Select missing media only”.',false);
      return false;
    }

    const folders=[...new Set(chosen.map((item)=>item.path).filter(Boolean))];
    const preview=folders.slice(0,5).map((path)=>`• ${path}`).join('\n');
    const extra=folders.length>5?`\n• …and ${folders.length-5} more folder(s)`:'';
    const warning=`DANGER: Remove ${chosen.length} MISSING-media record(s) and ask Radarr/Sonarr to delete their managed folders from disk?\n\nArrMedic will re-check each item before deletion and block it if media is now present. A progress screen and Stop button will remain visible during the operation.${preview?`\n\nFolders include:\n${preview}${extra}`:''}`;
    if(!confirm(warning))return false;
    const typed=prompt('Type DELETE to continue.');
    return typed==='DELETE';
  }

  function setProgress({total=0,done=0,removed=0,failed=0,current='',status='running'}={}){
    const panel=$('cleanupProgress');
    panel.classList.remove('hidden','is-stopping','is-stopped');
    if(status==='stopping')panel.classList.add('is-stopping');
    if(status==='stopped')panel.classList.add('is-stopped');
    const percent=total?Math.round((done/total)*100):0;
    $('cleanupProgressBar').style.width=`${percent}%`;
    $('cleanupProgressPercent').textContent=`${percent}%`;
    $('cleanupProgressDone').textContent=done;
    $('cleanupProgressTotal').textContent=total;
    $('cleanupProgressRemoved').textContent=removed;
    $('cleanupProgressFailed').textContent=failed;
    $('cleanupProgressCurrent').textContent=current||'Waiting to start';
    $('cleanupProgressTitle').textContent=status==='stopped'?'Cleanup stopped':status==='done'?'Cleanup complete':status==='stopping'?'Stopping after current request…':'Cleanup in progress';
    $('stopCleanup').disabled=status!=='running';
    $('stopCleanup').textContent=status==='stopping'?'Stopping…':status==='stopped'?'Stopped':status==='done'?'Complete':'Stop';
  }

  function refreshCounts(){
    $('candidateCount').textContent=items.length;
    $('staleCount').textContent=items.filter((i)=>i.staleMetadata).length;
    $('missingCount').textContent=items.filter((i)=>!i.hasMedia).length;
  }

  async function removeSelected(deleteFiles=false){
    if(cleanupRunning)return;
    const chosen=selectedItems();
    if(!chosen.length)return;
    if(deleteFiles&&chosen.some((item)=>item.hasMedia)){
      notice('Safety block: destructive cleanup only works for Missing items. Select missing media only first.',false);
      return;
    }
    if(!confirmRemoval(chosen,deleteFiles))return;

    cleanupRunning=true;
    stopRequested=false;
    const removedKeys=new Set();
    let removed=0;
    let failed=0;
    let done=0;
    updateSelected();
    setScanEnabled();
    $('cleanupSearch').disabled=true;
    $('cleanupFilter').disabled=true;
    $('selectAllInstances').disabled=true;
    document.querySelectorAll('[data-instance-check]').forEach((el)=>el.disabled=true);
    setProgress({total:chosen.length,done,removed,failed,current:'Starting first item…',status:'running'});

    for(const item of chosen){
      if(stopRequested)break;
      const label=`${item.title} · ${item.instanceName}`;
      setProgress({total:chosen.length,done,removed,failed,current:`Processing ${label}`,status:'running'});
      try{
        const payload={items:[{instance_id:item.instanceId,item_id:item.itemId}],delete_files:deleteFiles,add_import_exclusion:$('addExclusion').checked};
        const result=await api('/api/cleanup/remove',{method:'POST',body:JSON.stringify(payload)});
        if((result.removedCount||0)>0){removed+=(result.removedCount||0);removedKeys.add(key(item));}
        failed+=(result.failedCount||0);
      }catch(error){
        failed+=1;
        notice(`Cleanup error on ${item.title}: ${error.message}`,false);
      }
      done+=1;
      const state=stopRequested?'stopping':'running';
      setProgress({total:chosen.length,done,removed,failed,current:stopRequested?'Stop requested. Finishing current request only.':`Finished ${label}`,status:state});
    }

    items=items.filter((item)=>!removedKeys.has(key(item)));
    selected.clear();
    refreshCounts();
    renderRows();

    const stopped=stopRequested&&done<chosen.length;
    setProgress({total:chosen.length,done,removed,failed,current:stopped?`${chosen.length-done} item(s) were not started.`:`Processed ${done} item(s).`,status:stopped?'stopped':'done'});
    if(stopped){
      notice(`Cleanup stopped. ${removed} removed, ${failed} blocked/failed, ${chosen.length-done} not started.`,false);
    }else{
      const action=deleteFiles?'Destructive cleanup finished':'Removal finished';
      notice(`${action}. ${removed} removed.${failed?` ${failed} blocked/failed.`:''}`,failed===0);
    }

    cleanupRunning=false;
    stopRequested=false;
    $('cleanupSearch').disabled=false;
    $('cleanupFilter').disabled=false;
    $('selectAllInstances').disabled=false;
    document.querySelectorAll('[data-instance-check]').forEach((el)=>el.disabled=false);
    updateSelected();
    setScanEnabled();
  }

  document.addEventListener('DOMContentLoaded',async()=>{
    try{const data=await api('/api/cleanup/instances');instances=data.items||[];renderInstances();}catch(error){notice(error.message,false);}
    document.addEventListener('change',(e)=>{
      if(e.target.matches('[data-instance-check]'))setScanEnabled();
      if(e.target.matches('[data-row-check]')){const id=e.target.dataset.rowCheck;e.target.checked?selected.add(id):selected.delete(id);updateSelected();}
    });
    $('selectAllInstances').addEventListener('click',()=>{if(cleanupRunning)return;document.querySelectorAll('[data-instance-check]').forEach((x)=>x.checked=true);setScanEnabled();});
    $('scanCleanup').addEventListener('click',scan);
    $('selectAllRows').addEventListener('click',()=>setSelection(()=>true));
    $('selectMissingRows').addEventListener('click',()=>setSelection((item)=>!item.hasMedia));
    $('selectStaleRows').addEventListener('click',()=>setSelection((item)=>item.staleMetadata));
    $('clearRows').addEventListener('click',()=>setSelection(()=>false));
    $('cleanupSearch').addEventListener('input',renderRows);$('cleanupFilter').addEventListener('change',renderRows);
    $('removeSelected').addEventListener('click',()=>removeSelected(false));
    $('removeSelectedAndFiles').addEventListener('click',()=>removeSelected(true));
    $('stopCleanup').addEventListener('click',()=>{
      if(!cleanupRunning||stopRequested)return;
      stopRequested=true;
      $('stopCleanup').disabled=true;
      setProgress({
        total:Number($('cleanupProgressTotal').textContent)||0,
        done:Number($('cleanupProgressDone').textContent)||0,
        removed:Number($('cleanupProgressRemoved').textContent)||0,
        failed:Number($('cleanupProgressFailed').textContent)||0,
        current:'Stop requested. No new item will start after the current request.',
        status:'stopping'
      });
    });
  });
})();
