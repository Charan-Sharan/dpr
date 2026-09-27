/* Durable reasoning UI; document rendering remains in app.js. */
let scholarshipTab='discussion', scholarshipFingerprint='', panelSession=null, panelProject=null;
$('.project-bar').append($('.scholarship-switch'));
const modeLabel=el('label','request-mode','Mode '),requestMode=el('select');
requestMode.id='requestMode';
for(const [value,label] of [['auto','Auto'],['discuss','Discuss'],['revise','Revise'],['review','Review whole paper']]){
 const option=el('option','',label);option.value=value;requestMode.append(option);
}
modeLabel.append(requestMode);$('.composer').prepend(modeLabel);modeLabel.hidden=true;
$('#scholarshipEnabled').onchange=async event=>{
 try{await api('/api/scholarship',{enabled:event.target.checked});scholarshipFingerprint='';await refresh()}
 catch(error){notice(error);event.target.checked=!!state?.project.dpr_enabled}
};
for(const tab of document.querySelectorAll('[data-tab]'))tab.onclick=()=>{
 scholarshipTab=tab.dataset.tab;scholarshipFingerprint='';renderScholarship();
};
$('#expandDiscussion').onclick=()=>{
 const expanded=document.body.classList.toggle('discussion-wide');
 $('#expandDiscussion').textContent=expanded?'Collapse':'Expand';$('#expandDiscussion').setAttribute('aria-expanded',String(expanded));
};
function actionButton(label,handler){
 const button=el('button','secondary',label);
 button.onclick=async()=>{button.disabled=true;try{await handler();await refresh()}catch(error){notice(error)}finally{button.disabled=false}};
 return button;
}
async function sessionAction(job,action,text='',extra={}){
 return api('/api/sessions/'+job.id+'/'+action,{text,...extra});
}
function askContribution(job,action,replyTo){
 const text=window.prompt(action==='continue'||action==='redirect'?'What objective should the next round pursue?':'Your contribution or instruction');
 if(text?.trim())return sessionAction(job,action,text,{reply_to:replyTo});
}
function renderScholarship(){
 if(!state)return;
 const enabled=!!state.project.dpr_enabled,data=state.scholarship||{sessions:[],memory:[]};
 $('#scholarshipEnabled').checked=enabled;modeLabel.hidden=!enabled;
 $('#scholarshipPanel').hidden=!enabled;$('#expandDiscussion').hidden=!enabled;
 $('#activityTitle').textContent=enabled?'Inquiry workspace':'Agent activity';
 $('#events').hidden=enabled;
 $('.compose-foot span').textContent=enabled?'Generated prose needs your approval. Explicit title changes and section moves save immediately.':'Reviewed edits update your draft. Disagreements need your decision.';
 $('#exportAudit').href='/api/audit?project='+encodeURIComponent(projectId);
 if(!enabled)return;
 for(const tab of document.querySelectorAll('[data-tab]'))tab.setAttribute('aria-pressed',String(tab.dataset.tab===scholarshipTab));
 const fingerprint=JSON.stringify([projectId,scholarshipTab,data,state.paper.id]);
 if(fingerprint===scholarshipFingerprint)return;
 const pane=$('#scholarshipContent'),chosen=window.getSelection();
 if(!chosen.isCollapsed&&pane.contains(chosen.anchorNode))return;
 scholarshipFingerprint=fingerprint;
 const scroll=$('.activity').scrollTop;clear(pane);
 if(scholarshipTab==='memory'){
   for(const item of [...data.memory].reverse()){
     const card=el('div','card');card.append(el('strong','',item.kind.replaceAll('_',' ')+' · '+item.status),el('p','',item.text),el('p','hint',item.authority+' · '+(item.stale?'Document changed; recheck':'Recorded against current document')));
     if(item.turn_id)card.append(actionButton('View originating discussion',()=>{
       scholarshipTab='discussion';scholarshipFingerprint='';renderScholarship();
       document.querySelector('[data-turn-id="'+CSS.escape(item.turn_id)+'"]')?.scrollIntoView({block:'center'});
     }));
     if(item.evidence_status)card.append(el('p','hint','Evidence: '+item.evidence_status.replaceAll('_',' ')));
     for(const citation of item.citations||[])card.append(actionButton('Inspect quotation',async()=>{
       const source=await api('/api/source/'+citation.source_id);$('#versionDetail').textContent=source.title+'\n\n'+citation.quote+'\n\nFull source:\n'+source.text;$('#versionDialog').showModal();
     }));
     for(const [action,label] of [['correct','Correct'],[item.status==='resolved'?'reopen':'resolve',item.status==='resolved'?'Reopen':'Resolve']]){
       card.append(actionButton(label,async()=>{const text=action==='correct'?window.prompt('Correct this memory entry',item.text):'';if(text!==null)await api('/api/memory',{id:item.id,action,text})}));
     }
     if(item.history.length){const history=el('details');history.append(el('summary','','Correction history'));for(const entry of item.history)history.append(el('p','',entry.action+': '+entry.text));card.append(history);}
     pane.append(card);
   }
   if(!data.memory.length)pane.append(el('p','','Assumptions, alternatives, questions, and your decisions will appear here.'));
 }else{
   for(const job of byTime(data.sessions).reverse()){
     const group=el('section','activity-run');group.dataset.sessionId=job.id;
     const header=el('div','card');header.append(el('strong','',job.prompt),el('span','stamp',activityStamp(job.at)),el('p','',job.status.replaceAll('_',' ')+' · Round '+job.round),el('p','',job.summary));
     const progress=job.mode==='revise'?job.tasks.filter(t=>['committed','rejected','superseded'].includes(t.status)).length+'/'+job.tasks.length+' editing tasks resolved'
       :job.mode==='review'?(job.coverage||[]).length+' sections reviewed':job.contributions+'/6 contributions';
     header.append(el('p','hint',progress+' · '+job.calls+'/40 provider attempts'));
     if(scholarshipTab==='discussion'){
       if(['queued','running'].includes(job.status)){
         header.append(actionButton('Pause',()=>sessionAction(job,'pause')),actionButton('My turn',()=>sessionAction(job,'hand')),actionButton('Stop',()=>sessionAction(job,'stop')));
       }else if(job.status==='paused')header.append(actionButton('Resume',()=>sessionAction(job,'resume')));
       if(job.status!=='completed')header.append(actionButton('Reply',()=>askContribution(job,'turn')),actionButton('Inject context',()=>askContribution(job,'inject')));
       header.append(actionButton('Redirect',()=>askContribution(job,'redirect')),actionButton(job.status==='completed'?'Start follow-up':job.mode==='revise'?'Continue request':'Continue round',()=>askContribution(job,'continue')));
       const pending=job.tasks.filter(t=>['awaiting_approval','disputed','evidence_required','needs_input','waiting','blocked'].includes(t.status));
       if(pending.length){
         for(const task of pending)header.append(el('p','',task.instruction+': '+(task.reason||task.status.replaceAll('_',' '))));
         header.append(actionButton('View decisions / required input',()=>{scholarshipTab='decisions';scholarshipFingerprint='';renderScholarship();}));
       }
       if(job.status==='paused')header.append(actionButton('Edit panel',()=>openPanel(job)),actionButton('Recommend panel',()=>sessionAction(job,'recommend_panel')));
       if(job.checkpoint&&!['queued','running','completed'].includes(job.status))header.append(actionButton('Mark reviewed',()=>sessionAction(job,'finalize')));
       const panel=el('details');panel.append(el('summary','','Participants and model diversity'));
       for(const member of job.panel)panel.append(el('p','',member.perspective+' · '+member.provider+' / '+(job.actual_models?.[member.id]||member.model)));
       const models=job.panel.map(p=>(job.actual_models?.[p.id]||p.model).replace(/:free$/,''));
       panel.append(el('p','hint',new Set(models).size<models.length?'Reduced model diversity: participants share a model.':'Different models can still share biases and errors.'));
       header.append(panel);
     }
     group.append(header);
     if(scholarshipTab==='discussion'){
       for(const turn of job.turns){
         const card=el('div','card contribution');card.dataset.turnId=turn.id;
         card.append(el('strong','',turn.role+(turn.ignored?' · repeated contribution':'')),el('span','stamp',activityStamp(turn.at)),renderMarkdown(turn.text));
         if(turn.model)card.append(el('p','hint',turn.model+(turn.independent?' · independent initial assessment':'')));
         if(turn.reply_to)card.append(el('p','hint','In reply to '+turn.reply_to));
         card.append(actionButton('Challenge / reply',()=>askContribution(job,'turn',turn.id)));group.append(card);
       }
       if(job.checkpoint){const card=el('div','card checkpoint');card.append(el('strong','','Researcher checkpoint'),el('p','',job.checkpoint.summary||'Review the discussion.'));for(const key of ['disagreements','missing_evidence','choices']){if(Array.isArray(job.checkpoint[key])){card.append(el('strong','',key.replaceAll('_',' ')));for(const text of job.checkpoint[key])card.append(el('p','',text));}}group.append(card);}
       if(job.mode==='review'){
         const reviewed=job.coverage||[],version=job.review_version;
         group.append(el('p','hint','Reviewed sections: '+reviewed.length+'. '+(version!==state.paper.id?'Document changed; review is stale.':reviewed.length===state.paper.sections.length&&job.synthesis_complete?'All current sections covered, with cross-section synthesis.':'Partial review: section coverage or cross-section synthesis remains unfinished.')));
       }
     }else if(scholarshipTab==='decisions'){
       for(const task of job.tasks)renderProposal(job,task,group);
     }else{
       for(const event of [...job.activity].sort((a,b)=>a.seq-b.seq)){
         const card=el('div','card activity-event');card.append(el('strong','',event.seq+' · '+event.kind),el('span','stamp',activityStamp(event.at)),el('p','',event.message));
         const detail=el('details');detail.append(el('summary','','Details'),el('pre','',JSON.stringify(event,null,2)));card.append(detail);group.append(card);
       }
     }
     pane.append(group);
   }
   if(!data.sessions.length)pane.append(el('p','','Ask a research question, request a revision, or review your paper. Generated prose stays pending until you approve it.'));
   if(scholarshipTab==='activity'&&state.jobs.some(j=>j.schema!==2)){
     const legacy=el('details');legacy.append(el('summary','','Legacy request history (read-only)'));
     for(const job of byTime(state.jobs.filter(j=>j.schema!==2)).reverse())legacy.append(el('p','',job.prompt+' · '+job.status));pane.append(legacy);
   }
 }
 $('.activity').scrollTop=scroll;
}
function renderProposal(job,task,group){
 const card=el('div','card');card.dataset.taskId=task.id;
 card.append(el('strong','',task.instruction),el('p','',task.status.replaceAll('_',' ')));
 if(task.reason)card.append(decisionSection(task.status==='evidence_required'?'Evidence concerns':task.status==='committed'?'Original review concerns':'Review concerns',task.reason,task.status==='evidence_required'?'concerns':'review'));
 if(task.proposal){
   const before=el('details');before.append(el('summary','','Before'),el('pre','diff-before',task.before||'(empty section)'));
   const after=decisionSection(task.status==='committed'?'Approved text':'Proposed text — not saved',task.proposal.text,'proposed',true);card.append(before,after);
   if(task.diff){const diff=el('details');diff.append(el('summary','','Line-by-line diff'),el('pre','',task.diff));card.append(diff);}
   if(task.review)card.append(decisionSection('Review',task.review.rationale,'review'));
   if(task.audit)card.append(decisionSection('Evidence audit',task.audit.rationale,'audit'));
   for(const claim of Array.isArray(task.proposal.claims)?task.proposal.claims:[])for(const citation of Array.isArray(claim?.citations)?claim.citations:[]){
     if(!citation||typeof citation.source_id!=='string')continue;
     card.append(actionButton('Inspect source passage',async()=>{
       const source=await api('/api/source/'+citation.source_id);
       $('#versionDetail').textContent=source.title+'\n\nClaim: '+claim.text+'\n\nQuoted passage: '+citation.quote+'\n\nFull source:\n'+source.text;
       $('#versionDialog').showModal();
     }));
   }
 }
 if(['awaiting_approval','evidence_required','disputed','blocked','needs_input'].includes(task.status)){
   const actions=el('div','decision-actions');
   if(task.status==='evidence_required')actions.append(el('p','decision-note','Allow saves this proposed text without verified evidence. The evidence concern remains recorded.'));
   const send=async(choice)=>{
     let rationale='';
     if(choice==='allow'){
       if(!window.confirm('This saves unverified text. It does not resolve the evidence concern. Continue?'))return;
       rationale=window.prompt('Explain why you are allowing this unverified revision');if(!rationale?.trim())return;
     }
     if(choice==='revise'){rationale=window.prompt('What should change, or what evidence can you supply?');if(!rationale?.trim())return;}
     await api('/api/sessions/'+job.id+'/decide',{task_id:task.id,choice,rationale});
   };
   if(['awaiting_approval','disputed'].includes(task.status))actions.append(actionButton('Approve revision',()=>send('approve')));
   if(task.status==='evidence_required')actions.append(actionButton('Allow without verified evidence',()=>send('allow')));
   actions.append(actionButton('Request revision',()=>send('revise')),actionButton('Reject',()=>send('reject')));
   card.append(actions);
   if(['queued','running'].includes(job.status))for(const button of card.querySelectorAll('button'))button.disabled=true;
 }
 group.append(card);
}
function panelRow(member={perspective:'Additional perspective',provider:'groq',model:'openai/gpt-oss-20b',role:'skeptic'}){
 const row=el('fieldset');
 for(const field of ['perspective','provider','model','role']){
   const label=el('label','',field+' '),input=['provider','role'].includes(field)?el('select'):el('input');
   if(input.tagName==='SELECT')for(const value of field==='provider'?['groq','openrouter']:['writer','skeptic','methodology','evidence','planner']){const option=el('option','',value);option.value=value;input.append(option);}
   input.name=field;input.value=member[field];input.required=true;label.append(input);row.append(label);
 }
 const remove=el('button','secondary','Remove');remove.type='button';remove.onclick=()=>row.remove();row.append(remove);$('#panelRows').append(row);
}
function openPanel(job){panelSession=job.id;panelProject=projectId;clear($('#panelRows'));for(const member of job.panel)panelRow(member);$('#panelError').textContent='';$('#panelDialog').showModal();}
$('#addParticipant').onclick=()=>{if($('#panelRows').children.length<5)panelRow()};
$('#cancelPanel').onclick=()=>$('#panelDialog').close();
$('#panelForm').onsubmit=async event=>{event.preventDefault();try{
 const panel=Array.from($('#panelRows').children).map(row=>Object.fromEntries(Array.from(row.querySelectorAll('input,select')).map(input=>[input.name,input.value])));
 await api('/api/sessions/'+panelSession+'/panel',{panel},panelProject);$('#panelDialog').close();await refresh();
 }catch(error){$('#panelError').textContent=error.message}};
