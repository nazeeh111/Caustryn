// Actual production parser and asynchronous revision boundary. MIT.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(process.argv[2]||'studio/sweep.js','utf8');
const reader=source.slice(source.indexOf('function readDraft()'),source.indexOf('async function api('));
const fields={'training-editor':{value:''},'validation-editor':{value:''}};
const context=vm.createContext({$:id=>fields[id],TextEncoder,JSON,Set,Error});vm.runInContext(reader,context);
const good='{"x":[1,"text [ ]",{"escaped\\u006bey":3}],"y":true}';
fields['training-editor'].value=good;assert.equal(JSON.stringify(context.readDraft().training),JSON.stringify(JSON.parse(good)));
for(const bad of ['{"x":1,"x":2}','{"x":1,"\\u0078":2}','{"x":[{"a":1,"a":2}]}','[1,]','{"a":NaN}','"unterminated','[', '['.repeat(33)+'0'+']'.repeat(33)]){
 fields['training-editor'].value=bad;assert.throws(()=>context.readDraft());
}
fields['training-editor'].value=good;fields['validation-editor'].value='{"a":1,"a":2}';assert.throws(()=>context.readDraft());
fields['validation-editor'].value='';fields['training-editor'].value=' '.repeat(1900001);assert.throws(()=>context.readDraft());
const jobSource=source.slice(source.indexOf('async function job('),source.indexOf('function setCurrent('));
let resolver,completions=0;const state={revision:1,busy:false};const notices=[];
const jobContext=vm.createContext({state,AbortController,controls:()=>{},status:(...x)=>notices.push(x),$:()=>({textContent:''}),api:()=>new Promise(r=>resolver=r)});vm.runInContext(jobSource,jobContext);
const late=jobContext.job('sweep-solve',{},()=>completions++);assert.equal(state.busy,true);await jobContext.job('sweep-validate',{},()=>completions++);assert.equal(completions,0);state.revision++;state.busy=false;resolver({status:'late'});await late;assert.equal(completions,0);assert.equal(state.busy,false);
const current=jobContext.job('sweep-solve',{},()=>completions++);resolver({status:'current'});await current;assert.equal(completions,1);assert.equal(state.busy,false);assert.equal(state.controller,null);
console.log('Sweep controls passed: duplicate keys, malformed/deep/oversized packets, stale asynchronous result exclusion and current completion.');
