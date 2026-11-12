const $ = id => document.getElementById(id);
const publicSite=document.body.dataset.public==='true';
const apiBase=document.querySelector('meta[name="ivrit-api-base"]')?.content || '';
const apiURL=path=>apiBase+'/api/'+path;
let browserLoaded=!publicSite;
const audioURLs=new Map();
let words = [], selected = new Set(), queue = [], position = -1, basket = new Map(), lookupVersion = 0;
let resultsByWord = new Map(), knownIds = new Set(), skipped = new Set();
let knownWords = new Set();
let syncedDeck = '', reviewBusy = false, ankiConnected = false, connectionBusy = false;
let selectionAnchor = null, translationVersion = 0;
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const he = value => `<bdi lang="he" dir="rtl">${escapeHTML(value)}</bdi>`;
function notice(message) { $('notice').textContent = message; $('notice').hidden = !message; }
async function api(path, data) {
  if(publicSite) {
    await browserReady;
    if(path==='decks')return IvritAnki.connect();
    if(path==='sync')return IvritAnki.known(data.deck,data.field);
    if(path==='create-deck')return IvritAnki.createDeck(data.name);
    if(path==='skip') {
      const updated=new Set(skipped);
      if(data.remove)updated.delete(data.word);else updated.add(data.word);
      await IvritStorage.set('skips',[...updated]);
      skipped=updated;
      return {skipped:[...skipped]};
    }
  }
  // Deck names and collection contents stay on the visitor's computer.
  const payload=publicSite && data ? Object.fromEntries(Object.entries(data).filter(([key])=>key!=='deck')) : data;
  const response = await fetch(apiURL(path), data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Request failed. Please retry.');
  if(publicSite && path==='text') {
    result.skipped=[...skipped];
    for(const word of result.tokens) {
      word.known=skipped.has(word.key) || knownWords.has(word.key);
      word.reason=skipped.has(word.key) ? 'Previously skipped' : knownWords.has(word.key) ? 'In your Anki deck' : '';
    }
  }
  if(publicSite && path==='lookup')for(const entry of result.entries)entry.known=knownIds.has(entry.id) || knownWords.has(entry.canonical?.plain);
  return result;
}
function deck() { return $('deck').value; }
function snapshot() {
  if(publicSite){if(browserLoaded) IvritStorage.set('basket',[...basket.values()]).catch(error=>notice(error.message));}
  else localStorage.setItem('ivrit-basket', JSON.stringify([...basket.values()]));
}
function cardAudio(entry) {
  if(!publicSite)return '/api/audio/'+entry.id;
  if(!entry.recording)return '';
  if(!audioURLs.has(entry.id)) {
    const bytes=Uint8Array.from(atob(entry.recording),c=>c.charCodeAt(0));
    audioURLs.set(entry.id,URL.createObjectURL(new Blob([bytes],{type:'audio/wav'})));
  }
  return audioURLs.get(entry.id);
}
function renderBasket() {
  snapshot();
  $('basketCount').textContent = `${basket.size} meaning${basket.size === 1 ? '' : 's'}`;
  $('export').disabled = !basket.size || reviewBusy;
  $('import').disabled = !basket.size || !syncedDeck || deck() !== syncedDeck || reviewBusy || connectionBusy;
  $('syncCards').disabled=$('import').disabled;
  $('deck').disabled=!ankiConnected || reviewBusy || connectionBusy;
  $('connect').disabled=reviewBusy || connectionBusy;
  $('createDeck').disabled=!ankiConnected || reviewBusy || connectionBusy;
  $('newDeck').disabled=reviewBusy || connectionBusy;
  $('knownField').disabled=reviewBusy || connectionBusy;
  $('basket').innerHTML = basket.size ? [...basket.values()].map(e => `<div class="basket-item"><span class="lemma">${he(e.canonical.plain)}</span><span class="small">${escapeHTML(e.meaning)}${e.source === 'manual' ? '<br>Added manually' : ''}</span>${e.audio_filename ? `<audio controls preload="none" src="${cardAudio(e)}" aria-label="Your recording"></audio>` : ''}<button class="quiet" data-remove="${e.id}">Remove</button></div>`).join('') : '<p class="small">Choose meanings as you read. Your selected words will appear here.</p>';
}
if(!publicSite)try { for (const e of JSON.parse(localStorage.getItem('ivrit-basket') || '[]')) if(e?.canonical && /^(\d+|manual-[a-f0-9]{32})$/.test(e.id)) basket.set(e.id,e); } catch {}
function renderPassage() {
  const text = Array.from($('input').value);
  let html = '', end = 0;
  words.forEach((w,i) => {
    html += escapeHTML(text.slice(end,w.start).join(''));
    html += `<button class="token ${w.known ? 'known' : ''} ${selected.has(i) ? 'selected' : ''} ${queue[position] === i ? 'active' : ''}" data-index="${i}" aria-pressed="${selected.has(i)}" title="${escapeHTML(w.reason || 'Click to explore; Ctrl / ⌘ click to select')}">${escapeHTML(w.text)}</button>`;
    end = w.end;
  });
  html += escapeHTML(text.slice(end).join(''));
  $('passage').innerHTML = html;
  $('textCount').textContent = `${words.length} words · ${words.filter(w => w.known).length} known or skipped`;
  $('selectedCount').textContent = selected.size;
  $('selected').disabled = !selected.size;
  updateTranslationScope();
}
async function startReading() {
  notice('');
  const data = await api('text', {text:$('input').value,deck:deck()});
  words = data.tokens;
  if(!words.length) throw new Error('Paste a text containing Hebrew words first.');
  skipped = new Set(data.skipped); renderSkips();
  selected.clear(); selectionAnchor=null; queue=[]; position=-1; lookupVersion++;
  invalidateTranslation();
  $('editor').hidden = true; $('reading').hidden = false;
  $('empty').hidden = false; $('explorer').hidden = true;
  renderPassage();
}
function beginQueue(indices, includeKnown=false) {
  queue = indices.filter(i => includeKnown || !words[i].known); position = -1;
  if (!queue.length) {notice('No unknown words in this selection. You can click a muted word to review it.'); return;}
  go(1);
}
function progress() {
  $('position').textContent = `Word ${position+1} of ${queue.length}`;
  $('previous').disabled = position <= 0;
  $('next').disabled = position >= queue.length-1;
}
async function go(delta) {
  let p = position + delta;
  while(p >= 0 && p < queue.length && words[queue[p]].known) p += delta;
  if(p < 0 || p >= queue.length) {
    if(delta > 0) notice('You have reached the end of this review. Choose another word or import your selected meanings.');
    return;
  }
  position = p;
  await showWord();
}
async function showWord(force=false) {
  const version = ++lookupVersion;
  const w = words[queue[position]];
  if(!w) return;
  renderPassage(); progress();
  $('empty').hidden=true; $('explorer').hidden=false;
  $('current').textContent=w.text;
  $('skip').textContent = skipped.has(w.key) ? 'Unskip this word' : 'I know this word · skip';
  const key = deck() + ':' + w.key;
  $('results').innerHTML='<div class="loading"><span class="spinner"></span><p>Looking up this spelling and its possible prefixes…<br>First lookups may take a little time.</p></div>';
  try {
    const result = !force && resultsByWord.has(key) ? resultsByWord.get(key) : await api('lookup',{word:w.key,deck:deck()});
    resultsByWord.set(key,result);
    if(version !== lookupVersion) return;
    renderResults(result);
    if(result.entries.length && result.entries.every(e => e.known || knownIds.has(e.id)) && !result.warnings.length) {
      words.forEach(token => {if(token.key === w.key) {token.known=true;token.reason='All dictionary meanings are in your Anki deck';}});
      renderPassage();
      if(position < queue.length-1) {notice(`Skipped ${w.text}: all dictionary meanings are already in your deck.`); go(1);}
    }
  } catch(error) {if(version === lookupVersion) $('results').innerHTML=`<p class="warning">${escapeHTML(error.message)}</p>`;}
}
function renderResults(result) {
  const entries = result.entries;
  $('results').innerHTML = (result.warnings.length ? `<p class="warning">Some lookups failed. Results may be incomplete. Use “Look up again” to retry.</p><details><summary>Lookup details</summary><p class="small">${result.warnings.map(escapeHTML).join('<br>')}</p></details>` : '') +
    (!entries.length ? '<div class="loading">No exact dictionary matches found.<br>Names, slang, and some spellings may be absent from Pealim.</div>' : entries.map(e => {
      const c = e.canonical;
      const known = e.known || knownIds.has(e.id);
      return `<article class="sense ${basket.has(e.id) ? 'chosen' : ''} ${known ? 'known-sense' : ''}"><div class="sense-header"><span class="lemma">${he(c?.vowelled || e.analyses[0].matches[0].vowelled)}</span><button data-add="${e.id}" ${known || !e.importable ? 'disabled' : ''}>${known ? 'Already in deck' : !e.importable ? 'No canonical form' : basket.has(e.id) ? 'Selected ✓' : '+ Add meaning'}</button></div><div class="pronunciation">${escapeHTML(c?.pronunciation || '')}${c?.stress ? ` · stressed vowel: ${escapeHTML(c.stress)}` : ''}</div><div class="meaning">${escapeHTML(e.meaning)}</div><p class="grammar">${escapeHTML(e.characteristics)}${e.root ? ` · root ${he(e.root)}` : ''}${e.plural ? `<br>Plural: ${he(e.plural.vowelled)} · ${escapeHTML(e.plural.pronunciation)}` : ''}${e.irregular_plural ? '<br>Irregular plural ending · singular and plural included on the card' : ''}${e.plural_only ? '<br>Plural-only noun · preserved as listed' : ''}</p><div class="analysis">${e.analyses.map(a => `${a.prefix ? `${he(a.prefix + '־')} ${escapeHTML(a.explanation)} → ${he(a.base)}` : 'Matches the original spelling'}<br>${a.matches.map(f => `${he(f.vowelled)} · ${escapeHTML(f.pronunciation)} · ${escapeHTML(f.description)}`).join('<br>')}`).join('<br>')}</div><p><a href="${escapeHTML(e.url)}" target="_blank" rel="noopener">Full forms on Pealim ↗</a></p>${c?.audio?.startsWith('https://audio.pealim.com/') ? `<audio controls preload="none" src="${escapeHTML(c.audio)}" aria-label="Pronunciation of ${escapeHTML(c.plain)}"></audio>` : ''}</article>`;
    }).join('')) + `<details style="margin-top:15px"><summary>Prefix candidates (${result.candidates.length})</summary><p class="small">${result.candidates.map(c => `${he(c.base)} · ${escapeHTML(c.explanation)}`).join('<br>')}</p></details>`;
  $('results').querySelectorAll('[data-add]').forEach(button => button.onclick = () => {
    if(reviewBusy) return;
    const entry = entries.find(e => e.id === button.dataset.add);
    if(basket.has(entry.id)) basket.delete(entry.id); else basket.set(entry.id,entry);
    renderBasket(); renderResults(result);
  });
}
function renderSkips() {
  $('skips').innerHTML = skipped.size ? [...skipped].map(word => `<button class="quiet" data-unskip="${escapeHTML(word)}">${he(word)} ×</button>`).join('') : '<span class="small">No skipped words yet.</span>';
}
async function connect() {
  connectionBusy=true; ankiConnected=false; forgetDeck();renderBasket();
  $('connection').textContent='Connecting… approve access in Anki and your browser if asked.';
  try {
    const {decks} = await api('decks');
    ankiConnected=true;
    const preferred = deck() || localStorage.getItem('ivrit-deck');
    $('deck').innerHTML = decks.length ? decks.map(d => `<option value="${escapeHTML(d)}">${escapeHTML(d)}</option>`).join('') : '<option value="">Create a deck below</option>';
    if(decks.includes(preferred)) $('deck').value=preferred;
    if(decks.length)await sync();
    else $('connection').textContent='Connected · enter a new deck name and choose Create deck.';
  } catch(error) {syncedDeck=''; $('connection').textContent=error.message;renderBasket();}
  finally {connectionBusy=false;renderBasket();}
}
function forgetDeck() {
  syncedDeck='';knownIds.clear();knownWords.clear();resultsByWord.clear();lookupVersion++;
  for(const word of words){word.known=skipped.has(word.key);word.reason=word.known ? 'Previously skipped' : '';}
  if(words.length)renderPassage();
}
async function sync() {
  const selectedDeck=deck();
  forgetDeck();connectionBusy=true;renderBasket();
  $('connection').textContent='Reading the selected Anki deck…';
  try {
    const result = await api('sync',{deck:selectedDeck,field:$('knownField').value.trim()});
    if(deck() !== selectedDeck) return;
    syncedDeck=selectedDeck; knownIds=new Set(result.entries); resultsByWord.clear();
    localStorage.setItem('ivrit-deck',selectedDeck);
    $('connection').textContent=`Connected · ${result.words.length + result.entries.length} known words / meanings`;
    knownWords = new Set(result.words);
    for(const [id, entry] of basket) if(knownIds.has(id) || (entry.source !== 'manual' && knownWords.has(entry.canonical.plain))) basket.delete(id);
    renderBasket();
    if(words.length) await startReading();
  } catch(error) {$('connection').textContent=error.message;throw error;}
  finally {connectionBusy=false;renderBasket();}
}
function handle(fn) {return async (...args) => {try {await fn(...args);} catch(error) {notice(error.message);}};}
$('settingsToggle').onclick=()=>{$('settings').hidden=!$('settings').hidden;};
$('connect').onclick=handle(connect);
$('deck').onchange=handle(sync);
$('createDeck').onclick=handle(async()=>{
  connectionBusy=true;renderBasket();
  try {
    const result=await api('create-deck',{name:$('newDeck').value});
    $('deck').innerHTML=result.decks.map(d=>`<option value="${escapeHTML(d)}">${escapeHTML(d)}</option>`).join('');
    $('deck').value=result.deck;$('newDeck').value='';
    await sync();
  } catch(error) {$('connection').textContent=error.message;throw error;}
  finally {connectionBusy=false;renderBasket();}
});
$('syncCards').onclick=()=>{$('import').click();};
if(publicSite)$('ankiOrigin').textContent=location.origin;
$('read').onclick=handle(startReading);
$('example').onclick=()=>{$('input').value='קראתי ספר טוב בבית. הילדים משחקים בגינה, ועל השולחנות יש ספרים חדשים.';$('editor').hidden=false;$('reading').hidden=true;};
$('edit').onclick=()=>{lookupVersion++; $('editor').hidden=false;$('reading').hidden=true;$('explorer').hidden=true;$('empty').hidden=false;};
$('passage').onclick=event=>{
  const token=event.target.closest('[data-index]');if(!token) return;
  const i=Number(token.dataset.index);
  if(event.shiftKey){
    if(!event.ctrlKey && !event.metaKey) selected.clear();
    for(let index=Math.min(selectionAnchor ?? i,i);index<=Math.max(selectionAnchor ?? i,i);index++) selected.add(index);
    renderPassage();
  } else if(event.ctrlKey || event.metaKey){selected.has(i) ? selected.delete(i) : selected.add(i);selectionAnchor=i;renderPassage();}
  else {selected=new Set([i]);selectionAnchor=i;queue=words.map((_,index)=>index).filter(index=>index===i || !words[index].known);position=queue.indexOf(i);showWord();}
};
$('all').onclick=()=>beginQueue(words.map((_,i)=>i));
$('selected').onclick=()=>beginQueue([...selected].sort((a,b)=>a-b));
$('clear').onclick=()=>{selected.clear();selectionAnchor=null;renderPassage();};
$('previous').onclick=()=>go(-1);$('next').onclick=()=>go(1);$('retry').onclick=()=>showWord(true);
document.addEventListener('keydown',event=>{
  if(event.target.closest('input,textarea,select,audio,form') || event.ctrlKey || event.metaKey || event.altKey || position<0 || $('explorer').hidden) return;
  if(event.key==='ArrowLeft' || event.key==='ArrowRight'){event.preventDefault();go(event.key==='ArrowLeft' ? 1 : -1);}
});
$('skip').onclick=handle(async()=>{
  const w=words[queue[position]],remove=skipped.has(w.key);
  const result=await api('skip',{word:w.key,remove});skipped=new Set(result.skipped);renderSkips();
  words.forEach(token=>{if(token.key===w.key){token.known=!remove;token.reason=remove ? '' : 'Previously skipped';}});renderPassage();
  $('skip').textContent=remove ? 'I know this word · skip' : 'Unskip this word';
  if(!remove && position<queue.length-1) go(1);
});
$('skips').onclick=handle(async event=>{
  const button=event.target.closest('[data-unskip]');if(!button)return;
  const result=await api('skip',{word:button.dataset.unskip,remove:true});skipped=new Set(result.skipped);renderSkips();
  if(words.length) await startReading();
});
$('basket').onclick=event=>{if(reviewBusy)return;const button=event.target.closest('[data-remove]');if(button){basket.delete(button.dataset.remove);renderBasket();if(position>=0)showWord();}};
$('import').onclick=handle(async()=>{
  reviewBusy=true;renderBasket();$('import').textContent='Syncing…';$('syncCards').textContent='Syncing…';
  try {
    const result=publicSite ? await IvritAnki.add(deck(),await api('anki-prepare',{entries:[...basket.values()]}),$('knownField').value.trim(),
      (current,total)=>{$('connection').textContent=`Sending card ${current} of ${total} to ${deck()}…`;}) : await api('import',{deck:deck(),ids:[...basket.keys()]});
    for(const id of [...result.imported,...result.duplicates]){basket.delete(id);knownIds.add(id);}
    resultsByWord.clear();
    const message=`Imported ${result.imported.length} meanings. ${result.duplicates.length} already in deck.${result.failed.length ? '\nNot imported: ' + result.failed.map(f=>f.error).join('; ') : ''}`;
    notice(message);$('connection').textContent=message;
    if(position>=0)showWord();
  } catch(error) {$('connection').textContent=error.message;throw error;}
  finally {reviewBusy=false;$('import').textContent='Sync cards to Anki ↗';$('syncCards').textContent='Sync cards to Anki ↗';renderBasket();}
});
$('export').onclick=handle(async()=>{
  if(publicSite)await browserReady;
  const payload=publicSite ? {entries:[...basket.values()]} : {ids:[...basket.keys()]};
  const response=await fetch(apiURL('export'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  if(!response.ok)throw new Error((await response.json()).error);
  const archive=response.headers.get('Content-Type').includes('application/zip');
  const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download=archive ? 'hebrew-vocabulary.zip' : 'hebrew-vocabulary.tsv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  notice((archive ? 'ZIP downloaded. Extract it and copy the WAV files into your Anki profile’s collection.media folder. ' : 'TSV downloaded. ') + 'Import the TSV as Basic, map Front and Back, and allow HTML. Choose “import as new notes” to retain meanings sharing a spelling.' + (publicSite ? '' : ' Sync your deck after importing.'));
});

function translationParts() {
  const input=$('input');
  if(!$('editor').hidden) return [input.value.slice(input.selectionStart,input.selectionEnd) || input.value];
  if(!selected.size) return [input.value];
  const indices=[...selected].sort((a,b)=>a-b), ranges=[];
  for(const i of indices) {
    const last=ranges[ranges.length-1];
    if(last && last[1]===i-1) last[1]=i; else ranges.push([i,i]);
  }
  const chars=Array.from(input.value);
  return ranges.map(([first,last])=>chars.slice(words[first].start,words[last].end).join(''));
}
function updateTranslationScope() {
  const input=$('input'), count=$('editor').hidden ? selected.size : input.selectionEnd-input.selectionStart;
  $('translationScope').textContent=count ? ($('editor').hidden ? `${count} selected words` : 'Highlighted text') + ' · Google Translate' : 'Full text · Google Translate';
}
function invalidateTranslation() {
  translationVersion++; $('translationPanel').hidden=true;
  $('translate').disabled=false; $('translate').textContent='Translate to English';
  updateTranslationScope();
}
$('input').addEventListener('input',invalidateTranslation);
$('input').addEventListener('select',updateTranslationScope);
$('input').addEventListener('keyup',updateTranslationScope);
$('translate').onclick=handle(async()=>{
  const parts=translationParts().filter(p=>p.trim());
  if(!parts.length) throw new Error('Enter some Hebrew text first.');
  const version=++translationVersion;
  $('translationPanel').hidden=false; $('translationOutput').textContent='';
  $('translationStatus').textContent='Translating to English… Selected text is sent to Google.';
  $('translate').disabled=true; $('translate').textContent='Translating…';
  const link=$('googleTranslate');
  link.href='https://translate.google.com/?sl=he&tl=en&text='+encodeURIComponent(parts.join('\n\n'))+'&op=translate';
  link.hidden=false;
  try {
    const result=await api('translate',{parts});
    if(version!==translationVersion) return;
    $('translationStatus').textContent=`${parts.length > 1 ? parts.length+' selected passages' : 'Hebrew → English'} · Google Translate`;
    $('translationOutput').replaceChildren(...result.translations.map(text=>{const p=document.createElement('p');p.textContent=text;return p;}));
  } catch(error) {if(version===translationVersion) $('translationStatus').textContent=error.message;}
  finally {if(version===translationVersion) {$('translate').disabled=false;$('translate').textContent='Translate to English';}}
});
$('closeTranslation').onclick=()=>{invalidateTranslation();};
// Native textarea selections work before reading. Reading mode adds disjoint word/range selection.
const editorHint=document.createElement('span');editorHint.className='small';editorHint.textContent='Highlight text to translate part of it. Start reading to select multiple passages with Ctrl / ⌘ or Shift.';
editorHint.style.cssText='display:block;padding:0 24px 16px;line-height:1.6';$('editor').append(editorHint);
$('edit').addEventListener('click',updateTranslationScope);
$('example').addEventListener('click',invalidateTranslation);

let recorder=null, recordStream=null, recording='', recordURL='', recordTimer=null, recordSession=0;
let recordState='idle';
function manualError(message) {$('manualError').textContent=message;$('manualError').hidden=!message;}
function clearRecording() {
  recordSession++;
  clearTimeout(recordTimer);
  if(recorder?.state==='recording') recorder.stop();
  recordStream?.getTracks().forEach(track=>track.stop());recordStream=null;
  if(recordURL) URL.revokeObjectURL(recordURL);
  recordURL='';recording='';recordState='idle';
  $('recordPreview').hidden=true;$('recordPreview').removeAttribute('src');$('removeRecording').hidden=true;
  $('record').textContent='● Record pronunciation';$('record').disabled=false;
  $('recordStatus').textContent='Optional · up to 60 seconds';$('saveManual').disabled=false;
}
function openManual() {
  if($('manualForm').hidden) {
    $('manualForm').hidden=false;
    if(!$('explorer').hidden && words[queue[position]]) $('manualWord').value=words[queue[position]].text;
  }
  $('manualWord').focus();
}
$('addManual').onclick=openManual;
$('cancelManual').onclick=()=>{clearRecording();$('manualForm').hidden=true;manualError('');};
$('removeRecording').onclick=clearRecording;
async function wavRecording(blob) {
  const context=new AudioContext();
  try {
    const decoded=await context.decodeAudioData(await blob.arrayBuffer());
    const frames=Math.min(Math.floor(decoded.duration*16000),60*16000);
    const offline=new OfflineAudioContext(1,Math.max(1,frames),16000);
    const source=offline.createBufferSource();source.buffer=decoded;source.connect(offline.destination);source.start();
    const samples=(await offline.startRendering()).getChannelData(0);
    const buffer=new ArrayBuffer(44+samples.length*2),view=new DataView(buffer);
    function str(offset,text){for(let i=0;i<text.length;i++)view.setUint8(offset+i,text.charCodeAt(i));}
    str(0,'RIFF');view.setUint32(4,36+samples.length*2,true);str(8,'WAVE');str(12,'fmt ');
    view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,16000,true);view.setUint32(28,32000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);str(36,'data');view.setUint32(40,samples.length*2,true);
    samples.forEach((sample,i)=>view.setInt16(44+i*2,Math.max(-1,Math.min(1,sample))*(sample<0 ? 32768 : 32767),true));
    return new Blob([buffer],{type:'audio/wav'});
  } finally {await context.close();}
}
$('record').onclick=async()=>{
  manualError('');
  if(recordState==='recording') {recorder.stop();return;}
  if(!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {manualError('Audio recording needs a browser with microphone support on localhost or HTTPS.');return;}
  clearRecording();
  const session=recordSession;
  recordState='requesting';$('record').disabled=true;$('saveManual').disabled=true;
  try {
    const stream=await navigator.mediaDevices.getUserMedia({audio:true});
    if(session!==recordSession) {stream.getTracks().forEach(track=>track.stop());return;}
    recordStream=stream;
    const chunks=[];recorder=new MediaRecorder(stream);
    recorder.ondataavailable=event=>{if(event.data.size)chunks.push(event.data);};
    recorder.onerror=()=>{clearRecording();manualError('Recording failed. Check your microphone and try again.');};
    recorder.onstop=async()=>{
      clearTimeout(recordTimer);stream.getTracks().forEach(track=>track.stop());
      if(session!==recordSession)return;
      recordState='processing';$('record').disabled=true;$('recordStatus').textContent='Preparing audio…';
      try {
        const wav=await wavRecording(new Blob(chunks,{type:recorder.mimeType}));
        const base64=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(wav);});
        if(session!==recordSession)return;
        recording=base64;recordURL=URL.createObjectURL(wav);$('recordPreview').src=recordURL;$('recordPreview').hidden=false;
        $('removeRecording').hidden=false;$('recordStatus').textContent='Recording ready · saved with each definition';
      } catch(error) {if(session===recordSession)manualError('Could not prepare the recording. Please record again.');}
      finally {if(session===recordSession){recordState='idle';$('record').disabled=false;$('record').textContent='● Record again';$('saveManual').disabled=false;}}
    };
    recorder.start();recordState='recording';$('record').disabled=false;$('record').textContent='■ Stop recording';$('recordStatus').textContent='Recording… stops automatically after 60 seconds';
    recordTimer=setTimeout(()=>{if(recorder.state==='recording')recorder.stop();},60000);
  } catch(error) {if(session===recordSession){clearRecording();manualError('Microphone unavailable. Allow microphone access in your browser, then try again.');}}
};
$('manualForm').onsubmit=async event=>{
  event.preventDefault();manualError('');
  if(recordState!=='idle' || reviewBusy)return;
  $('saveManual').disabled=true;
  try {
    const data={word:$('manualWord').value,meanings:$('manualMeanings').value.split('\n').map(s=>s.trim()).filter(Boolean),
      pos:$('manualPos').value,number:$('manualNumber').value,genders:['manualMasculine','manualFeminine'].filter(id=>$(id).checked).map(id=>$(id).value),
      vowelled:$('manualVowelled').value,pronunciation:$('manualPronunciation').value,root:$('manualRoot').value,notes:$('manualNotes').value,recording};
    const result=await api('manual',data);
    if(publicSite) {
      const updated=new Map(basket);
      for(const entry of result.entries)updated.set(entry.id,entry);
      await IvritStorage.set('basket',[...updated.values()]);
    }
    for(const entry of result.entries)basket.set(entry.id,entry);
    renderBasket();notice(`Added ${result.entries.length} manual meaning${result.entries.length===1?'':'s'} to your vocabulary.`);
    $('manualForm').reset();clearRecording();$('manualForm').hidden=true;
  } catch(error) {manualError(error.message);}
  finally {$('saveManual').disabled=false;}
};
renderBasket();
if(!publicSite && !localStorage.getItem('ivrit-deck')) $('settings').hidden=false;
async function initializeBrowserState() {
  const [entries,skips,draft]=await Promise.all([IvritStorage.get('basket',[]),IvritStorage.get('skips',[]),IvritStorage.get('draft','')]);
  for(const e of entries)if(e?.canonical && /^(\d+|manual-[a-f0-9]{32})$/.test(e.id))basket.set(e.id,e);
  skipped=new Set(skips);if(!$('input').value)$('input').value=draft;
  browserLoaded=true;renderBasket();renderSkips();
  document.body.dataset.storageReady='true';
}
const browserReady=publicSite ? initializeBrowserState() : Promise.resolve();
browserReady.catch(error=>notice(error.message));
if(publicSite) {
  const saveDraft=()=>{if(browserLoaded)IvritStorage.set('draft',$('input').value).catch(error=>notice(error.message));};
  $('input').addEventListener('input',saveDraft);
  $('example').addEventListener('click',saveDraft);
}
