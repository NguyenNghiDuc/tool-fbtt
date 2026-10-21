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
function icon(name) {
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('class','icon');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.7');svg.setAttribute('stroke-linecap','round');svg.setAttribute('stroke-linejoin','round');svg.setAttribute('aria-hidden','true');
  const use=document.createElementNS('http://www.w3.org/2000/svg','use');use.setAttribute('href',`/static/icons.svg#${name}`);svg.append(use);return svg;
}
function empty(container) {
  const messages={
    upcoming:['calendar','Lịch đăng đang chờ bạn','Tạo bài mới và chọn thời điểm đăng phù hợp.'],
    recent:['activity','Một khởi đầu mới','Hoạt động của Studio sẽ xuất hiện tại đây.'],
    'profile-list':['users','Thêm tài khoản đầu tiên','Kết nối Facebook hoặc TikTok bằng biểu mẫu phía trên.'],
    'media-list':['video','Thư viện đang chờ video đầu tiên','Upload nội dung của bạn để bắt đầu lên lịch.'],
    'product-list':['bag','Sản phẩm của bạn sẽ ở đây','Thêm sản phẩm và liên kết affiliate để sử dụng trong bài đăng.'],
    'caption-list':['text','Dành chỗ cho những ý tưởng hay','Tạo bộ caption đầu tiên bằng biểu mẫu phía trên.'],
    'schedule-list':['calendar','Chưa có lịch đăng nào','Chọn tài khoản và thiết lập lịch đăng của bạn.'],
    'job-list':['layers','Sẵn sàng cho bài đăng đầu tiên','Chuẩn bị video, sản phẩm và caption rồi tạo bài mới.'],
    'event-list':['activity','Chưa có hoạt động nào','Nhật ký sẽ được cập nhật khi bạn sử dụng Studio.']
  };
  const [type,title,description]=messages[container.id]||['layers','Chưa có nội dung','Dữ liệu mới sẽ xuất hiện tại đây.'];
  const el=node('div',undefined,'empty-state'),badge=node('span',undefined,'empty-icon');badge.append(icon(type));
  el.append(badge,node('strong',title,'empty-title'),node('p',description,'empty-description'));container.replaceChildren(el);
}
function button(parent,label,fn,kind='secondary') { const b=node('button',label,kind); b.type='button'; b.addEventListener('click',async()=>{ b.disabled=true; try { await fn(); } catch(e) { toast(e.message); } finally { b.disabled=false; } }); parent.append(b); return b; }
function badge(text,status='') { const el=node('span',text,'badge');if(status)el.dataset.state=status;return el; }
function card(title,label,type='video',status='') {
  const el=node('article',undefined,'card'),head=node('div',undefined,'card-head'),mark=node('span',undefined,'card-icon'),heading=node('div',undefined,'card-heading');
  mark.append(icon(type));heading.append(node('h2',title));if(label)heading.append(badge(label,status));head.append(mark,heading);el.append(head);return el;
}
function line(parent,text) { parent.append(node('p',text)); }
function list(selector,items,render) { const container=$(selector); container.replaceChildren(); if(!items.length) return empty(container); items.forEach(i=>container.append(render(i))); }
function options(select,items) { const old=select.value; select.replaceChildren(); for(const i of items) { const o=node('option',`${i.name} (#${i.id})`); o.value=i.id; select.append(o); } if([...select.options].some(o=>o.value===old)) select.value=old; }
const connectionLabels={connected:'Đã kết nối',disconnected:'Chưa kết nối',expiring:'Cần cấp quyền lại',revoked:'Quyền truy cập đã thu hồi',error:'Kết nối cần kiểm tra'};
function profileName(id) { return data.profiles.find(p=>p.id===id)?.name || `#${id}`; }
function date(epoch) { return new Date(epoch*1000).toLocaleString('vi-VN'); }
const states={pending:'Chờ duyệt',queued:'Đã duyệt',publishing:'Đang gửi',processing:'Đang xử lý',success:'Thành công',failed:'Thất bại',uncertain:'Cần kiểm tra trên nền tảng',manual_link:'Chờ gắn Shop link',cancelled:'Đã hủy',active:'Hoạt động',paused:'Tạm dừng',error:'Lỗi',restricted:'Bị hạn chế'};
function state(s){return states[s]||s;}
const pageDescriptions={overview:'Mọi nội dung, mọi tài khoản. Nắm bắt trong một góc nhìn.',profiles:'Kết nối và quản lý các kênh sáng tạo của bạn.',media:'Sắp xếp video, chuẩn bị nội dung cho những bài đăng tiếp theo.',products:'Quản lý sản phẩm và những liên kết affiliate của bạn.',captions:'Biến ý tưởng thành những caption sẵn sàng sử dụng.',schedules:'Sắp xếp thời gian, giữ nhịp sáng tạo mỗi ngày.',jobs:'Xem trước, duyệt và theo dõi từng bài đăng.',events:'Theo dõi hoạt động và các cập nhật trong Studio.',settings:'Thiết lập không gian làm việc theo cách của bạn.'};
function setNavigation(open) {
  const wasOpen=document.body.classList.contains('nav-open');
  document.body.classList.toggle('nav-open',open);$('#nav-backdrop').hidden=!open;$('#open-nav').setAttribute('aria-expanded',String(open));
  $('#sidebar').inert=window.innerWidth<=900&&!open;$('main').inert=window.innerWidth<=900&&open;
  if(open){$('#sidebar').setAttribute('role','dialog');$('#sidebar').setAttribute('aria-modal','true');$('#sidebar').setAttribute('aria-label','Điều hướng Studio');$('#close-nav').focus();}
  else{$('#sidebar').removeAttribute('role');$('#sidebar').removeAttribute('aria-modal');if(wasOpen)$('#open-nav').focus();}
}
function tab(name,resetScroll=true) {
  if(!pageDescriptions[name])return;
  activeTab=name;$$('[data-panel]').forEach(p=>p.hidden=p.dataset.panel!==name);
  $$('#nav button').forEach(b=>{b.classList.toggle('active',b.dataset.tab===name);if(b.dataset.tab===name)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
  const title=$(`#nav [data-tab="${name}"] .nav-label`).textContent;
  $('#page-title').textContent=title;$('#breadcrumb-page').textContent=title;$('#page-description').textContent=pageDescriptions[name];
  if(document.body.classList.contains('nav-open'))setNavigation(false);
  if(resetScroll)window.scrollTo({top:0,behavior:'auto'});
}
function showLogin() { $('#login').hidden=false; $('#workspace').hidden=true; setNavigation(false); }
function rights() { $$('[data-admin]').forEach(n=>n.hidden=me.role!=='admin'); $$('[data-publisher]').forEach(n=>n.hidden=me.role==='viewer'); }
async function refresh() {
  const keys=['profiles','media','products','captions','schedules','jobs','events'];
  const values=await Promise.all(keys.map(k=>api('/api/'+k)));
  keys.forEach((k,i)=>data[k]=values[i]);
  const report=await api('/api/reports/summary'); paused=report.paused;
  $('#publish-status').textContent=(paused?'Hệ thống đang tạm dừng. ':report.publisher_enabled?'Tự động đăng đã bật. ':'Chế độ chuẩn bị · Đăng bài thật đang tắt. ')+'Bạn có thể chuẩn bị nội dung và duyệt bài trong hàng đợi.';
  $('.status-banner').classList.toggle('is-paused',paused);$('.status-banner').classList.toggle('is-enabled',!paused&&report.publisher_enabled);
  $('#pause').textContent=paused?'Tiếp tục đăng':'Dừng toàn hệ thống';
  $$('[data-options]').forEach(s=>options(s,data[s.dataset.options]));
  $('#stats').replaceChildren();
  const count=states=>report.jobs.filter(j=>states.includes(j.status)).reduce((sum,j)=>sum+j.count,0);
  const metrics=[
    ['Tài khoản',data.profiles.length,'users',`${data.profiles.filter(p=>p.token_status==='connected').length} đã kết nối với Studio`],
    ['Video trong kho',data.media.length,'video',`${data.media.filter(m=>!m.assignments.length||m.assignments.some(a=>!a.used)).length} video chưa dùng`],
    ['Chờ xuất bản',count(['pending','queued']),'calendar',`${count(['pending'])} bài đang chờ bạn duyệt`],
    ['Bài thành công',count(['success','manual_link']),'check',`${count(['failed','uncertain'])} bài cần kiểm tra`]
  ];
  for(const [label,value,type,detail] of metrics){
    const el=node('div',undefined,'stat'),top=node('div',undefined,'stat-top'),mark=node('span',undefined,'stat-icon');mark.append(icon(type));top.append(node('span',label,'stat-label'),mark);
    el.append(top,node('strong',String(value)),node('div',detail,'stat-detail'));$('#stats').append(el);
  }
  const queueCount=count(['pending','queued']);$('#nav-job-count').textContent=queueCount>99?'99+':String(queueCount);$('#nav-job-count').hidden=!queueCount;
  for(const [kind,key] of [['profile','profiles'],['media','media'],['product','products'],['caption','captions'],['schedule','schedules'],['job','jobs']]){const target=$('#'+kind+'-total');if(target)target.textContent=String(data[key].length);}
  list('#upcoming',data.jobs.filter(j=>['pending','queued'].includes(j.status)).sort((a,b)=>a.scheduled-b.scheduled).slice(0,5),j=>{
    const el=node('div',undefined,'queue-row'),identity=node('div',undefined,'queue-identity'),avatar=node('span',undefined,'queue-avatar'),copy=node('div',undefined,'queue-copy');avatar.append(icon('video'));
    copy.append(node('div',profileName(j.profile_id),'queue-name'),node('div',j.caption.replace(/\s+/g,' ').slice(0,90),'queue-caption'));identity.append(avatar,copy);
    el.append(identity,node('div',new Date(j.scheduled*1000).toLocaleString('vi-VN',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}),'queue-time'),badge(state(j.status),j.status));return el;
  });
  list('#recent',data.events.slice(0,4),e=>{
    const el=node('div',undefined,'activity-row'),mark=node('span',undefined,'activity-icon'),copy=node('div',undefined,'activity-copy');mark.append(icon(e.kind.includes('error')?'activity':e.kind.includes('success')?'check':'clock'));
    const eventLabels={job_resolved:'Đã đối soát một bài đăng',publish_success:'Bài đăng đã hoàn tất',publish_error:'Có bài đăng cần kiểm tra',oauth_connected:'Tài khoản đã được kết nối',system:e.message.includes('paused')?'Đã tạm dừng đăng bài':'Đã tiếp tục đăng bài'};
    copy.append(node('p',eventLabels[e.kind]||e.message),node('small',date(e.created)));el.append(mark,copy);return el;
  });
  const distribution=$('#job-distribution');distribution.replaceChildren();
  const track=node('div',undefined,'distribution-track'),legend=node('div',undefined,'distribution-legend');
  const groups=[['queued','Đã lên lịch',['queued']],['pending','Chờ duyệt',['pending']],['success','Thành công',['success','manual_link']],['error','Cần kiểm tra',['failed','uncertain']],['processing','Đang xử lý',['processing','publishing']],['cancelled','Đã hủy',['cancelled']]];
  for(const [key,label,statuses] of groups){
    const amount=data.jobs.filter(j=>statuses.includes(j.status)).length;
    if(amount){const segment=node('span',undefined,'distribution-segment');segment.dataset.state=key;segment.style.flexGrow=String(amount);segment.title=`${label}: ${amount}`;track.append(segment);}
    const item=node('div',undefined,'legend-item');item.dataset.state=key;item.append(node('span',undefined,'legend-dot'),node('span',label),node('strong',String(amount)));legend.append(item);
  }
  $('#distribution-total').textContent=`${data.jobs.length} bài`;distribution.append(track,legend);
  list('#profile-list',data.profiles,p=>{
    const el=card(p.name,`${p.platform==='facebook'?'Facebook':'TikTok'} · ${state(p.status)}`,'users',p.status);el.dataset.platform=p.platform;line(el,`Nhóm: ${p.niche||'Chưa gán'} · ID: ${p.external_id||'Chờ OAuth'}`);line(el,`Kết nối: ${connectionLabels[p.token_status]||p.token_status}${p.expires?' · Hạn: '+date(p.expires):''}`);if(p.notes)line(el,p.notes);
    if(me.role==='admin') {
      button(el,'Kết nối tài khoản',async()=>{const r=await api(`/api/profiles/${p.id}/oauth`,{});window.location.assign(r.url);});
      button(el,p.status==='active'?'Tạm dừng':'Kích hoạt',async()=>{await api(`/api/profiles/${p.id}`,{...p,status:p.status==='active'?'paused':'active'},'PUT');await refresh();});
      button(el,'Sửa',()=>{const form=$('#profile-form');for(const key of ['name','platform','external_id','niche','notes','color','status'])form.elements[key].value=p[key]||''; form.dataset.editId=p.id; form.querySelector('button').textContent='Lưu thay đổi';form.scrollIntoView({behavior:'smooth'});});
      button(el,'Xóa',async()=>{if(confirm(`Xóa ${p.name}? Các bài trong hàng đợi cần được xử lý trước.`)){await api(`/api/profiles/${p.id}`,{},'DELETE');await refresh();}},'danger');
    } return el;
  });
  list('#media-list',data.media,m=>{
    const el=card(m.name,`${m.vertical?'9:16':'Khác 9:16'} · ${m.duration.toFixed(1)}s`,'video');const video=node('video');video.controls=true;video.preload='none';video.src=`/api/media/${m.id}/video`;el.append(video);line(el,`${m.width}×${m.height} · ${(m.size/1048576).toFixed(2)} MiB`);
    line(el,m.assignments.map(a=>`${profileName(a.profile_id)}: ${a.used?'đã dùng':'chưa dùng'}`).join(' · ')||'Chưa gán tài khoản');
    if(me.role==='admin') {
      const select=node('select');select.setAttribute('aria-label','Tài khoản nhận video');options(select,data.profiles);el.append(select);
      button(el,'Gán tài khoản',async()=>{if(!select.value)throw Error('Thêm tài khoản trước');const r=await api(`/api/media/${m.id}/assign`,{profile_ids:[Number(select.value)]});toast(r.duplicate_warning?'Đã gán. Cảnh báo: video dùng cho nhiều tài khoản.':'Đã gán video');await refresh();});
      const product=node('select');product.setAttribute('aria-label','Sản phẩm gắn video');product.multiple=true;options(product,data.products);el.append(product);
      button(el,'Gán sản phẩm đã chọn',async()=>{await api(`/api/media/${m.id}/products`,{product_ids:[...product.selectedOptions].map(o=>Number(o.value))});toast('Đã gán sản phẩm');});
      button(el,'Tạo thumbnail',async()=>{await api(`/api/media/${m.id}/thumbnail`,{});toast('Đã tạo thumbnail');});
    }return el;
  });
  list('#product-list',data.products,p=>{const el=card(p.name,p.available?'Đang bán':'Hết hàng','bag',p.available?'active':'paused');line(el,`${p.price.toLocaleString('vi-VN')}đ · Hoa hồng ${p.commission}%`);line(el,`Ngách: ${p.niche||'Chưa gán'}`);if(p.shopee_link)line(el,p.shopee_link);if(p.tiktok_link)line(el,p.tiktok_link);if(me.role==='admin'){
    button(el,p.available?'Đánh dấu hết hàng':'Mở bán lại',async()=>{await api(`/api/products/${p.id}`,{...p,available:!p.available},'PUT');await refresh();});
    button(el,'Sửa',()=>{const form=$('#product-form');for(const key of ['name','price','commission','niche','image','shopee_link','tiktok_link'])form.elements[key].value=p[key]??'';form.dataset.editId=p.id;form.querySelector('button').textContent='Lưu thay đổi';form.scrollIntoView({behavior:'smooth'});});
    button(el,'Tạo link tracking',async()=>{if(!data.profiles.length)throw Error('Thêm tài khoản trước');const pid=prompt('ID tài khoản nhận tracking',String(data.profiles[0].id));if(!pid)return;const link=await api('/api/links',{product_id:p.id,profile_id:Number(pid),platform:p.shopee_link?'shopee':'tiktok'});line(el,link.url);});
  }return el;});
  list('#caption-list',data.captions,c=>{const el=card(c.name,`${c.variants.length} biến thể`,'text');c.variants.forEach(v=>el.append(node('pre',v)));line(el,c.hashtags.join(' '));return el;});
  list('#schedule-list',data.schedules,s=>{const el=card(profileName(s.profile_id),s.enabled?'Đã bật':'Đã tắt','calendar',s.enabled?'active':'paused');line(el,`${s.times.join(', ')} · ${s.timezone}`);line(el,`Ngày: ${s.weekdays.map(d=>['T2','T3','T4','T5','T6','T7','CN'][d]).join(', ')} · Lệch: 0–${s.jitter_minutes} phút`);line(el,`Tối đa ${s.daily_limit} bài/ngày · ${s.require_approval?'Cần duyệt':'Tự động'}`);if(me.role==='admin')button(el,s.enabled?'Tắt lịch':'Bật lịch',async()=>{await api('/api/schedules',{...s,enabled:!s.enabled});await refresh();});return el;});
  list('#job-list',data.jobs,j=>{const el=card(`${profileName(j.profile_id)} · Bài #${j.id}`,state(j.status),'layers',j.status);line(el,date(j.scheduled));el.append(node('pre',j.caption));if(j.error)line(el,`Lỗi: ${j.error}`);if(j.remote_id)line(el,`Mã nền tảng: ${j.remote_id}`);if(me.role!=='viewer'){
    if(j.status==='pending')button(el,'Duyệt đăng',async()=>{const review=await api(`/api/jobs/${j.id}/review`);if(review.requires_acknowledgment&&!confirm(review.warnings.join('\n')+'\nBạn đã kiểm tra và xác nhận nội dung?'))return;await api(`/api/jobs/${j.id}/approve`,{acknowledged:true});await refresh();});
    if(['pending','queued'].includes(j.status))button(el,'Hủy',async()=>{await api(`/api/jobs/${j.id}/cancel`,{});await refresh();},'danger');
    if(j.status==='manual_link')button(el,'Đã gắn Shop link',async()=>{await api(`/api/jobs/${j.id}/shop-linked`,{});await refresh();});
    if(j.status==='processing')line(el,'Đang chờ nền tảng xử lý. Quá thời hạn sẽ chuyển sang cần đối soát; không tự đăng lại.');
    if(j.status==='uncertain'){
      line(el,'Mở đúng tài khoản trên nền tảng và kiểm tra bài trước khi xác nhận. Chọn chưa đăng sẽ đưa bài về chờ duyệt, không gửi lại ngay.');
      const form=node('form',undefined,'fields');form.dataset.resolveJob=String(j.id);
      const outcomeLabel=node('label','Kết quả kiểm tra');const outcome=node('select');outcome.name='outcome';outcome.required=true;
      for(const [value,text] of [['','Chọn kết quả'],['published','Đã kiểm tra: đã đăng'],['not_published','Đã kiểm tra: chưa đăng']]){const option=node('option',text);option.value=value;outcome.append(option);}outcomeLabel.append(outcome);
      const remoteLabel=node('label','ID bài/video đã kiểm tra');const remote=node('input');remote.name='remote_id';remote.maxLength=200;remoteLabel.append(remote);remoteLabel.hidden=true;
      outcome.addEventListener('change',()=>{remote.required=outcome.value==='published';remoteLabel.hidden=outcome.value!=='published';});
      const confirmedLabel=node('label','Tôi đã kiểm tra trực tiếp trên nền tảng');const confirmed=node('input');confirmed.type='checkbox';confirmed.name='confirmed';confirmed.required=true;confirmedLabel.prepend(confirmed);
      const submit=node('button','Lưu đối soát');submit.type='submit';form.append(outcomeLabel,remoteLabel,confirmedLabel,submit);
      form.addEventListener('submit',async e=>{e.preventDefault();submit.disabled=true;try{const body={outcome:outcome.value,confirmed:confirmed.checked};if(outcome.value==='published')body.remote_id=remote.value.trim();await api(`/api/jobs/${j.id}/resolve`,body);toast(outcome.value==='published'?'Đã ghi nhận bài đã đăng':'Đã đưa về chờ duyệt lại');await refresh();}catch(err){toast(err.message);}finally{submit.disabled=false;}});el.append(form);
    }
    button(el,'Lịch sử đối soát',async()=>{const history=await api(`/api/jobs/${j.id}/resolutions`);if(!history.length)line(el,'Chưa có đối soát.');for(const r of history)line(el,`${date(r.created)} · ${r.username} · ${r.outcome==='published'?'Đã đăng':'Chưa đăng'}`);});
  }return el;});
  list('#event-list',data.events,e=>{const el=node('article');el.append(node('span',e.kind,'badge'));line(el,e.message);line(el,`${date(e.created)} · ${e.profile_id?profileName(e.profile_id):'Hệ thống'}`);return el;});
  rights();tab(activeTab,false);
}
function bindForm(selector,action) { $(selector).addEventListener('submit',async e=>{e.preventDefault();const form=e.currentTarget,b=form.querySelector('button[type=submit],button:not([type])');b.disabled=true;try{await action(Object.fromEntries(new FormData(form)),form);if(selector!=='#login-form' && selector!=='#totp-setup' && selector!=='#totp-enable'){form.reset();if(selector==='#media-form')fileLabel();delete form.dataset.editId;toast('Đã lưu');await refresh();}}catch(err){if(selector==='#login-form')$('#login-error').textContent=err.message;else toast(err.message);}finally{b.disabled=false;}}); }
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
$('#nav').addEventListener('click',e=>{const target=e.target.closest('button[data-tab]');if(target)tab(target.dataset.tab);});
$$('[data-go]').forEach(b=>b.addEventListener('click',()=>tab(b.dataset.go)));
$('#new-post').addEventListener('click',()=>{tab('jobs');$('#job-form').scrollIntoView({behavior:'smooth',block:'center'});});
$('#open-nav').addEventListener('click',()=>setNavigation(true));
for(const id of ['close-nav','nav-backdrop'])$('#'+id).addEventListener('click',()=>{$('#open-nav').focus();setNavigation(false);});
document.addEventListener('keydown',e=>{
  if(!document.body.classList.contains('nav-open'))return;
  if(e.key==='Escape'){setNavigation(false);return;}
  if(e.key==='Tab'){
    const targets=[...$('#sidebar').querySelectorAll('a[href],button:not([disabled])')].filter(el=>el.getClientRects().length),first=targets[0],last=targets.at(-1);
    if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
  }
});
window.addEventListener('resize',()=>{if(window.innerWidth>900)setNavigation(false);else $('#sidebar').inert=!document.body.classList.contains('nav-open');});
setNavigation(false);
$('#toggle-password').addEventListener('click',()=>{const input=$('#login-form [name=password]'),visible=input.type==='password';input.type=visible?'text':'password';$('#toggle-password').setAttribute('aria-label',visible?'Ẩn mật khẩu':'Hiện mật khẩu');$('#toggle-password').setAttribute('aria-pressed',String(visible));});
const uploadInput=$('#media-form [name=file]');
function fileLabel(){$('#upload-file-name').textContent=uploadInput.files[0]?.name||'Chọn video hoặc kéo thả vào đây';}
uploadInput.addEventListener('change',fileLabel);
for(const type of ['dragenter','dragover'])$('#dropzone').addEventListener(type,e=>{e.preventDefault();$('#dropzone').classList.add('is-dragging');});
for(const type of ['dragleave','drop'])$('#dropzone').addEventListener(type,e=>{e.preventDefault();$('#dropzone').classList.remove('is-dragging');if(type==='drop'&&e.dataTransfer.files.length){const transfer=new DataTransfer();transfer.items.add(e.dataTransfer.files[0]);uploadInput.files=transfer.files;fileLabel();}});
$('#refresh').addEventListener('click',()=>refresh().catch(e=>toast(e.message)));
$('#logout').addEventListener('click',async()=>{try{await api('/api/logout',{});showLogin();}catch(e){toast(e.message);}});
for(const [id,path] of [['scan','/api/media/scan'],['plan','/api/schedules/plan'],['tick','/api/worker/tick']])$('#'+id).addEventListener('click',async()=>{try{const r=await api(path,{});toast(JSON.stringify(r));await refresh();}catch(e){toast(e.message);}});
$('#pause').addEventListener('click',async()=>{try{await api('/api/system/pause',{paused:!paused});await refresh();}catch(e){toast(e.message);}});
$('#csv').addEventListener('change',async e=>{const file=e.target.files[0];if(!file)return;try{const r=await fetch('/api/products/import',{method:'POST',headers:{'X-Requested-With':'FBTT'},body:await file.text()});const body=await r.json();if(!r.ok)throw Error(body.detail);toast(`Đã nhập ${body.imported} sản phẩm`);await refresh();}catch(err){toast(err.message);}e.target.value='';});
$('#backup').addEventListener('click',async()=>{try{const r=await fetch('/api/backups',{method:'POST',headers:{'X-Requested-With':'FBTT'}});if(!r.ok)throw Error('Sao lưu thất bại');const url=URL.createObjectURL(await r.blob());const a=node('a');a.href=url;a.download='fbtt-backup.tar.gz';a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);}catch(e){toast(e.message);}});
async function start(){
  me=await api('/api/me');await refresh();$('#identity').textContent=me.username;
  $('#user-role').textContent={admin:'Quản trị viên',publisher:'Người xuất bản',viewer:'Chỉ xem'}[me.role]||me.role;
  for(const avatar of $$('.user-avatar'))avatar.textContent=me.username.slice(0,1).toUpperCase();
  $('#login').hidden=true;$('#workspace').hidden=false;
}
start().catch(showLogin);
