const $ = x => document.querySelector(x);
const el = (tag, cls, text) => { const n = document.createElement(tag); if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n; };
let state, busy=false, renderedVersion=null, selection=null, editorVersion=null;
let projectId=new URLSearchParams(location.search).get('project')||'default';
const promptDrafts=new Map();
const sourceReferences=new Map();
function referenceMarker(source){return 'Source: “'+source.title+'”';}
function addSourceReference(source){
 const prompt=$('#prompt'),marker=referenceMarker(source);
 if(!sourceReferences.has(projectId))sourceReferences.set(projectId,new Map());
 sourceReferences.get(projectId).set(source.id,marker);
 if(!prompt.value.includes(marker)){
   const before=prompt.value.slice(0,prompt.selectionStart),after=prompt.value.slice(prompt.selectionEnd);
   const inserted=(before&&!/\s$/.test(before)?' ':'')+marker+(after&&!/^\s/.test(after)?' ':' ');
   prompt.setRangeText(inserted,prompt.selectionStart,prompt.selectionEnd,'end');
 }
 prompt.focus();
}
function referencedSourceIds(prompt){return [...(sourceReferences.get(projectId)||new Map())].filter(([,marker])=>prompt.includes(marker)).map(([id])=>id);}
async function api(path, body, project=projectId){const r=await fetch(path+'?project='+encodeURIComponent(project),{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||'Request failed');return d;}
function clear(n){n.replaceChildren();}
function byTime(items){return [...items].sort((a,b)=>(a.at||0)-(b.at||0));}
function activityStamp(at){return at?new Date(at*1000).toLocaleString():'';}
function renderTaskDecision(job,task,group){
 if(!['disputed','evidence_required','waiting','blocked','needs_input','inquiry'].includes(task.status))return;
 const card=el('div','card '+(task.status==='disputed'?'warning':''));
 card.append(el('strong','',task.status.replaceAll('_',' ').toUpperCase()+' · '+task.instruction),el('p','',task.reason||task.finding?.finding||''));
 if(task.proposal){card.append(el('p','','Proposed text: '+task.proposal.text));if(task.review)card.append(el('p','','Review: '+task.review.rationale));}
 if(task.status==='evidence_required')card.append(el('p','','Allow saves this proposed text without verified evidence.'));
 if(['disputed','evidence_required'].includes(task.status)&&task.proposal){
   for(const choice of [task.status==='evidence_required'?'allow':'approve','reject']){
     const button=el('button','',choice==='allow'?'Allow':choice==='approve'?'Approve revision':'Reject');
     button.disabled=['queued','running'].includes(job.status);
     button.onclick=async()=>{button.disabled=true;try{await api('/api/decide',{job_id:job.id,task_id:task.id,choice});await refresh()}catch(error){notice(error);button.disabled=false}};
     card.append(button);
   }
 }
 group.append(card);
}
function renderActivity(jobs,activity,target){
 const grouped=new Map();
 for(const event of byTime(activity)){if(!grouped.has(event.job_id))grouped.set(event.job_id,[]);grouped.get(event.job_id).push(event);}
 clear(target);
 for(const job of byTime(jobs).reverse()){
   const group=el('section','activity-run');group.dataset.jobId=job.id;
   const request=el('div','card');request.append(el('strong','','Your request · '+job.status.replaceAll('_',' ')),el('span','stamp',activityStamp(job.at)),el('p','',job.prompt));
   if(job.summary)request.append(el('p','',job.summary));group.append(request);
   if(job.status==='error'){const card=el('div','card error');card.append(el('strong','','Run failed'),el('p','',job.error));group.append(card);}
   for(const task of job.tasks||[])renderTaskDecision(job,task,group);
   for(const event of grouped.get(job.id)||[]){
     const card=el('div','card activity-event');card.dataset.eventId=event.id;
     card.append(el('strong','',event.role+' · '+event.message),el('span','stamp',activityStamp(event.at)));
     if(event.detail)card.append(el('p','',JSON.stringify(event.detail)));group.append(card);
   }
   target.append(group);
 }
}
function render(){if(!state)return;const p=state.paper;$('#version').textContent='Version '+p.number;
 const projects=$('#projectSelect');
 if(JSON.stringify(state.projects)!==projects.dataset.items){projects.replaceChildren(...state.projects.map(p=>{const option=el('option','',p.name);option.value=p.id;return option}));projects.dataset.items=JSON.stringify(state.projects);}
 projects.value=projectId;projects.disabled=busy;$('#newProject').disabled=busy;
 $('#providerStatus').textContent=state.providers.map(p=>(p.id==='groq'?'Groq':'OpenRouter')+': '+(p.configured?'key configured':'key missing')).join(' · ');
 $('#exportMarkdown').href='/api/markdown?project='+encodeURIComponent(projectId);
 for(const id of ['editTitle','editMarkdown','addSource'])$('#'+id).disabled=false;
 const outline=$('#outline'),paper=$('#paper'),sources=$('#sources'),events=$('#events'),versions=$('#versions');[sources,events,versions].forEach(clear);
 if(renderedVersion!==p.id){
   if(selection){setSelection(null);notice('The document changed. Select the passage again to revise it.');}
   [outline,paper].forEach(clear);paper.append(el('h1','',p.title));
   p.sections.forEach(s=>{
     const section=el('section');section.id=s.id;
     if(s.heading){const link=el('a','',s.heading);link.href='#'+s.id;outline.append(link);section.append(el('h2','',s.heading));}
     s.blocks.forEach(b=>{const block=el('div','markdown-block');block.dataset.sectionId=s.id;block.dataset.blockId=b.id;block.append(renderMarkdown(b.text));section.append(block);
       if(b.claims?.length){const refs=[...new Set(b.claims.flatMap(c=>(c.citations||[]).map(q=>state.sources.find(x=>x.id===q.source_id)?.title||q.source_id)))];section.append(el('div','cite','Sources: '+refs.join('; ')));}
       if(b.evidence_override)section.append(el('div','cite','Allowed by you · evidence not verified'));
     });paper.append(section);
   });
   if(!p.sections.length){const empty=el('div','empty-state');empty.append(el('p','','Your document is empty.'),el('p','','Describe what you want to write below, or use Edit Markdown to paste a draft.'));paper.append(empty);}
   renderedVersion=p.id;
 }
 $('#undo').disabled=!p.parent;
 $('#documentStatus').textContent='LATEST SAVED DOCUMENT · '+new Date(p.at*1000).toLocaleTimeString();
 state.sources.forEach(s=>{const n=el('div','source-item'),open=el('button','source-open','▣ '+s.title),reference=el('button','source-reference','Add reference');
   open.title='View '+s.title;open.onclick=async()=>{try{const item=await api('/api/source/'+s.id);$('#versionDetail').textContent=item.title+'\n\n'+item.text;$('#versionDialog').showModal()}catch(e){notice(e)}};
   reference.type='button';reference.setAttribute('aria-label','Add '+s.title+' to prompt');reference.onclick=()=>addSourceReference(s);
   n.append(open,reference);sources.append(n)});
 renderActivity(state.jobs,state.events,events);
 [...state.versions].sort((a,b)=>b.number-a.number).slice(0,20).forEach(v=>{const n=el('div','version-item','v'+v.number+' · '+v.prompt);n.onclick=async()=>{try{const item=await api('/api/version/'+v.id);$('#versionDetail').textContent='Version '+v.number+'\n'+item.title+'\n\n'+item.sections.map(s=>s.heading+'\n'+s.blocks.map(b=>b.text).join('\n')).join('\n\n');$('#versionDialog').showModal()}catch(e){notice(e)}};versions.append(n)});
 const active=state.jobs.some(j=>['queued','running'].includes(j.status));$('#run').disabled=active||busy;$('#run').textContent=active?'Reviewing your request…':'Send request ↗';}
function notice(e){$('#notice').textContent=e.message||String(e);setTimeout(()=>$('#notice').textContent='',8500)}
let refreshing=false;
async function refresh(){if(refreshing)return;refreshing=true;const requestedProject=projectId;try{const next=await api('/api/state',undefined,requestedProject);if(requestedProject===projectId){state=next;render()}}catch(e){if(requestedProject===projectId){notice(e);if(e.message==='Unknown project'){projectId='default';history.replaceState(null,'','?project=default');}}}finally{refreshing=false;if(requestedProject!==projectId)refresh()}}
$('#run').onclick=async()=>{if(busy)return;try{const prompt=$('#prompt').value.trim();if(!prompt)return;busy=true;$('#run').disabled=true;await api('/api/run',{prompt,selection,source_ids:referencedSourceIds(prompt)});$('#prompt').value='';sourceReferences.delete(projectId);setSelection(null);await refresh()}catch(e){notice(e)}finally{busy=false;if(state)render()}};
$('#undo').onclick=async()=>{try{await api('/api/undo',{});refresh()}catch(e){notice(e)}};
$('#editTitle').onclick=async()=>{const title=window.prompt('Paper title',state.paper.title);if(title?.trim())try{await api('/api/title',{title});refresh()}catch(e){notice(e)}};
$('#addSource').onclick=()=>$('#sourceDialog').showModal();$('#cancelSource').onclick=()=>$('#sourceDialog').close();$('#closeVersion').onclick=()=>$('#versionDialog').close();
$('#sourceForm').onsubmit=async e=>{e.preventDefault();try{const title=$('#sourceTitle').value.trim(),file=$('#sourceFile').files[0];if(file?.name.toLowerCase().endsWith('.pdf')){const b64=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file)});await api('/api/evidence/pdf',{title,base64:b64})}else{const text=$('#sourceText').value||await file?.text();await api('/api/evidence',{title,text})}$('#sourceForm').reset();$('#sourceDialog').close();refresh()}catch(err){notice(err)}};
function setSelection(value){selection=value;$('#selectionContext').hidden=!value;$('#selectionText').textContent=value?'Selected: “'+value.text+'”':'';}
$('#clearSelection').onclick=()=>setSelection(null);
$('#paper').addEventListener('mouseup',captureSelection);
$('#paper').addEventListener('keyup',captureSelection);
function captureSelection(){
 const selected=window.getSelection();if(!selected.rangeCount||selected.isCollapsed)return;
 const range=selected.getRangeAt(0);
 const blockOf=node=>(node.nodeType===Node.ELEMENT_NODE?node:node.parentElement)?.closest('.markdown-block');
 const startBlock=blockOf(range.startContainer),endBlock=blockOf(range.endContainer);
 if(!startBlock||startBlock!==endBlock){setSelection(null);notice('Select text within one document block. For a broader change, describe the section in your request.');return;}
 const section=state.paper.sections.find(s=>s.id===startBlock.dataset.sectionId),block=section.blocks.find(b=>b.id===startBlock.dataset.blockId);
 const text=selected.toString(),start=block.text.indexOf(text);
 if(start<0||block.text.indexOf(text,start+1)!==-1){setSelection(null);notice('Select a unique passage without crossing Markdown formatting, or describe the passage in your request.');return;}
 // Python uses Unicode code points for offsets; JS string indices use UTF-16.
 setSelection({version_id:state.paper.id,section_id:section.id,block_id:block.id,text,start:Array.from(block.text.slice(0,start)).length,end:Array.from(block.text.slice(0,start+text.length)).length});
}
function documentMarkdown(p){return ['# '+p.title,...p.sections.flatMap(s=>[...(s.heading?['## '+s.heading]:[]),...s.blocks.map(b=>b.text)])].join('\n\n')+'\n';}
$('#editMarkdown').onclick=()=>{if(!state)return;editorVersion=state.paper.id;$('#markdownEditor').value=documentMarkdown(state.paper);$('#editorError').textContent='';$('#markdownDialog').showModal();};
$('#cancelMarkdown').onclick=()=>$('#markdownDialog').close();
$('#markdownForm').onsubmit=async event=>{event.preventDefault();$('#saveMarkdown').disabled=true;try{await api('/api/markdown',{markdown:$('#markdownEditor').value,base_version:editorVersion});$('#markdownDialog').close();await refresh()}catch(e){$('#editorError').textContent=e.message}finally{$('#saveMarkdown').disabled=false}};
$('#prompt').addEventListener('keydown',event=>{if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)){event.preventDefault();if(!$('#run').disabled)$('#run').click();}});
async function switchProject(id){
 if(busy){$('#projectSelect').value=projectId;return;}
 promptDrafts.set(projectId,$('#prompt').value);projectId=id;state=null;renderedVersion=null;setSelection(null);
 history.replaceState(null,'','?project='+encodeURIComponent(id));$('#prompt').value=promptDrafts.get(id)||'';
 for(const selector of ['#paper','#outline','#sources','#events','#versions'])clear($(selector));
 for(const id of ['run','undo','editTitle','editMarkdown','addSource'])$('#'+id).disabled=true;
 $('#version').textContent='Loading…';$('#documentStatus').textContent='LOADING PROJECT';
 $('#notice').textContent='';$('#exportMarkdown').href='/api/markdown?project='+encodeURIComponent(id);
 await refresh();
}
$('#projectSelect').onchange=event=>switchProject(event.target.value);
$('#newProject').onclick=()=>{$('#projectForm').reset();$('#projectError').textContent='';$('#projectDialog').showModal();$('#projectName').focus();};
$('#cancelProject').onclick=()=>$('#projectDialog').close();
$('#projectForm').onsubmit=async event=>{event.preventDefault();$('#createProject').disabled=true;try{const project=await api('/api/projects',{name:$('#projectName').value});$('#projectDialog').close();await switchProject(project.id)}catch(e){$('#projectError').textContent=e.message}finally{$('#createProject').disabled=false}};
refresh();setInterval(refresh,1800);
