// Standalone, synthetic display probe using a measured vector distinct from predicted values.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const script=fs.readFileSync(process.argv[2] || 'studio/sweep.js','utf8');
const start=script.indexOf('function drawPrediction()');
const end=script.indexOf('\nfunction renderPlan(',start);
assert.ok(start >= 0 && end>start);
function context(){return {moves:[],lines:[],setTransform(){},clearRect(){},beginPath(){},stroke(){},setLineDash(){},moveTo(x,y){this.moves.push([x,y]);},lineTo(x,y){this.lines.push([x,y]);},fillText(){}};}
const primary=context(),residual=context(), canvas=c=>({getContext:()=>c,getBoundingClientRect:()=>({width:500,height:240}),setAttribute(k,v){this[k]=v;}});
const nodes={'prediction-plot':canvas(primary),'residual-plot':canvas(residual),'prediction-copy':{},'prediction-range':{},'prediction-legend':{},'residual-heading':{},'residual-range':{}};
function iq(real){return {real:[[real.slice(0,2)],[real.slice(2)]],imag:[[[0,0]],[[0,0]]]};}
const state={selected:0,current:{training:{frequencies_hz:[1,2],noise_std_per_component:0.5},validation:{iq:iq([1,2,3,4])}},held:{candidates:[{predicted_iq:iq([5,6,7,8]),reduced_residual:7,compatible:false}]}};
const ctx=vm.createContext({state,$:k=>nodes[k],devicePixelRatio:1,Math,Number,format:String});
vm.runInContext(script.slice(start,end),ctx);
for(const [sigma,expect] of [[0.5,8],[0,4/Math.sqrt(7.5)]]){
  state.current.training.noise_std_per_component=sigma;
  const n=residual.moves.length;ctx.drawPrediction();
  assert.equal(nodes['residual-range'].textContent,'Range ±'+expect.toPrecision(3)+' · cyan real / orange imaginary');
  assert.equal(nodes['residual-range'].hidden,false);
  assert.equal(residual.moves.length-n,5);
  console.log('sigma',sigma,'expected',expect,'actual',nodes['residual-range'].textContent);
}
state.current.validation.iq=iq([0,0,0,0]);const n=residual.moves.length;ctx.drawPrediction();
assert.equal(residual.moves.length,n);assert.equal(nodes['residual-range'].hidden,true);assert.match(nodes['residual-plot']['aria-label'],/undefined/);
console.log('zero-noise zero-amplitude undefined; no additional plotted residual');
