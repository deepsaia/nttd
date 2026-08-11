"""The stylesheet and the script layer, inlined into every page.

Inlined rather than served as files because there is then nothing to cache wrongly, no
second request to get out of step with the HTML, and no subresource to pin. The whole
dashboard is one response.

Dark is the default and light follows the system unless the reader picks one. Both are
defined with the same variables so a panel added later gets both themes for free.
"""

from __future__ import annotations

CSS = """
:root{--bg:#0f1420;--panel:#171d2b;--panel2:#1e2637;--ink:#e6ebf5;--muted:#8b97ad;
 --accent:#4f8cff;--line:#2a3346;--good:#35d0a5;--warn:#ffd166;--bad:#ef476f;--grid:#2a3346;}
@media (prefers-color-scheme:light){
 :root:not([data-theme="dark"]){--bg:#f6f8fc;--panel:#ffffff;--panel2:#eef2f8;
  --ink:#1a2233;--muted:#5c6b85;--accent:#2f6bdf;--line:#dbe2ee;--good:#0f9d78;
  --warn:#b7791f;--bad:#d1435b;--grid:#e6ebf3;}
}
:root[data-theme="light"]{--bg:#f6f8fc;--panel:#ffffff;--panel2:#eef2f8;--ink:#1a2233;
 --muted:#5c6b85;--accent:#2f6bdf;--line:#dbe2ee;--good:#0f9d78;--warn:#b7791f;
 --bad:#d1435b;--grid:#e6ebf3;}
:root[data-theme="dark"]{--bg:#0f1420;--panel:#171d2b;--panel2:#1e2637;--ink:#e6ebf5;
 --muted:#8b97ad;--accent:#4f8cff;--line:#2a3346;--good:#35d0a5;--warn:#ffd166;
 --bad:#ef476f;--grid:#2a3346;}
*{box-sizing:border-box;}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
 background:var(--bg);color:var(--ink);font-size:13px;}
.app{display:flex;height:100vh;overflow:hidden;}
.sidebar{width:260px;flex:0 0 260px;background:var(--panel);border-right:1px solid var(--line);
 padding:14px 12px;overflow-y:auto;}
.sbhead{display:flex;align-items:center;justify-content:space-between;}
.sidebar h1{font-size:15px;margin:0;}
.navlabel{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.6px;
 margin:12px 2px 6px;}
.nav{display:flex;align-items:center;gap:8px;padding:8px 9px;text-decoration:none;
 color:var(--ink);border:1px solid transparent;border-radius:9px;margin-bottom:5px;
 background:var(--panel2);}
.nav:hover{border-color:var(--line);}
.nav.on{border-color:var(--accent);}
.nav .meta{min-width:0;flex:1 1 auto;}
.nav .name{font-size:12.5px;font-weight:600;white-space:nowrap;overflow:hidden;
 text-overflow:ellipsis;}
.nav .stat{font-size:10.5px;color:var(--muted);display:block;}
.nav .ndot{width:9px;height:9px;border-radius:50%;flex:0 0 auto;background:var(--muted);}
.nav .ndot.all{background:var(--accent);}
.nav .nname{flex:1 1 auto;font-size:12.5px;font-weight:600;}
.nav .ncount{font-size:11px;color:var(--muted);}
.main{flex:1 1 auto;padding:14px 18px;overflow-y:auto;}
.tabs{display:flex;align-items:center;gap:12px;margin-bottom:12px;}
.tab{font-size:14px;font-weight:600;color:var(--muted);text-decoration:none;padding:4px 0;}
.tab.on{color:var(--ink);border-bottom:2px solid var(--accent);}
.hint{color:var(--muted);font-size:11px;margin-left:auto;}
.cards{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px;}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
 padding:9px 14px;min-width:112px;}
.card .k{font-size:10.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px;}
.card .v{font-size:19px;font-weight:700;margin-top:2px;}
.card .v.good{color:var(--good);}
.card .v.bad{color:var(--bad);}
.card .v.warn{color:var(--warn);}
.metastrip{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px;}
.chip{background:var(--panel2);border:1px solid var(--line);border-radius:20px;
 padding:3px 11px;font-size:11px;color:var(--muted);}
/* align-items:start so a short panel keeps its own height. Without it every panel in a
   row stretches to the tallest, and the health panel next to the map became a mostly
   empty box the height of the whole world view. */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:12px;
 align-items:start;}
.plot{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:9px 11px;}
.plot.two{grid-column:span 2;}
.plot.full{grid-column:1/-1;}
.ptitle{font-size:12px;font-weight:600;margin-bottom:4px;display:flex;
 justify-content:space-between;}
.readout{color:var(--accent);font-weight:600;font-size:11px;}
.chart{width:100%;height:150px;display:block;}
.chart .gl{stroke:var(--grid);}
.chart .axl{fill:var(--muted);}
.chart .xhair{stroke:var(--ink);}
.legend{display:flex;flex-wrap:wrap;gap:9px;margin-top:5px;}
.lg{font-size:10.5px;color:var(--muted);display:flex;align-items:center;gap:4px;
 cursor:pointer;user-select:none;}
.lg.off{opacity:.35;text-decoration:line-through;}
.sw{width:9px;height:9px;border-radius:2px;display:inline-block;}
.sw.round{border-radius:50%;}
.sw.good{background:var(--good);}
.sw.bad{background:var(--bad);}
.mix{display:flex;flex-direction:column;gap:6px;padding:2px 0;}
.mixrow{display:flex;align-items:center;gap:9px;}
.mixlab{flex:0 0 130px;font-size:11px;white-space:nowrap;overflow:hidden;
 text-overflow:ellipsis;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;}
.mixbar{display:flex;height:14px;border-radius:4px;overflow:hidden;background:var(--panel2);
 border:1px solid var(--line);min-width:8px;}
.mixbar .seg.good{background:var(--good);}
.mixbar .seg.bad{background:var(--bad);}
.mixtot{flex:0 0 auto;font-size:11px;color:var(--muted);min-width:44px;text-align:right;}
/* health: one row per rule that tripped, coloured by how bad it is */
.health{display:flex;flex-direction:column;gap:8px;}
.hrow{display:flex;gap:9px;align-items:flex-start;padding:7px 9px;border-radius:8px;
 background:var(--panel2);border-left:3px solid var(--muted);}
.hrow.bad{border-left-color:var(--bad);}
.hrow.warn{border-left-color:var(--warn);}
.hrow .hbody{min-width:0;}
.hrule{font-weight:700;font-size:11.5px;text-transform:uppercase;letter-spacing:.4px;}
.hrow.bad .hrule{color:var(--bad);}
.hrow.warn .hrule{color:var(--warn);}
.hdetail{font-size:12px;margin-top:1px;}
.hwhy{font-size:11px;color:var(--muted);margin-top:2px;}
/* the top down map */
.wmap{width:100%;height:auto;max-height:60vh;display:block;border-radius:8px;}
.wmap .wbg{fill:var(--panel2);}
.wscrub{display:flex;align-items:center;gap:10px;margin-top:6px;}
.wslider{flex:1 1 auto;accent-color:var(--accent);cursor:pointer;}
.wstep{font-size:11px;color:var(--muted);white-space:nowrap;min-width:64px;text-align:right;}
.wlivebtn{display:inline-flex;align-items:center;gap:5px;font-size:10.5px;font-weight:700;
 letter-spacing:.4px;background:var(--panel2);color:var(--muted);border:1px solid var(--line);
 border-radius:8px;padding:3px 8px;cursor:pointer;white-space:nowrap;}
.wlivebtn:hover{border-color:var(--accent);}
.wlivebtn.on{color:var(--good);border-color:var(--good);}
.wlivebtn .livedot{width:7px;height:7px;margin:0;}
.wlivebtn:not(.on) .livedot{background:var(--muted);animation:none;box-shadow:none;}
.wdata{display:none;}
/* tables for the action log and the event timeline */
.tscroll{max-height:280px;overflow-y:auto;}
.tbl{width:100%;border-collapse:collapse;font-size:11.5px;}
.tbl th{text-align:left;color:var(--muted);font-weight:600;font-size:10.5px;
 text-transform:uppercase;letter-spacing:.4px;padding:4px 6px;position:sticky;top:0;
 background:var(--panel);}
.tbl td{padding:4px 6px;border-top:1px solid var(--line);
 font-family:ui-monospace,SFMono-Regular,Menlo,monospace;}
.tbl tr:hover td{background:var(--panel2);}
.themebtn{background:var(--panel2);color:var(--ink);border:1px solid var(--line);
 border-radius:8px;padding:5px 7px;cursor:pointer;display:inline-flex;align-items:center;
 line-height:0;}
.themebtn:hover{border-color:var(--accent);color:var(--accent);}
.themebtn .ticon{display:none;}
:root:not([data-theme]) .themebtn .ti-system{display:inline;}
:root[data-theme="light"] .themebtn .ti-light{display:inline;}
:root[data-theme="dark"] .themebtn .ti-dark{display:inline;}
.ph{color:var(--muted);padding:22px;text-align:center;}
.ph.big{padding:60px;font-size:15px;}
.livedot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--good);
 margin-right:5px;animation:pulse 1.6s infinite;}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(53,208,165,.5);}
 70%{box-shadow:0 0 0 6px rgba(53,208,165,0);}100%{box-shadow:0 0 0 0 rgba(53,208,165,0);}}
.err{color:var(--bad);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;}
code{background:var(--panel2);padding:2px 6px;border-radius:5px;}
"""

