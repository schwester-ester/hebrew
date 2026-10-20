const $ = id => document.getElementById(id);
let words = [], selected = new Set(), queue = [], position = -1, basket = new Map(), lookupVersion = 0;
let resultsByWord = new Map(), knownIds = new Set(), skipped = new Set();
let syncedDeck = '', reviewBusy = false;
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const he = value => `<bdi lang="he" dir="rtl">${escapeHTML(value)}</bdi>`;
function notice(message) { $('notice').textContent = message; $('notice').hidden = !message; }
async function api(path, data) {
  const response = await fetch('/api/' + path, data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Request failed. Please retry.');
  return result;
}
function deck() { return $('deck').value; }
function snapshot() { localStorage.setItem('ivrit-basket', JSON.stringify([...basket.values()])); }
function renderBasket() {
  snapshot();
  $('basketCount').textContent = `${basket.size} meaning${basket.size === 1 ? '' : 's'}`;
  $('export').disabled = !basket.size || reviewBusy;
  $('import').disabled = !basket.size || !syncedDeck || deck() !== syncedDeck || reviewBusy;
  $('basket').innerHTML = basket.size ? [...basket.values()].map(e => `<div class="basket-item"><span class="lemma">${he(e.canonical.plain)}</span><span class="small">${escapeHTML(e.meaning)}</span><button class="quiet" data-remove="${e.id}">Remove</button></div>`).join('') : '<p class="small">Choose meanings as you read. Your selected words will appear here.</p>';
}
try { for (const e of JSON.parse(localStorage.getItem('ivrit-basket') || '[]')) if(e?.canonical && /^\d+$/.test(e.id)) basket.set(e.id,e); } catch {}
function renderPassage() {
  const text = $('input').value;
  let html = '', end = 0;
  words.forEach((w,i) => {
    html += escapeHTML(text.slice(end,w.start));
    html += `<button class="token ${w.known ? 'known' : ''} ${selected.has(i) ? 'selected' : ''} ${queue[position] === i ? 'active' : ''}" data-index="${i}" aria-pressed="${selected.has(i)}" title="${escapeHTML(w.reason || 'Click to explore; Ctrl / ⌘ click to select')}">${escapeHTML(w.text)}</button>`;
    end = w.end;
  });
  html += escapeHTML(text.slice(end));
  $('passage').innerHTML = html;
  $('textCount').textContent = `${words.length} words · ${words.filter(w => w.known).length} known or skipped`;
  $('selectedCount').textContent = selected.size;
  $('selected').disabled = !selected.size;
}
async function startReading() {
  notice('');
  const data = await api('text', {text:$('input').value,deck:deck()});
  words = data.tokens;
  if(!words.length) throw new Error('Paste a text containing Hebrew words first.');
  skipped = new Set(data.skipped); renderSkips();
  selected.clear(); queue=[]; position=-1; lookupVersion++;
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
  $('connect').disabled=true; $('connection').textContent='Connecting…';
  try {
    const {decks} = await api('decks');
    const preferred = deck() || localStorage.getItem('ivrit-deck');
    $('deck').innerHTML = decks.map(d => `<option value="${escapeHTML(d)}">${escapeHTML(d)}</option>`).join('');
    if(decks.includes(preferred)) $('deck').value=preferred;
    if(!decks.length) throw new Error('Create a deck in Anki first.');
    await sync();
  } catch(error) {syncedDeck=''; $('connection').textContent=error.message;renderBasket();}
  finally {$('connect').disabled=false;}
}
async function sync() {
  const selectedDeck=deck();
  syncedDeck='';renderBasket();
  const result = await api('sync',{deck:selectedDeck,field:$('knownField').value});
  if(deck() !== selectedDeck) return;
  syncedDeck=selectedDeck; knownIds=new Set(result.entries); resultsByWord.clear();
  localStorage.setItem('ivrit-deck',selectedDeck);
  $('connection').textContent=`Connected · ${result.words.length + result.entries.length} known words / meanings`;
  const knownWords = new Set(result.words);
  for(const [id, entry] of basket) if(knownIds.has(id) || knownWords.has(entry.canonical.plain)) basket.delete(id);
  renderBasket();
  if(words.length) await startReading();
}
function handle(fn) {return async (...args) => {try {await fn(...args);} catch(error) {notice(error.message);}};}
$('settingsToggle').onclick=()=>{$('settings').hidden=!$('settings').hidden;};
$('connect').onclick=handle(connect);
$('deck').onchange=handle(sync);
$('read').onclick=handle(startReading);
$('example').onclick=()=>{$('input').value='קראתי ספר טוב בבית. הילדים משחקים בגינה, ועל השולחנות יש ספרים חדשים.';$('editor').hidden=false;$('reading').hidden=true;};
$('edit').onclick=()=>{lookupVersion++; $('editor').hidden=false;$('reading').hidden=true;$('explorer').hidden=true;$('empty').hidden=false;};
$('passage').onclick=event=>{
  const token=event.target.closest('[data-index]');if(!token) return;
  const i=Number(token.dataset.index);
  if(event.ctrlKey || event.metaKey){selected.has(i) ? selected.delete(i) : selected.add(i);renderPassage();}
  else {queue=words.map((_,index)=>index).filter(index=>index===i || !words[index].known);position=queue.indexOf(i);showWord();}
};
$('all').onclick=()=>beginQueue(words.map((_,i)=>i));
$('selected').onclick=()=>beginQueue([...selected].sort((a,b)=>a-b));
$('clear').onclick=()=>{selected.clear();renderPassage();};
$('previous').onclick=()=>go(-1);$('next').onclick=()=>go(1);$('retry').onclick=()=>showWord(true);
document.addEventListener('keydown',event=>{
  if(event.target.matches('input,textarea,select') || event.ctrlKey || event.metaKey || event.altKey || position<0 || $('explorer').hidden) return;
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
$('basket').onclick=event=>{const button=event.target.closest('[data-remove]');if(button){basket.delete(button.dataset.remove);renderBasket();if(position>=0)showWord();}};
$('import').onclick=handle(async()=>{
  reviewBusy=true;renderBasket();$('import').textContent='Importing…';$('deck').disabled=true;$('connect').disabled=true;
  try {
    const result=await api('import',{deck:deck(),ids:[...basket.keys()]});
    for(const id of [...result.imported,...result.duplicates]){basket.delete(id);knownIds.add(id);}
    resultsByWord.clear();
    notice(`Imported ${result.imported.length} meanings. ${result.duplicates.length} already in deck.${result.failed.length ? '\nNot imported: ' + result.failed.map(f=>f.error).join('; ') : ''}`);
    if(position>=0)showWord();
  } finally {reviewBusy=false;$('import').textContent='Import to Anki ↗';$('deck').disabled=false;$('connect').disabled=false;renderBasket();}
});
$('export').onclick=handle(async()=>{
  const response=await fetch('/api/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ids:[...basket.keys()]})});
  if(!response.ok)throw new Error((await response.json()).error);
  const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download='hebrew-vocabulary.tsv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  notice('TSV downloaded. In Anki, import it as Basic, map Front and Back, and allow HTML. Choose “import as new notes” to retain meanings sharing a spelling. Sync your deck after importing.');
});
renderBasket();
if(!localStorage.getItem('ivrit-deck')) $('settings').hidden=false;
