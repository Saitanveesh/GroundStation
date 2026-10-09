/* HROT AirTrust v0.1 — standalone operator console.
   Synthetic fixtures are not live sensor data or physical identity proofs. */
(() => {
  "use strict";
  const $ = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];
  const safe = s => String(s ?? "").replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const icon = name => '<svg aria-hidden="true"><use href="#i-'+name+'"></use></svg>';
  const state = {data:null,selected:"TRK-041",page:"overview",zoom:1,token:"",loading:false};
  const navTitles = {overview:"Airspace Overview",tracks:"Aircraft & Tracks",missions:"Mission Permits",identities:"Identity Registry",incidents:"Incident Desk",sensors:"Sensor Inputs",evidence:"Evidence Ledger"};
  let refreshTimer;

  async function api(path, opts={}) {
    const headers={"Content-Type":"application/json",...(state.token?{"X-HROT-Token":state.token}:{})};
    const res=await fetch("/api"+path,{...opts,headers:{...headers,...opts.headers}});
    const body=await res.json().catch(()=>({detail:"Unexpected server response"}));
    if(!res.ok) throw new Error(typeof body.detail==="string"?body.detail:JSON.stringify(body.detail||body));
    return body;
  }
  function toast(message,isError=false) {
    const element=document.createElement("div");element.className="toast"+(isError?" error":"");element.textContent=message;
    $("#toastHost").appendChild(element);setTimeout(()=>element.remove(),4400);
  }
  function shortTime(v){if(!v)return "—";const d=new Date(v);return isNaN(+d)?"—":d.toISOString().slice(11,16)+" UTC";}
  function fullTime(v){if(!v)return "—";const d=new Date(v);return isNaN(+d)?"—":d.toISOString().replace("T"," ").slice(0,16)+" UTC";}
  function chip(value){const label=String(value||"unknown").replaceAll("_"," ");return '<span class="state-chip '+safe(value)+'">'+safe(label)+'</span>';}
  function fmtCoord(n){return Number(n).toFixed(5)}
  async function load(silent=false){
    if(state.loading)return;state.loading=true;
    try{
      state.data=await api("/bootstrap");
      if(!state.data.tracks.some(x=>x.id===state.selected))state.selected=state.data.tracks[0]?.id||null;
      render();
      $("#syncTime").textContent="SYNC "+new Date().toISOString().slice(11,19);
      const isDemo=state.data.mode==="demo";
      $("#demoBanner").classList.toggle("hidden",!isDemo||sessionStorage.getItem("hrot-demo-banner")==="hidden");
      $("#modeTop").textContent=isDemo?"DEMO ENVIRONMENT":"LIVE MODE / ADAPTERS";
      $("#modeTop").classList.toggle("live",!isDemo);
      $("#scenarioBtn").classList.toggle("hidden",!isDemo);
      $("#addObservationBtn").title="Add observation manually (not cryptographically authenticated)";
    }catch(e){
      if(!silent)toast("Cannot load HROT Core: "+e.message,true);
      if(e.message.includes("X-HROT-Token")&&!state.token)promptToken();
      $("#syncTime").textContent="CORE NOT AVAILABLE";
    }finally{state.loading=false}
  }
  function render(){
    const d=state.data;if(!d)return;
    $("#statTracks").textContent=d.stats.tracks.toString().padStart(2,"0");
    $("#statUnresolved").textContent=d.stats.unresolved.toString().padStart(2,"0");
    $("#statAuthorized").textContent=d.stats.authorized.toString().padStart(2,"0");
    $("#statIncidents").textContent=d.stats.active_incidents.toString().padStart(2,"0");
    $("#trackCountChip").textContent=d.tracks.length+" TRACKS";
    renderMap();renderInspector();renderObservationList();renderActivity();renderTables();renderIncidents();renderSensors();
  }
  function mapProjection(t){
    const center=state.data.site;
    const width=1000,height=620, mlat=111132, mlon=111320*Math.cos(center.lat*Math.PI/180);
    const radius=1600/state.zoom;
    return {x:Math.max(18,Math.min(982,width/2+(t.lon-center.lon)*mlon/radius*310)),
            y:Math.max(18,Math.min(602,height/2-(t.lat-center.lat)*mlat/radius*310))};
  }
  function renderMap(){
    if(!state.data)return;
    const colors={corroborated:"#4de8c3",ambiguous:"#f7c16a",contradicted:"#fb8792"};
    $("#trackMarkers").innerHTML=state.data.tracks.map(t=>{
      const {x,y}=mapProjection(t),color=colors[t.association_state]||"#b8ced8",selected=t.id===state.selected;
      const label=safe(t.id);
      return '<g class="track-marker '+(selected?"selected":"")+'" data-track="'+label+'" transform="translate('+x.toFixed(1)+' '+y.toFixed(1)+')" style="color:'+color+'"><circle r="23" fill="'+color+'" fill-opacity=".06" stroke="'+color+'" stroke-opacity=".21" stroke-width="1.3"/><circle class="selected-ring" r="29" fill="none" stroke="'+color+'" stroke-width="1.5"/><circle class="inner" r="9" fill="#102633" stroke="'+color+'" stroke-width="2.3"/><path d="M0-21l-4 7h8z" fill="'+color+'" transform="rotate('+Number(t.heading)+')"/><text x="18" y="-15">'+label+'</text></g>';
    }).join("");
    $$("#trackMarkers .track-marker").forEach(el=>el.addEventListener("click",()=>selectTrack(el.dataset.track)));
  }
  function selectTrack(id){
    state.selected=id;
    renderMap();renderInspector();renderObservationList();
  }
  function renderInspector(){
    const t=state.data.tracks.find(x=>x.id===state.selected);
    if(!t){$("#trackInspector").innerHTML='<div class="empty">No tracks reported. Connect a real adapter to add observations.</div>';return}
    $("#trackInspector").innerHTML=
      '<div class="target-profile"><div class="target-avatar">'+icon("radar")+'</div><div><h3>'+safe(t.label)+'</h3><p>'+safe(t.id)+' &nbsp; / &nbsp; '+safe(t.aircraft_type.toUpperCase())+'</p></div></div>'+
      '<div class="status-head">TRUST ASSESSMENT</div><div class="state-stack">'+
        '<div class="state-line"><span>Identity proof</span>'+chip(t.identity_state)+'</div>'+
        '<div class="state-line"><span>Physical association</span>'+chip(t.association_state)+'</div>'+
        '<div class="state-line"><span>Mission authorization</span>'+chip(t.authorization_state)+'</div></div>'+
      '<div class="inspector-separator"></div><div class="status-head" style="margin-top:0">REPORTED TELEMETRY</div>'+
      '<div class="telemetry-grid"><div><small>ALTITUDE</small><strong>'+Number(t.alt_m).toFixed(1)+' m</strong></div>'+
        '<div><small>GROUND SPEED</small><strong>'+Number(t.speed_ms).toFixed(1)+' m/s</strong></div>'+
        '<div><small>HEADING</small><strong>'+Math.round(t.heading)+'°</strong></div>'+
        '<div><small>POSITION</small><strong style="font-size:10px">'+fmtCoord(t.lat)+'<br>'+fmtCoord(t.lon)+'</strong></div></div>'+
      '<div class="inspect-warning">Source: '+safe(t.source)+' · '+(t.is_demo?'SYNTHETIC fixture':'ADAPTER OBSERVATION')+
      '<br>Signed key possession does not independently verify this physical location.<br>Last record: '+fullTime(t.observed_at)+'</div>';
  }
  function renderObservationList(){
    $("#overviewTrackList").innerHTML=state.data.tracks.length?state.data.tracks.map(t=>
      '<div class="observation-row '+(t.id===state.selected?"selected":"")+'" data-select-track="'+safe(t.id)+'"><div class="track-icon">'+icon("radar")+
      '</div><div><strong>'+safe(t.label)+'</strong><small>'+safe(t.id)+' / '+safe(t.source)+'</small></div>'+chip(t.association_state)+'</div>'
    ).join(""):'<div class="empty">No observations.</div>';
    $$("[data-select-track]").forEach(el=>el.onclick=()=>{selectTrack(el.dataset.selectTrack);navigate("overview")});
  }
  function renderActivity(){
    $("#activityFeed").innerHTML=state.data.evidence.slice(0,5).map(x=>
      '<div class="activity-row"><div class="activity-icon '+(x.severity==="attention"?"attention":"")+'">'+icon(x.severity==="attention"?"alert":"check")+
      '</div><div><strong>'+safe(x.kind.replaceAll("_"," "))+'</strong><p>'+safe(x.detail)+'</p></div><time>'+shortTime(x.timestamp).replace(" UTC","")+'</time></div>'
    ).join("")||'<div class="empty">No events.</div>';
  }
  function renderTables(){
    const d=state.data;
    $("#tracksTable").innerHTML=d.tracks.map(t=>'<tr><td><strong>'+safe(t.label)+'</strong><small>'+safe(t.id)+(t.is_demo?' · DEMO':'')+'</small></td>'+
      '<td>'+safe(t.source)+'</td><td class="mono">'+fmtCoord(t.lat)+', '+fmtCoord(t.lon)+'</td><td>'+chip(t.identity_state)+'</td><td>'+chip(t.association_state)+'</td><td>'+chip(t.authorization_state)+'</td><td class="mono">'+shortTime(t.observed_at)+'</td></tr>').join("")||'<tr><td colspan="7" class="empty">No observations received.</td></tr>';
    $("#missionsTable").innerHTML=d.missions.map(m=>'<tr><td><strong>'+safe(m.title)+'</strong><small>'+safe(m.id)+(m.is_demo?' · DEMO':'')+'</small></td><td class="mono">'+safe(m.identity_id)+'</td><td>'+safe(m.location)+'</td><td>'+fullTime(m.start_time)+'<br>'+fullTime(m.end_time)+'</td><td>'+chip(m.status)+'</td><td>'+(m.status==="pending"?'<button class="btn secondary" data-approve="'+safe(m.id)+'">Approve</button>':'<span class="muted">—</span>')+'</td></tr>').join("")||'<tr><td colspan="6" class="empty">No missions.</td></tr>';
    $("#identitiesTable").innerHTML=d.identities.map(i=>'<tr><td><strong>'+safe(i.label)+'</strong><small>'+safe(i.id)+'</small></td><td>'+safe(i.issuer)+'</td><td class="mono">'+safe(i.key_type)+'</td><td>'+chip(i.protection_claim)+'</td><td>'+chip(i.status)+'</td><td>'+(i.status==="active"?'<button class="btn secondary" data-challenge="'+safe(i.id)+'">Verify key</button> <button class="btn danger" data-revoke="'+safe(i.id)+'">Revoke</button>':'—')+'</td></tr>').join("")||'<tr><td colspan="6" class="empty">No credentials enrolled. Enroll a real Ed25519 public key to start verification.</td></tr>';
    $("#evidenceTable").innerHTML=d.evidence.map(e=>'<tr><td class="mono">'+e.seq+'</td><td class="mono">'+shortTime(e.timestamp)+'</td><td><strong>'+safe(e.kind)+'</strong></td><td>'+safe(e.detail)+'</td><td>'+safe(e.source)+'</td><td class="mono" title="'+safe(e.hash)+'">'+safe(e.hash.slice(0,12))+'…</td></tr>').join("")||'<tr><td colspan="6" class="empty">No events.</td></tr>';
    $$("[data-approve]").forEach(el=>el.onclick=()=>perform("Approve pending mission?",()=>api("/missions/"+encodeURIComponent(el.dataset.approve)+"/approve",{method:"POST"})));
    $$("[data-revoke]").forEach(el=>el.onclick=()=>perform("Revoke enrolled key? This prevents new successful proofs.",()=>api("/identities/"+encodeURIComponent(el.dataset.revoke)+"/revoke",{method:"POST"})));
    $$("[data-challenge]").forEach(el=>el.onclick=()=>startChallenge(el.dataset.challenge));
  }
  function renderIncidents(){
    $("#incidentCards").innerHTML=state.data.incidents.map(i=>
      '<div class="incident-card"><div class="card-title"><h3>'+safe(i.title)+'</h3>'+chip(i.severity)+'</div><p>'+safe(i.description)+'</p><div class="card-meta"><span>'+safe(i.id)+'</span><span>TRACK '+safe(i.track_id||"N/A")+'</span><span>'+shortTime(i.created_at)+'</span></div>'+
      '<div class="card-title" style="margin:0"><span>'+chip(i.status)+(i.is_demo?' <small class="muted">DEMO</small>':'')+'</span>'+(i.status==="open"?'<button class="btn secondary" data-ack="'+safe(i.id)+'">Acknowledge</button>':'')+'</div></div>'
    ).join("")||'<div class="empty">No incidents in the queue.</div>';
    $$("[data-ack]").forEach(el=>el.onclick=()=>perform("Acknowledge incident?",()=>api("/incidents/"+encodeURIComponent(el.dataset.ack)+"/ack",{method:"POST"})));
  }
  function renderSensors(){
    $("#sensorCards").innerHTML=state.data.sensors.map(s=>
      '<div class="sensor-card"><div class="sensor-icon">'+icon("radio")+'</div><div class="card-title"><h3>'+safe(s.label)+'</h3>'+chip(s.status)+'</div><p>Input type: '+safe(s.type)+'. '+(s.is_demo?'Training fixture only. There is no physical sensor connection.':'No active adapter heartbeat has been established.')+'</p><div class="card-meta"><span>'+safe(s.id)+'</span><span>'+shortTime(s.last_seen)+'</span></div></div>'
    ).join("")||'<div class="empty">No sensor adapters registered.</div>';
  }
  function navigate(page){
    if(!navTitles[page])return;
    state.page=page;
    $$(".page").forEach(el=>el.classList.toggle("visible",el.id==="page-"+page));
    $$(".rail-link").forEach(el=>el.classList.toggle("active",el.dataset.nav===page));
    $("#sectionTitle").textContent=navTitles[page];
    $("#scenarioMenu").classList.add("hidden");
    window.scrollTo({top:0,behavior:"smooth"});
  }
  function modal(title,body,eyebrow="HROT OPERATOR ACTION"){
    $("#modalTitle").textContent=title;$("#modalEyebrow").textContent=eyebrow;
    $("#modalBody").innerHTML=body;$("#modal").classList.remove("hidden");
  }
  function closeModal(){$("#modal").classList.add("hidden")}
  function fieldsForm(fields,submit="Save"){
    return '<form class="dialog-content" id="actionForm"><div class="form-grid">'+fields.map(f=>
      '<div class="form-field"><label for="f-'+safe(f.name)+'">'+safe(f.label)+'</label>'+
      (f.type==="select"?'<select id="f-'+safe(f.name)+'" name="'+safe(f.name)+'">'+f.options.map(o=>'<option value="'+safe(o)+'">'+safe(o.replaceAll("_"," "))+'</option>').join("")+'</select>':
      '<input id="f-'+safe(f.name)+'" name="'+safe(f.name)+'" type="'+safe(f.type||"text")+'" '+(f.required!==false?"required":"")+' '+(f.placeholder?'placeholder="'+safe(f.placeholder)+'"':'')+' '+(f.value?'value="'+safe(f.value)+'"':'')+'>')+'</div>'
    ).join("")+'</div><div class="dialog-actions"><button type="button" class="btn outline" id="formCancel">Cancel</button><button type="submit" class="btn primary">'+safe(submit)+'</button></div></form>';
  }
  function wireForm(action){
    $("#formCancel").onclick=closeModal;
    $("#actionForm").onsubmit=async e=>{
      e.preventDefault();
      const obj=Object.fromEntries(new FormData(e.target).entries());
      const submit=e.target.querySelector('[type="submit"]');submit.disabled=true;
      try{await action(obj);closeModal();toast("Action completed and recorded");await load()}
      catch(err){toast(err.message,true);submit.disabled=false}
    };
  }
  function missionForm(){
    const toLocalInput = dt => new Date(dt.getTime()-dt.getTimezoneOffset()*60000).toISOString().slice(0,16);const isoLocal=toLocalInput(new Date(Date.now()+3600000));const endLocal=toLocalInput(new Date(Date.now()+7200000));
    modal("Create mission permit",fieldsForm([
      {name:"title",label:"MISSION NAME",placeholder:"e.g. Rooftop inspection"},
      {name:"identity_id",label:"DECLARED DEVICE ID",placeholder:"e.g. CONTRACT-02"},
      {name:"location",label:"AUTHORIZED LOCATION",value:"Training Sector 7"},
      {name:"start_time",label:"START TIME (LOCAL)",type:"datetime-local",value:isoLocal},
      {name:"end_time",label:"END TIME (LOCAL)",type:"datetime-local",value:endLocal}
    ],"Create pending permit"));
    wireForm(d=>api("/missions",{method:"POST",body:JSON.stringify({...d,start_time:new Date(d.start_time).toISOString(),end_time:new Date(d.end_time).toISOString()})}));
  }
  function identityForm(){
    modal("Enroll public identity",fieldsForm([
      {name:"id",label:"DEVICE ID",placeholder:"e.g. GATEWAY-01"},
      {name:"label",label:"DISPLAY NAME",placeholder:"e.g. Inspection vehicle"},
      {name:"issuer",label:"ENROLLMENT AUTHORITY (OPERATOR-DECLARED)",placeholder:"e.g. Facility Lab"},
      {name:"public_key",label:"ED25519 PUBLIC KEY (BASE64)",placeholder:"32-byte public key, base64 encoded"},
      {name:"protection_claim",label:"KEY PROTECTION (UNATTESTED)",type:"select",options:["not_attested","software_declared","puf_declared","secure_element_declared"]}
    ],"Enroll public key"));
    const form=$("#actionForm");
    form.insertAdjacentHTML("beforeend",'<p class="form-hint" style="padding:0 25px 18px">Device origin, hardware protection and CA endorsement are NOT verified in this prototype. Never paste private keys.</p>');
    wireForm(d=>api("/identities",{method:"POST",body:JSON.stringify(d)}));
  }
  function observationForm(){
    modal("Submit an observation",fieldsForm([
      {name:"id",label:"TRACK ID",placeholder:"TRK-LIVE-001"},
      {name:"label",label:"LABEL",placeholder:"Visual target"},
      {name:"source",label:"SOURCE ID",placeholder:"adapter-camera-01"},
      {name:"lat",label:"LATITUDE",type:"number",value:"12.915"},
      {name:"lon",label:"LONGITUDE",type:"number",value:"77.607"},
      {name:"alt_m",label:"ALTITUDE (METRES)",type:"number",value:"80"},
      {name:"heading",label:"HEADING (DEGREES)",type:"number",value:"0"},
      {name:"speed_ms",label:"SPEED (METRES/SEC)",type:"number",value:"0"}
    ],"Record observation"));
    wireForm(d=>api("/observations",{method:"POST",body:JSON.stringify({...d,lat:+d.lat,lon:+d.lon,alt_m:+d.alt_m,heading:+d.heading,speed_ms:+d.speed_ms})}));
  }
  async function startChallenge(identityId){
    try{
      const c=await api("/verify/challenge",{method:"POST",body:JSON.stringify({identity_id:identityId})});
      modal("Verify device signature",'<div class="dialog-content"><div class="form-field"><label>TRANSCRIPT TO SIGN (UTF-8)</label><textarea readonly rows="4">'+safe(c.transcript)+'</textarea></div>'+
        '<p class="form-hint">The private key stays on the device. Sign the exact transcript and paste the 64-byte signature in base64. Expires 90 seconds after issuance. No track binding is inferred.</p>'+
        '<div class="form-field" style="margin-top:15px"><label>SIGNATURE (BASE64)</label><textarea id="proofSignature" rows="3" placeholder="Signature created by the enrolled Ed25519 key"></textarea></div>'+
        '<div class="dialog-actions"><button class="btn outline" id="proofCancel">Cancel</button><button class="btn primary" id="proofSubmit">Verify signature</button></div></div>',
        "FRESH CRYPTOGRAPHIC CHALLENGE");
      $("#proofCancel").onclick=closeModal;
      $("#proofSubmit").onclick=async ()=>{
        try{
          const p=await api("/verify/complete",{method:"POST",body:JSON.stringify({challenge_id:c.challenge_id,signature:$("#proofSignature").value.trim()})});
          closeModal();toast(p.verified?"Signature valid: key possession verified; physical track NOT bound.":"Proof rejected: "+p.reason,!p.verified);await load()
        }catch(e){toast(e.message,true)}
      };
    }catch(e){toast(e.message,true)}
  }
  async function perform(message,action){
    if(!window.confirm(message))return;
    try{await action();toast("Change saved and audit event recorded");await load()}catch(e){toast(e.message,true)}
  }
  function promptToken(){
    modal("Administrator access",'<div class="dialog-content"><p class="form-hint">Live mode requires an administrator token for API access. This token is held in page memory only.</p><div class="form-field" style="margin-top:16px"><label>X-HROT-Token</label><input type="password" id="tokenEntry" autocomplete="off"></div><div class="dialog-actions"><button class="btn primary" id="tokenSave">Unlock console</button></div></div>',"AUTHENTICATION REQUIRED");
    $("#tokenSave").onclick=()=>{state.token=$("#tokenEntry").value;closeModal();load()};
  }
  function updateClock(){$("#utcClock").textContent=new Date().toISOString().slice(11,19)}
  function attach(){
    $$("[data-nav]").forEach(el=>el.addEventListener("click",()=>navigate(el.dataset.nav)));
    $("#refreshBtn").onclick=()=>load();
    $("#dismissBanner").onclick=()=>{sessionStorage.setItem("hrot-demo-banner","hidden");$("#demoBanner").classList.add("hidden")};
    $("#scenarioBtn").onclick=e=>{$("#scenarioMenu").classList.toggle("hidden");e.stopPropagation()};
    $$("#scenarioMenu [data-scenario]").forEach(el=>el.onclick=async()=>{
      $("#scenarioMenu").classList.add("hidden");
      try{await api("/demo/scenario",{method:"POST",body:JSON.stringify({scenario:el.dataset.scenario})});toast("Synthetic scenario: "+el.dataset.scenario);await load()}catch(e){toast(e.message,true)}
    });
    document.addEventListener("click",e=>{if(!e.target.closest("#scenarioMenu")&&!e.target.closest("#scenarioBtn"))$("#scenarioMenu").classList.add("hidden")});
    $("#zoomIn").onclick=()=>{state.zoom=Math.min(3,state.zoom*1.35);renderMap()};
    $("#zoomOut").onclick=()=>{state.zoom=Math.max(.5,state.zoom/1.35);renderMap()};
    $("#mapReset").onclick=()=>{state.zoom=1;renderMap()};
    $("#createMissionBtn").onclick=missionForm;
    $("#enrollIdentityBtn").onclick=identityForm;
    $("#addObservationBtn").onclick=observationForm;
    $("#modalClose").onclick=closeModal;
    $("#modal").addEventListener("click",e=>{if(e.target.id==="modal")closeModal()});
    document.addEventListener("keydown",e=>{if(e.key==="Escape"){closeModal();$("#scenarioMenu").classList.add("hidden")}});
    $("#verifyLedgerBtn").onclick=async()=>{
      try{const r=await api("/evidence/check");const el=$("#ledgerResult");el.className="ledger-result "+(r.valid?"ok":"bad");el.textContent=r.valid?"PASS — "+r.entries_checked+" records checked · head "+r.head_hash.slice(0,20)+"… · local integrity only":"FAIL — evidence chain discrepancy near record #"+r.first_invalid_seq}
      catch(e){toast(e.message,true)}
    };
    $("#exportLedgerBtn").onclick=async()=>{
      try{
        const data=await api("/evidence/export");
        const blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"});
        const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download="hrot-airtrust-evidence-"+Date.now()+".json";a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);
        toast("Evidence JSON exported (not externally signed)")
      }catch(e){toast(e.message,true)}
    };
  }
  attach();updateClock();setInterval(updateClock,1000);load();
  refreshTimer=setInterval(()=>{if(!document.hidden&&!$("#modal").classList.contains("hidden"))return;if(!document.hidden)load(true)},9000);
})();
