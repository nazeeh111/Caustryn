// Exercise the actual plot function with a small, synthetic two-position packet. MIT.
import assert from 'node:assert/strict';import fs from 'node:fs';import vm from 'node:vm';
const source=fs.readFileSync(process.argv[2]||'studio/sweep.js','utf8');const start=source.indexOf('function drawPrediction()'),endMarker=source.includes('\nfunction renderPlan(')?'\nfunction renderPlan(':'\nfunction save(';const end=source.indexOf(endMarker,start);assert.ok(start>=0&&end>start);
function context(){const moves=[],lines=[],labels=[];return {moves,lines,labels,setTransform(){},clearRect(){},beginPath(){},stroke(){},setLineDash(){},moveTo(x,y){moves.push([x,y]);},lineTo(x,y){lines.push([x,y]);},fillText(text){labels.push(text);}};}
const primary=context(),residual=context();function canvas(ctx){return {getContext:()=>ctx,getBoundingClientRect:()=>({width:500,height:240})};}const nodes={'prediction-plot':canvas(primary),'residual-plot':canvas(residual),'prediction-copy':{textContent:''}};
const iq={real:[[[1,2]],[[3,4]]],imag:[[[0,1]],[[2,3]]]};const state={selected:0,current:{training:{frequencies_hz:[1,2],noise_std_per_component:1},validation:{iq}},held:{candidates:[{predicted_iq:iq,reduced_residual:0,compatible:true}]}};
const ctx=vm.createContext({state,$:id=>nodes[id],devicePixelRatio:1,Math,Number,format:x=>String(x)});vm.runInContext(source.slice(start,end),ctx);ctx.drawPrediction();
// One baseline plus two separate paths per series; no line connects receiver positions.
assert.equal(primary.moves.length,1+4*2);assert.equal(primary.lines.length,1+4*2);
assert.equal(residual.moves.length,1+2*2);assert.equal(residual.lines.length,1+2*2);
assert.ok(primary.labels.includes('4.0')&&primary.labels.includes('-4.0'));
assert.match(nodes['prediction-copy'].textContent,/break between held positions/);
console.log('Held plots preserve position breaks and show the plotted IQ amplitude scale.');
