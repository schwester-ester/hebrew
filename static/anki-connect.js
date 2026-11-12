/* AnkiConnect is contacted only after the visitor chooses Connect & sync.
   Collection data and the optional API key never go to the hosted backend. */
(() => {
  const endpoint='http://127.0.0.1:8765';
  let connected=false;
  const key=()=>document.getElementById('ankiKey').value;
  const normalize=text=>text.normalize('NFKD').replace(/[^א-ת\s׳'״"]/gu,'').trim().replace(/׳/g,"'").replace(/״/g,'"');
  const deckQuery=deck=>'deck:"'+deck.replace(/\\/g,'\\\\').replace(/"/g,'\\"')+'"';

  async function call(action,params={}) {
    const controller=new AbortController();
    const timer=setTimeout(()=>controller.abort(),action==='requestPermission' ? 120000 : 30000);
    let response;
    try {
      // text/plain avoids an unnecessary JSON preflight on the local service.
      response=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'text/plain'},
        credentials:'omit',signal:controller.signal,
        body:JSON.stringify({action,version:6,params,...(action!=='requestPermission' && key() ? {key:key()} : {})})});
      if(!response.ok)throw new Error('HTTP '+response.status);
    } catch(error) {
      throw Object.assign(new Error('Could not reach AnkiConnect. Open Anki on this computer, install or update AnkiConnect, and allow this site’s local network access in your browser. See connection help above.'),{connectionLost:true});
    } finally {clearTimeout(timer);}
    let payload;
    try {payload=await response.json();} catch {throw new Error('AnkiConnect returned an invalid response. Update the add-on and restart Anki.');}
    if(!payload || !Object.hasOwn(payload,'result') || !Object.hasOwn(payload,'error'))throw new Error('AnkiConnect returned an invalid response.');
    if(payload.error)throw new Error(String(payload.error));
    return payload.result;
  }

  async function connect() {
    connected=false;
    const permission=await call('requestPermission');
    if(permission?.permission!=='granted')throw new Error('Access to Anki was denied. Approve this website in Anki, then retry. See connection help above.');
    if((permission.requireApiKey || permission.requireApikey) && !key())throw new Error('AnkiConnect requires your API key. Enter it under connection help, then connect again.');
    const decks=await call('deckNames');
    connected=true;
    return {decks};
  }

  async function known(deck,field='') {
    if(!connected)throw new Error('Connect to Anki first.');
    const ids=await call('findNotes',{query:deckQuery(deck)});
    const words=new Set(), entries=new Set();
    for(let offset=0;offset<ids.length;offset+=200) {
      const notes=await call('notesInfo',{notes:ids.slice(offset,offset+200)});
      for(const note of notes) {
        const own=(note.tags || []).filter(tag=>/^(pealim::\d+|hebrew-reader::manual-[a-f0-9]{32})$/.test(tag));
        if(own.length){for(const tag of own)entries.add(tag.split('::')[1]);continue;}
        const fields=note.fields || {};
        const front=field ? fields[field] : Object.values(fields).sort((a,b)=>(a.order || 0)-(b.order || 0))[0];
        if(field && !front)throw new Error(`Field “${field}” does not exist in note model ${note.modelName || ''}.`);
        // Parse inert HTML without loading images or other external resources.
        const template=document.createElement('template');
        template.innerHTML=front?.value || '';
        template.content.querySelectorAll('br').forEach(br=>br.replaceWith(' '));
        for(const part of template.content.textContent.split(/\s*[/;|]\s*/)) {
          if(/[א-ת]/.test(part) && !/[A-Za-z]/.test(part))words.add(normalize(part));
        }
      }
    }
    return {words:[...words],entries:[...entries]};
  }

  async function createDeck(name) {
    if(!connected)throw new Error('Connect to Anki first.');
    name=name.trim();
    if(!name || name.length>200 || /[\x00-\x1f]/.test(name))throw new Error('Enter a deck name between 1 and 200 characters.');
    await call('createDeck',{deck:name});
    return {deck:name,decks:await call('deckNames')};
  }

  async function add(deck,prepared,field='',progress=()=>{}) {
    if(!connected)throw new Error('Connect to Anki first.');
    if(!(await call('deckNames')).includes(deck))throw new Error('Select an existing Anki deck.');
    const existing=await known(deck,field), words=new Set(existing.words), ids=new Set(existing.entries);
    const model=prepared.model;
    if(!(await call('modelNames')).includes(model.modelName))await call('createModel',model);
    else if(JSON.stringify(await call('modelFieldNames',{modelName:model.modelName}))!==JSON.stringify(model.inOrderFields)) {
      throw new Error('An existing Hebrew Reader model has incompatible fields. Rename it in Anki, then retry.');
    }
    const result={imported:[],duplicates:[],failed:[]};
    for(const [index,card] of prepared.cards.entries()) {
      progress(index+1,prepared.cards.length);
      try {
        const tag=card.tags[1];
        if(ids.has(card.id) || (!card.manual && words.has(card.word)) || (await call('findNotes',{query:deckQuery(deck)+' tag:'+tag})).length) {
          result.duplicates.push(card.id);continue;
        }
        if(card.recording) {
          const filename=await call('storeMediaFile',{filename:card.audio_filename,data:card.recording});
          if(filename!==card.audio_filename)throw new Error('Anki could not save the recording. Retry this card.');
        }
        const note=await call('addNote',{note:{deckName:deck,modelName:model.modelName,fields:card.fields,
          options:{allowDuplicate:true},tags:card.tags}});
        if(!note)throw new Error('Anki did not return a note ID.');
        result.imported.push(card.id);ids.add(card.id);
      } catch(error) {
        result.failed.push({id:card.id,error:error.message});
        if(error.connectionLost) {
          for(const pending of prepared.cards.slice(index+1))result.failed.push({id:pending.id,error:'Not sent because the connection to Anki was lost. Retry after reconnecting.'});
          break;
        }
      }
    }
    return result;
  }
  window.IvritAnki={connect,known,createDeck,add};
})();
