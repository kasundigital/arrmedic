(()=>{
  const $=(id)=>document.getElementById(id);
  let instances=[];
  let items=[];
  const selected=new Set();

  const esc=(v)=>String(v??'').replace(/[&<>'\"]/g,(c)=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','\"':'&quot;'}[c]));
  async function api(url,options={}){const r=await fetch(url,{credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json',...(options.headers||{})},...options});const d=await r.json().catch(()=>({}));if(!r.ok){if(r.status===401){location.href='/';throw new Error('Please sign in to ArrMedic first.');}throw new Error(d.detail||`Request failed (${r.status})`);}return d;}
  function key(item){return `${item.instanceId}:${item.itemId}`;}
  function notice(message,ok=false){const el=$('scanNotice');el.className=`notice ${ok?'success':'error'}`;el.textContent=message;}
  function setScanEnabled(){$('scanCleanup').disabled=!document.querySelector('[data-instance-check]:checked');}
  function updateSelected(){
    $('selectedCount').textContent=selected.size;
    const disabled=selected.size===0;
    $('removeSelected').disabled=disabled;
    $('removeSelectedAndFiles').disabled=disabled;
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
        <td><input type="checkbox" data-row-check="${esc(id)}" ${checked} /></td>
        <td><strong>${esc(item.title)}</strong><small>${item.year?esc(item.year):''} · ${esc(item.kind.toUpperCase())}</small></td>
        <td><strong>${esc(item.instanceName)}</strong></td>
        <td>${item.staleMetadata?'<span class="pill danger">Removed</span>':'<span class="pill muted">Valid</span>'}<small>${esc(item.externalProvider)} ${esc(item.externalId||'—')}</small></td>
        <td>${item.hasMedia?'<span class="pill good">Present</span>':'<span class="pill warning">Missing</span>'}<small>${esc(mediaLabel(item))}</small></td>
        <td><code title="${esc(item.path||'')}">${esc(item.path||'—')}</code></td>
      </tr>`;
    }).join('');
    updateSelected();
  }

  function setSelection(predicate){selected.clear();items.forEach((item)=>{if(predicate(item))selected.add(key(item));});renderRows();}

  async function scan(){
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

    const withMedia=chosen.filter((item)=>item.hasMedia).length;
    const folders=[...new Set(chosen.map((item)=>item.path).filter(Boolean))];
    const preview=folders.slice(0,5).map((path)=>`• ${path}`).join('\n');
    const extra=folders.length>5?`\n• …and ${folders.length-5} more folder(s)`:'';
    const warning=`DANGER: Remove ${chosen.length} record(s) AND ask Radarr/Sonarr to delete their managed files/folders from disk?\n\nThis cannot be undone by ArrMedic.${withMedia?`\n${withMedia} selected item(s) currently report media files.`:''}${preview?`\n\nFolders include:\n${preview}${extra}`:''}`;
    if(!confirm(warning))return false;
    const typed=prompt(`Type DELETE to permanently remove the selected records and their managed files/folders.`);
    return typed==='DELETE';
  }

  async function removeSelected(deleteFiles=false){
    const chosen=items.filter((item)=>selected.has(key(item)));
    if(!chosen.length)return;
    if(!confirmRemoval(chosen,deleteFiles))return;

    const button=deleteFiles?$('removeSelectedAndFiles'):$('removeSelected');
    const original=button.textContent;
    button.disabled=true;
    button.textContent=deleteFiles?'Deleting…':'Removing…';
    $('removeSelected').disabled=true;
    $('removeSelectedAndFiles').disabled=true;

    try{
      const payload={items:chosen.map((item)=>({instance_id:item.instanceId,item_id:item.itemId})),delete_files:deleteFiles,add_import_exclusion:$('addExclusion').checked};
      const result=await api('/api/cleanup/remove',{method:'POST',body:JSON.stringify(payload)});
      const removedKeys=new Set((result.removed||[]).map((x)=>`${x.instanceId}:${x.itemId}`));
      items=items.filter((item)=>!removedKeys.has(key(item)));selected.clear();renderRows();
      $('candidateCount').textContent=items.length;$('staleCount').textContent=items.filter((i)=>i.staleMetadata).length;$('missingCount').textContent=items.filter((i)=>!i.hasMedia).length;
      const action=deleteFiles?'Removed records and requested file/folder deletion for':'Removed';
      notice(`${action} ${result.removedCount||0} item(s).${result.failedCount?` ${result.failedCount} failed.`:''}`,!result.failedCount);
    }catch(error){notice(error.message,false);}finally{button.textContent=original;updateSelected();}
  }

  document.addEventListener('DOMContentLoaded',async()=>{
    try{const data=await api('/api/cleanup/instances');instances=data.items||[];renderInstances();}catch(error){notice(error.message,false);}
    document.addEventListener('change',(e)=>{
      if(e.target.matches('[data-instance-check]'))setScanEnabled();
      if(e.target.matches('[data-row-check]')){const id=e.target.dataset.rowCheck;e.target.checked?selected.add(id):selected.delete(id);updateSelected();}
    });
    $('selectAllInstances').addEventListener('click',()=>{document.querySelectorAll('[data-instance-check]').forEach((x)=>x.checked=true);setScanEnabled();});
    $('scanCleanup').addEventListener('click',scan);
    $('selectAllRows').addEventListener('click',()=>setSelection(()=>true));
    $('selectMissingRows').addEventListener('click',()=>setSelection((item)=>!item.hasMedia));
    $('selectStaleRows').addEventListener('click',()=>setSelection((item)=>item.staleMetadata));
    $('clearRows').addEventListener('click',()=>setSelection(()=>false));
    $('cleanupSearch').addEventListener('input',renderRows);$('cleanupFilter').addEventListener('change',renderRows);
    $('removeSelected').addEventListener('click',()=>removeSelected(false));
    $('removeSelectedAndFiles').addEventListener('click',()=>removeSelected(true));
  });
})();