# One icon per theme mode, drawn inline. The stylesheet shows exactly one.
THEME_ICONS = (
    '<svg class="ticon ti-system" viewBox="0 0 24 24" width="16" height="16" fill="none" '
    'stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/>'
    '<path d="M12 3v18"/><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor" stroke="none"/></svg>'
    '<svg class="ticon ti-light" viewBox="0 0 24 24" width="16" height="16" fill="none" '
    'stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4.5"/>'
    '<path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4'
    'M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4"/></svg>'
    '<svg class="ticon ti-dark" viewBox="0 0 24 24" width="16" height="16" '
    'fill="currentColor" stroke="none">'
    '<path d="M21 12.8A8.5 8.5 0 1 1 11.2 3a7 7 0 1 0 9.8 9.8z"/></svg>'
)

# Applied before first paint so there is no flash of the wrong theme.
THEME_HEAD_JS = r"""
(function(){ try{ var t=localStorage.getItem('nttd-theme');
 if(t==='light'||t==='dark') document.documentElement.setAttribute('data-theme',t);
}catch(e){} })();
"""

THEME_BODY_JS = r"""
(function(){ var b=document.getElementById('themebtn'); if(!b) return;
 function cur(){ return document.documentElement.getAttribute('data-theme')||'system'; }
 b.title='theme: '+cur()+' (click to switch)';
 b.addEventListener('click', function(){ var order=['system','light','dark'];
  var nx=order[(order.indexOf(cur())+1)%3];
  if(nx==='system'){ document.documentElement.removeAttribute('data-theme');
   localStorage.removeItem('nttd-theme'); }
  else { document.documentElement.setAttribute('data-theme',nx);
   localStorage.setItem('nttd-theme',nx); }
  b.title='theme: '+nx+' (click to switch)'; });
})();
"""

