'use strict';
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
let data = {}, me, paused = false, activeTab = 'overview';
let timer;
function toast(message) { $('#toast').textContent=message; $('#toast').classList.add('visible'); clearTimeout(timer); timer=setTimeout(()=>$('#toast').classList.remove('visible'),6000); }
async function api(path, body, method='POST') {
  const options={method: body===undefined?'GET':method,headers:{'X-Requested-With':'FBTT'}};
  if(body!==undefined) { if(body instanceof FormData) options.body=body; else { options.headers['Content-Type']='application/json'; options.body=JSON.stringify(body); } }
  const response=await fetch(path,options);
  if(!response.ok) {
    let detail; try { detail=(await response.json()).detail; } catch { detail=`HTTP ${response.status}`; }
    if(response.status===401 && path!='/api/login') showLogin();
    throw Error(typeof detail==='string'?detail:JSON.stringify(detail));
  }
  return response.json();
}
function node(tag,text,className) { const el=document.createElement(tag); if(text!==undefined) el.textContent=text; if(className) el.className=className; return el; }
function empty(container) { container.replaceChildren(node('p','Chưa có dữ liệu.','empty')); }
function button(parent,label,fn,kind='secondary') { const b=node('button',label,kind); b.type='button'; b.addEventListener('click',async()=>{ b.disabled=true; try { await fn(); } catch(e) { toast(e.message); } finally { b.disabled=false; } }); parent.append(b); return b; }
function card(title,badge) { const el=node('article',undefined,'card'); el.append(node('h2',title)); if(badge) el.append(node('span',badge,'badge')); return el; }
function line(parent,text) { parent.append(node('p',text)); }
function list(selector,items,render) { const container=$(selector); container.replaceChildren(); if(!items.length) return empty(container); items.forEach(i=>container.append(render(i))); }
function options(select,items) { const old=select.value; select.replaceChildren(); for(const i of items) { const o=node('option',`${i.name} (#${i.id})`); o.value=i.id; select.append(o); } if([...select.options].some(o=>o.value===old)) select.value=old; }
function profileName(id) { return data.profiles.find(p=>p.id===id)?.name || `#${id}`; }
function date(epoch) { return new Date(epoch*1000).toLocaleString('vi-VN'); }
const states={pending:'Chờ duyệt',queued:'Đã duyệt',publishing:'Đang gửi',processing:'Đang xử lý',success:'Thành công',failed:'Thất bại',uncertain:'Cần kiểm tra trên nền tảng',manual_link:'Chờ gắn Shop link',cancelled:'Đã hủy',active:'Hoạt động',paused:'Tạm dừng',error:'Lỗi',restricted:'Bị hạn chế'};
function state(s){return states[s]||s;}
function tab(name) { activeTab=name; $$('[data-panel]').forEach(p=>p.hidden=p.dataset.panel!==name); $$('#nav button').forEach(b=>b.classList.toggle('active',b.dataset.tab===name)); $('#page-title').textContent=$(`#nav [data-tab="${name}"]`).textContent; }
function showLogin() { $('#login').hidden=false; $('#workspace').hidden=true; }
function rights() { $$('[data-admin]').forEach(n=>n.hidden=me.role!=='admin'); $$('[data-publisher]').forEach(n=>n.hidden=me.role==='viewer'); }
async function refresh() {
  const keys=['profiles','media','products','captions','schedules','jobs','events'];
  const values=await Promise.all(keys.map(k=>api('/api/'+k)));
  keys.forEach((k,i)=>data[k]=values[i]);
  const report=await api('/api/reports/summary'); paused=report.paused;
  $('#publish-status').textContent=(paused?'Hệ thống đang tạm dừng. ':report.publisher_enabled?'Worker đã bật. ':'Chưa bật đăng thật (PUBLISH_ENABLED=false). ')+'Bài cần được duyệt trước khi đăng theo cấu hình lịch.';
  $('#pause').textContent=paused?'Tiếp tục đăng':'Dừng toàn hệ thống';
  $$('[data-options]').forEach(s=>options(s,data[s.dataset.options]));
  $('#stats').replaceChildren();
  const count=states=>data.jobs.filter(j=>states.includes(j.status)).length;
  [['Tài khoản',data.profiles.length],['Video trong kho',data.media.length],['Chờ duyệt / đã duyệt',count(['pending','queued'])],['Bài thành công',count(['success','manual_link'])]].forEach(([label,value])=>{const el=node('div',undefined,'stat');el.append(node('span',label),node('strong',String(value)));$('#stats').append(el);});
  list('#upcoming',data.jobs.filter(j=>['pending','queued'].includes(j.status)).sort((a,b)=>a.scheduled-b.scheduled).slice(0,5),j=>{const el=node('div',`${profileName(j.profile_id)} · ${state(j.status)}`,'row');el.append(node('small',date(j.scheduled)));return el;});
  list('#recent',data.events.slice(0,5),e=>{const el=node('div',e.message,'row');el.append(node('small',date(e.created)));return el;});
  list('#profile-list',data.profiles,p=>{
    const el=card(p.name,`${p.platform} · ${state(p.status)}`);line(el,`Nhóm: ${p.niche||'Chưa gán'} · ID: ${p.external_id||'Chờ OAuth'}`);line(el,`Token: ${p.token_status}${p.expires?' · Hạn: '+date(p.expires):''}`);if(p.notes)line(el,p.notes);
    if(me.role==='admin') {
      button(el,'Kết nối OAuth',async()=>{const r=await api(`/api/profiles/${p.id}/oauth`,{});window.location.assign(r.url);});
      button(el,p.status==='active'?'Tạm dừng':'Kích hoạt',async()=>{await api(`/api/profiles/${p.id}`,{...p,status:p.status==='active'?'paused':'active'},'PUT');await refresh();});
      button(el,'Sửa',()=>{const form=$('#profile-form');for(const key of ['name','platform','external_id','niche','notes','color','status'])form.elements[key].value=p[key]||''; form.dataset.editId=p.id; form.querySelector('button').textContent='Lưu thay đổi';form.scrollIntoView({behavior:'smooth'});});
      button(el,'Xóa',async()=>{if(confirm(`Xóa ${p.name}? Các bài trong hàng đợi cần được xử lý trước.`)){await api(`/api/profiles/${p.id}`,{},'DELETE');await refresh();}},'danger');
    } return el;
  });
  list('#media-list',data.media,m=>{
    const el=card(m.name,`${m.vertical?'9:16':'Khác 9:16'} · ${m.duration.toFixed(1)}s`);const video=node('video');video.controls=true;video.preload='none';video.src=`/api/media/${m.id}/video`;el.append(video);line(el,`${m.width}×${m.height} · ${(m.size/1048576).toFixed(2)} MiB`);
    line(el,m.assignments.map(a=>`${profileName(a.profile_id)}: ${a.used?'đã dùng':'chưa dùng'}`).join(' · ')||'Chưa gán tài khoản');
    if(me.role==='admin') {
      const select=node('select');select.setAttribute('aria-label','Tài khoản nhận video');options(select,data.profiles);el.append(select);
      button(el,'Gán tài khoản',async()=>{if(!select.value)throw Error('Thêm tài khoản trước');const r=await api(`/api/media/${m.id}/assign`,{profile_ids:[Number(select.value)]});toast(r.duplicate_warning?'Đã gán. Cảnh báo: video dùng cho nhiều tài khoản.':'Đã gán video');await refresh();});
      const product=node('select');product.setAttribute('aria-label','Sản phẩm gắn video');product.multiple=true;options(product,data.products);el.append(product);
      button(el,'Gán sản phẩm đã chọn',async()=>{await api(`/api/media/${m.id}/products`,{product_ids:[...product.selectedOptions].map(o=>Number(o.value))});toast('Đã gán sản phẩm');});
      button(el,'Tạo thumbnail',async()=>{await api(`/api/media/${m.id}/thumbnail`,{});toast('Đã tạo thumbnail');});
    }return el;
  });
  list('#product-list',data.products,p=>{const el=card(p.name,p.available?'Đang bán':'Hết hàng');line(el,`${p.price.toLocaleString('vi-VN')}đ · Hoa hồng ${p.commission}%`);line(el,`Ngách: ${p.niche||'Chưa gán'}`);if(p.shopee_link)line(el,p.shopee_link);if(p.tiktok_link)line(el,p.tiktok_link);if(me.role==='admin'){
    button(el,p.available?'Đánh dấu hết hàng':'Mở bán lại',async()=>{await api(`/api/products/${p.id}`,{...p,available:!p.available},'PUT');await refresh();});
    button(el,'Sửa',()=>{const form=$('#product-form');for(const key of ['name','price','commission','niche','image','shopee_link','tiktok_link'])form.elements[key].value=p[key]??'';form.dataset.editId=p.id;form.querySelector('button').textContent='Lưu thay đổi';form.scrollIntoView({behavior:'smooth'});});
    button(el,'Tạo link tracking',async()=>{if(!data.profiles.length)throw Error('Thêm tài khoản trước');const pid=prompt('ID tài khoản nhận tracking',String(data.profiles[0].id));if(!pid)return;const link=await api('/api/links',{product_id:p.id,profile_id:Number(pid),platform:p.shopee_link?'shopee':'tiktok'});line(el,link.url);});
  }return el;});
  list('#caption-list',data.captions,c=>{const el=card(c.name,`${c.variants.length} biến thể`);c.variants.forEach(v=>el.append(node('pre',v)));line(el,c.hashtags.join(' '));return el;});
  list('#schedule-list',data.schedules,s=>{const el=card(profileName(s.profile_id),s.enabled?'Đã bật':'Đã tắt');line(el,`${s.times.join(', ')} · ${s.timezone}`);line(el,`Ngày: ${s.weekdays.map(d=>['T2','T3','T4','T5','T6','T7','CN'][d]).join(', ')} · Lệch: 0–${s.jitter_minutes} phút`);line(el,`Tối đa ${s.daily_limit} bài/ngày · ${s.require_approval?'Cần duyệt':'Tự động'}`);if(me.role==='admin')button(el,s.enabled?'Tắt lịch':'Bật lịch',async()=>{await api('/api/schedules',{...s,enabled:!s.enabled});await refresh();});return el;});
  list('#job-list',data.jobs,j=>{const el=card(`${profileName(j.profile_id)} · Bài #${j.id}`,state(j.status));line(el,date(j.scheduled));el.append(node('pre',j.caption));if(j.error)line(el,`Lỗi: ${j.error}`);if(j.remote_id)line(el,`Mã nền tảng: ${j.remote_id}`);if(me.role!=='viewer'){
    if(j.status==='pending')button(el,'Duyệt đăng',async()=>{const review=await api(`/api/jobs/${j.id}/review`);if(review.requires_acknowledgment&&!confirm(review.warnings.join('\n')+'\nBạn đã kiểm tra và xác nhận nội dung?'))return;await api(`/api/jobs/${j.id}/approve`,{acknowledged:true});await refresh();});
    if(['pending','queued'].includes(j.status))button(el,'Hủy',async()=>{await api(`/api/jobs/${j.id}/cancel`,{});await refresh();},'danger');
    if(j.status==='manual_link')button(el,'Đã gắn Shop link',async()=>{await api(`/api/jobs/${j.id}/shop-linked`,{});await refresh();});
  }return el;});
  list('#event-list',data.events,e=>{const el=node('article');el.append(node('span',e.kind,'badge'));line(el,e.message);line(el,`${date(e.created)} · ${e.profile_id?profileName(e.profile_id):'Hệ thống'}`);return el;});
  rights();tab(activeTab);
}
function bindForm(selector,action) { $(selector).addEventListener('submit',async e=>{e.preventDefault();const form=e.currentTarget,b=form.querySelector('button');b.disabled=true;try{await action(Object.fromEntries(new FormData(form)),form);if(selector!=='#login-form' && selector!=='#totp-setup' && selector!=='#totp-enable'){form.reset();delete form.dataset.editId;toast('Đã lưu');await refresh();}}catch(err){if(selector==='#login-form')$('#login-error').textContent=err.message;else toast(err.message);}finally{b.disabled=false;}}); }
bindForm('#login-form',async body=>{if(!body.otp)delete body.otp;await api('/api/login',body);await start();$('#login-form').reset();});
bindForm('#profile-form',async(body,form)=>{body.external_id=body.external_id||null;await api('/api/profiles'+(form.dataset.editId?'/'+form.dataset.editId:''),body,form.dataset.editId?'PUT':'POST');form.querySelector('button').textContent='Thêm tài khoản';});
bindForm('#product-form',async(body,form)=>{for(const k of ['price','commission'])body[k]=Number(body[k]);for(const k of ['image','shopee_link','tiktok_link'])if(!body[k])body[k]=null;body.available=form.dataset.editId?data.products.find(p=>p.id===Number(form.dataset.editId)).available:true;await api('/api/products'+(form.dataset.editId?'/'+form.dataset.editId:''),body,form.dataset.editId?'PUT':'POST');form.querySelector('button').textContent='Thêm sản phẩm';});
bindForm('#media-form',async(_,form)=>{await api('/api/media',new FormData(form));});
bindForm('#caption-form',async body=>{body.variants=body.variants.split('\n').map(s=>s.trim()).filter(Boolean);body.hashtags=body.hashtags.split(/\s+/).filter(Boolean);await api('/api/captions',body);});
bindForm('#schedule-form',async body=>{for(const k of ['profile_id','product_id','caption_id','jitter_minutes','daily_limit'])body[k]=Number(body[k]);body.times=body.times.split(',').map(s=>s.trim());body.weekdays=body.weekdays.split(',').map(Number);body.require_approval=body.require_approval==='true';await api('/api/schedules',body);});
bindForm('#job-form',async body=>{for(const k of ['profile_id','media_id','product_id','caption_id'])body[k]=Number(body[k]);body.scheduled=Math.floor(new Date(body.scheduled).getTime()/1000);await api('/api/jobs',body);});
bindForm('#user-form',async body=>{await api('/api/users',body);});
bindForm('#totp-setup',async body=>{const r=await api('/api/2fa/setup',body);$('#totp-secret').textContent='Thêm khóa này vào Authenticator, sau đó nhập mã để kích hoạt: '+r.secret;$('#totp-enable').hidden=false;$('#totp-setup').reset();});
bindForm('#totp-enable',async body=>{await api('/api/2fa/enable',body);$('#totp-secret').textContent='Đã bật 2FA. Lần đăng nhập tiếp theo cần mã Authenticator.';$('#totp-enable').hidden=true;});
$('#nav').addEventListener('click',e=>{if(e.target.dataset.tab)tab(e.target.dataset.tab);});
$('#refresh').addEventListener('click',()=>refresh().catch(e=>toast(e.message)));
$('#logout').addEventListener('click',async()=>{try{await api('/api/logout',{});showLogin();}catch(e){toast(e.message);}});
for(const [id,path] of [['scan','/api/media/scan'],['plan','/api/schedules/plan'],['tick','/api/worker/tick']])$('#'+id).addEventListener('click',async()=>{try{const r=await api(path,{});toast(JSON.stringify(r));await refresh();}catch(e){toast(e.message);}});
$('#pause').addEventListener('click',async()=>{try{await api('/api/system/pause',{paused:!paused});await refresh();}catch(e){toast(e.message);}});
$('#csv').addEventListener('change',async e=>{const file=e.target.files[0];if(!file)return;try{const r=await fetch('/api/products/import',{method:'POST',headers:{'X-Requested-With':'FBTT'},body:await file.text()});const body=await r.json();if(!r.ok)throw Error(body.detail);toast(`Đã nhập ${body.imported} sản phẩm`);await refresh();}catch(err){toast(err.message);}e.target.value='';});
$('#backup').addEventListener('click',async()=>{try{const r=await fetch('/api/backups',{method:'POST',headers:{'X-Requested-With':'FBTT'}});if(!r.ok)throw Error('Sao lưu thất bại');const url=URL.createObjectURL(await r.blob());const a=node('a');a.href=url;a.download='fbtt-backup.tar.gz';a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);}catch(e){toast(e.message);}});
async function start(){me=await api('/api/me');await refresh();$('#identity').textContent=`${me.username} · ${me.role}`;$('#login').hidden=true;$('#workspace').hidden=false;}
start().catch(showLogin);
