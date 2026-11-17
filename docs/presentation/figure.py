"""Exact XY geometry and all channel-0 held complex samples; no interpolated data."""
from pathlib import Path
import json,math,html
P=Path(__file__).parent
load=lambda n:json.loads((P/n).read_text())
t=load('mirror.training.json');h=load('mirror.validation.json');r=load('mirror.result.json');plan=load('plan.json');control=load('exact-counterfeit.result.json');truth=load('exact-counterfeit.truth.json');modes=r['fit']['candidates'];pred=r['validation']['candidates'];assert len(modes)==2 and all(x['compatible']for x in pred)
assert pred[0]['predicted_iq']==pred[1]['predicted_iq']
error=math.dist(control['fit']['candidates'][0]['position_m'],truth['position_m']);data={'training':t,'held':h,'modes':modes,'predictions':pred,'plan':plan,'counterfeitDistanceM':error,'counterfeitHeldReducedResidual':control['validation']['candidates'][0]['reduced_residual']};(P/'figure-data.json').write_text(json.dumps(data,indent=2)+'\n')
def make(mobile):
 W,H=(420,1190)if mobile else(1160,760);o=[];add=o.append
 def text(x,y,s,size=15,c='#e4ece8',weight=400):add(f'<text x="{x}" y="{y}" font-size="{size}" fill="{c}" font-weight="{weight}">{html.escape(str(s))}</text>')
 def line(x,y,X,Y,c='#41555f',w=1,dash=''):add(f'<line x1="{x:.8f}" y1="{y:.8f}" x2="{X:.8f}" y2="{Y:.8f}" stroke="{c}" stroke-width="{w}"'+(f' stroke-dasharray="{dash}"'if dash else'')+'/>')
 desc='A coplanar simulated receiver sweep retains two reflected locations. Both training-fitted complex responses predict the separate held positions, with no location or gain refit and no mode selected from held data. All 32 real and 32 imaginary held samples of channel zero are plotted, with a gap between configurations. An independently supplied out-of-plane receiver configuration is only a conditional proposal. A separate changing-response counterfeit passes held prediction while approximately 3.49 metres from its generator truth.'
 add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc"><title id="title">A prediction can pass without one answer</title><desc id="desc">{desc}</desc><style>text{{font-family:Arial,"DejaVu Sans",sans-serif}}</style><rect width="100%" height="100%" fill="#101b23"/>')
 text(28,35,'PhaseGlass RF / simulated evidence',13,'#9dc4cb');text(28,78,'Predict there.',30,'#eff6e9',600);text(28,116,'Keep both answers.',30,'#eff6e9',600)
 gx,gy,sz=(48,177,324)if mobile else(50,185,370);X=lambda x:gx+(x+.3)/6.6*sz;Y=lambda y:gy+sz-(y+3.3)/6.6*sz
 text(gx,gy-18,'Known geometry and found modes',15,'#eff6e9',600)
 for x in[0,3,6]:line(X(x),gy,X(x),gy+sz);text(X(x)-4,gy+sz+22,str(x),12,'#a8bbc5')
 for y in[-3,0,3]:line(gx,Y(y),gx+sz,Y(y));text(gx-24,Y(y)+4,str(y),12,'#a8bbc5')
 text(gx+sz-40,gy+sz+42,'x (m)',12,'#a8bbc5');text(gx-20,gy-2,'y (m)',12,'#a8bbc5')
 for i,p in enumerate(t['tx_m']):x,y=X(p[0]),Y(p[1]);add(f'<path data-tx="{i}" d="M{x-5:.8f},{y+4:.8f}L{x+5:.8f},{y+4:.8f}L{x:.8f},{y-5:.8f}Z" fill="#f5ad75"/>')
 for kind,poses in [('training',t['rx_poses_m']),('held',h['rx_poses_m'])]:
  for k,pose in enumerate(poses):
   for i,p in enumerate(pose):x,y=X(p[0]),Y(p[1]);add(f'<circle data-receiver="{kind}-{k}-{i}" cx="{x:.8f}" cy="{y:.8f}" r="{3 if kind=="training"else 2}" fill="{chr(35)+("73d4df"if kind=="training"else"eff6e9")}"/>')
 for i,m in enumerate(modes):
  x,y=X(m['position_m'][0]),Y(m['position_m'][1]);add(f'<circle data-mode="{i}" cx="{x:.8f}" cy="{y:.8f}" r="7" fill="#d6f87b"/>');text(x+12,y+5,f'Mode {i+1}',13,'#d6f87b',600)
 proposed=plan['recommended_pose_m'][2];x,y=X(proposed[0]),Y(proposed[1]);add(f'<path data-proposed="true" d="M{x:.8f},{y-6:.8f}L{x+6:.8f},{y:.8f}L{x:.8f},{y+6:.8f}L{x-6:.8f},{y:.8f}Z" fill="none" stroke="#73d4df" stroke-width="2"/>');line(x,Y(0),x,y,'#73d4df',1,'3 3')
 text(gx,gy+sz+65,'XY view; antenna heights omitted.',12,'#a8bbc5');text(gx,gy+sz+85,'5 fit + 2 held poses stay in y = 0.',12,'#a8bbc5');text(gx,gy+sz+103,'TX triangles; RX dots; green found modes.',12,'#a8bbc5')
 px,py,pw,ph=(48,690,324,115)if mobile else(505,212,610,130)
 vals=[v for comp in['real','imag']for pose in range(2)for v in h['iq'][comp][pose][0]];vmin=min(vals);vmax=max(vals);pad=(vmax-vmin)*.12;vmin-=pad;vmax+=pad
 text(px,py-28,'Unseen positions / channel 0',15,'#eff6e9',600)
 for ci,comp in enumerate(['real','imag']):
  yy=py+ci*(ph+65);sy=lambda v:yy+ph-(v-vmin)/(vmax-vmin)*ph;line(px,sy(0),px+pw,sy(0));text(px,yy-8,comp.capitalize()+' IQ',12,'#a8bbc5');text(px-36,yy+8,f'{vmax:.3f}',11,'#a8bbc5');text(px-36,yy+ph,f'{vmin:.3f}',11,'#a8bbc5')
  for pose in range(2):
   for label,values,c in [('observed',h['iq'][comp][pose][0],'#eff6e9'),('predicted',pred[0]['predicted_iq'][comp][pose][0],'#73d4df')]:
    points=[(px+(pose*17+i)/32*pw,sy(v))for i,v in enumerate(values)];add(f'<polyline data-series="{comp}-{pose}-{label}" points="'+ ' '.join(f'{x:.8f},{y:.8f}'for x,y in points)+f'" fill="none" stroke="{c}" stroke-width="{1 if label=="observed"else 2}"'+(' stroke-dasharray="4 3"'if label=='predicted'else'')+'/>')
   text(px+pose*17/32*pw,yy+ph+18,f'Pose {pose+1}: 16 frequencies',11,'#a8bbc5')
 end=py+2*(ph+65)-8;text(px,end,'Solid: supplied IQ. Dashed: frozen fit.',12,'#a8bbc5');text(px,end+23,'Both modes predict the same held signal.',12,'#d6f87b')
 by=1090 if mobile else 680
 text(28,by,'Passing is conditional, not physical validation.',16,'#f5ad75',600)
 text(28,by+26,f'Separate counterfeit: held residual {control["validation"]["candidates"][0]["reduced_residual"]:.3f}; wrong by {error:.3f} m.',12,'#e4ece8')
 text(28,by+50,'Out-of-plane diamond: proposed geometry, not a new measurement.',11,'#a8bbc5');text(28,H-18,'Original simulations. No radio, hardware accuracy or uniqueness claim.',11,'#a8bbc5');add('</svg>');(P/('sweep-mobile.svg'if mobile else'sweep.svg')).write_text(''.join(o))
make(False);make(True)
