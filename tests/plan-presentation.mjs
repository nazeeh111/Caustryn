// Exercise the production plan presentation without making network calls. MIT.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(process.argv[2]||'studio/sweep.js','utf8');
const start=source.indexOf('function renderPlan('),end=source.indexOf('\nfunction save(',start);
assert.ok(start>=0 && end>start,'production plan presentation exists');
class Node {
  constructor(tag){this.tag=tag;this.children=[];this.textContent='';this.className='';}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=[...nodes];this.textContent='';}
}
const panel=new Node('div');
const context=vm.createContext({$:()=>panel,document:{createElement:tag=>new Node(tag)},JSON,Number});
vm.runInContext(source.slice(start,end),context);
const data={status:'recommended',recommended_pose_m:[[0,1,2]],units:'squared IQ',warning:'Conditional; no uniqueness or hardware guarantee.',training_sha256:'training',fit_sha256:'fit',ranked_poses:[{rx_pose_m:[[0,1,2]],worst_pair_score:12,numerically_distinguishable:true},{rx_pose_m:[[0,0,2]],worst_pair_score:0,numerically_distinguishable:false}]};
context.renderPlan(data);
function text(node){return [node.textContent,...node.children.map(text)].join(' ');}
let display=text(panel);
assert.match(display,/recommended/i);assert.match(display,/numerically distinguishable/i);assert.match(display,/numerically indistinguishable/i);assert.match(display,/\[0,1,2\]/);assert.match(display,/squared IQ/);assert.match(display,/no uniqueness or hardware guarantee/i);assert.match(display,/training/);
context.renderPlan({...data,status:'no-mode-separation',recommended_pose_m:null,ranked_poses:[data.ranked_poses[1]]});display=text(panel);assert.match(display,/no .*separation/i);assert.doesNotMatch(display,/recommended pose/i);
context.renderPlan({...data,status:'refused-one-found-mode-conditional-coherence',recommended_pose_m:null,ranked_poses:[]});display=text(panel);assert.match(display,/two or more found modes are needed/i);assert.match(display,/does not prove global uniqueness/i);assert.match(display,/refused-one-found-mode-conditional-coherence/);
context.renderPlan({...data,status:'refused-weak-or-rank-deficient-mode',recommended_pose_m:null,ranked_poses:[]});display=text(panel);assert.match(display,/refused/i);assert.match(display,/weak-or-rank-deficient-mode/i);
console.log('Plan presentation preserves status, ranks, coordinates, units, roundoff flags and conditional caveat.');