# Crosshair readouts, legend toggles and the map scrubber. Everything here decorates a
# picture the server already finished, so the page still reads with scripting off.
JS = r"""
(function(){
  function nearest(data, xv){ var b=data[0], bd=1e18;
    for(var i=0;i<data.length;i++){ var d=Math.abs(data[i][0]-xv); if(d<bd){bd=d;b=data[i];} }
    return b; }
  function fmt(v){ v=+v;
    if(Math.abs(v)>=1e6) return (v/1e6).toFixed(2)+'M';
    if(Math.abs(v)>=1e4) return (v/1e3).toFixed(1)+'k';
    if(Math.abs(v)<1&&v!==0) return v.toFixed(3);
    return Math.round(v).toLocaleString(); }

  document.querySelectorAll('.plot[data-geom]').forEach(function(plot){
    var geom; try{ geom=JSON.parse(plot.getAttribute('data-geom')); }catch(e){ return; }
    var svg=plot.querySelector('svg'); if(!svg) return;
    var xh=svg.querySelector('.xhair'), ro=plot.querySelector('.readout');
    var hit=svg.querySelector('.hit'); if(!hit) return;
    hit.addEventListener('mousemove', function(ev){
      var r=svg.getBoundingClientRect();
      var sx=(ev.clientX-r.left)/r.width*geom.w;
      var frac=(sx-geom.padL)/(geom.w-geom.padL-geom.padR);
      var xv=Math.round(geom.xmin+frac*(geom.xmax-geom.xmin));
      if(xh){ xh.setAttribute('x1',sx); xh.setAttribute('x2',sx); xh.setAttribute('opacity','0.5'); }
      var parts=geom.series.map(function(s){ if(!s.data.length) return '';
        var p=nearest(s.data,xv);
        return '<span style="color:'+s.color+'">'+fmt(p[1])+'</span>'; })
        .filter(function(t){ return t; });
      if(ro) ro.innerHTML='step '+xv+' &middot; '+parts.join(' / ');
    });
    hit.addEventListener('mouseleave', function(){
      if(xh) xh.setAttribute('opacity','0'); if(ro) ro.innerHTML=''; });
  });

  document.querySelectorAll('.lg[data-si]').forEach(function(lg){
    var key='off:'+lg.getAttribute('data-cid')+':'+lg.getAttribute('data-si');
    var plot=lg.closest('.plot');
    var el=plot? plot.querySelector('.s'+lg.getAttribute('data-si')) : null;
    if(sessionStorage.getItem(key)==='1'){ lg.classList.add('off'); if(el) el.style.display='none'; }
    lg.addEventListener('click', function(){ var off=lg.classList.toggle('off');
      if(el) el.style.display=off?'none':'';
      try{ sessionStorage.setItem(key, off?'1':'0'); }catch(e){} });
  });

  // The map scrubber. Dragging freezes the map on that step and the choice survives the
  // page's auto refresh, so inspecting step 3 of a running session is not yanked back to
  // now every few seconds. LIVE re-syncs and resumes following.
  var holder=document.querySelector('.wdata'); if(!holder) return;
  var payload; try{ payload=JSON.parse(holder.getAttribute('data-frames')); }catch(e){ return; }
  var frames=payload.frames||[]; if(!frames.length) return;
  var svg=document.querySelector('.wmap'); if(!svg) return;
  var group=svg.querySelector('.wlive');
  var slider=document.querySelector('.wslider');
  var out=document.querySelector('.wstep');
  var live=document.querySelector('.wlivebtn');
  var last=frames.length-1;
  var NS='http://www.w3.org/2000/svg';
  var stationColours=payload.station_colours||{};
  var vehicleColours=payload.vehicle_colours||{};

  function paint(i){
    i=Math.max(0,Math.min(last,i));
    var f=frames[i];
    while(group.firstChild) group.removeChild(group.firstChild);
    (f.s||[]).forEach(function(s){
      var r=document.createElementNS(NS,'rect');
      r.setAttribute('x',s[0]-1.5); r.setAttribute('y',s[1]-1.5);
      r.setAttribute('width','3.4'); r.setAttribute('height','3.4');
      r.setAttribute('fill', stationColours[s[2]]||stationColours.other||'#8d99ae');
      r.setAttribute('stroke','#0f1420'); r.setAttribute('stroke-width','0.4');
      var t=document.createElementNS(NS,'title');
      t.textContent=s[3]+' ('+s[2]+')'+(s[4]?', '+s[4]+' waiting':'');
      r.appendChild(t); group.appendChild(r);
    });
    (f.v||[]).forEach(function(v){
      var c=document.createElementNS(NS,'circle');
      c.setAttribute('cx',v[0]); c.setAttribute('cy',v[1]); c.setAttribute('r','1.2');
      c.setAttribute('fill', vehicleColours[v[2]]||'#e6ebf5');
      group.appendChild(c);
    });
    if(out) out.textContent='step '+i+(f.d?' ('+f.d+')':'');
    if(slider) slider.value=i;
  }
  function setLive(on){
    if(live){ live.classList.toggle('on',on); live.setAttribute('aria-pressed',on?'true':'false'); }
    try{ sessionStorage.setItem('wlive', on?'1':'0'); }catch(e){}
  }
  var isLive=true;
  try{ isLive=sessionStorage.getItem('wlive')!=='0'; }catch(e){}
  if(isLive){ setLive(true); paint(last); }
  else{
    var saved=last; try{ saved=parseInt(sessionStorage.getItem('wstep'),10); }catch(e){}
    if(isNaN(saved)) saved=last;
    setLive(false); paint(saved);
  }
  if(slider) slider.addEventListener('input', function(){
    var v=+slider.value; setLive(v>=last);
    try{ sessionStorage.setItem('wstep', String(v)); }catch(e){}
    paint(v); });
  if(live) live.addEventListener('click', function(){
    setLive(true); try{ sessionStorage.removeItem('wstep'); }catch(e){} paint(last); });
})();
"""
