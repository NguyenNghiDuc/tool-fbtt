const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const {spawn}=require('node:child_process');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
  const server=spawn('python',['-m','tests.browser_server'],{stdio:['ignore','ignore','inherit']});
  let browser;
  try{
    for(let i=0;i<60;i++){try{const r=await fetch('http://127.0.0.1:8765/health');if(r.ok)break;}catch{}await new Promise(r=>setTimeout(r,250));}
    browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
    const page=await browser.newPage({viewport:{width:1440,height:1000},timezoneId:'Asia/Ho_Chi_Minh',reducedMotion:'reduce'});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    async function goTab(name){
      if(await page.locator('#open-nav').isVisible()&&await page.locator('#open-nav').getAttribute('aria-expanded')==='false')await page.locator('#open-nav').click();
      await page.locator(`[data-tab=${name}]`).click();
    }

    await page.goto('http://127.0.0.1:8765');
    fs.mkdirSync('/tmp/fbtt-evidence',{recursive:true});
    await page.screenshot({path:'/tmp/fbtt-evidence/login-desktop.png',fullPage:true});
    await page.locator('#login-form [name=username]').fill('admin');
    await page.locator('#login-form [name=password]').fill('browser-test-password');
    await page.locator('#toggle-password').click();
    assert.equal(await page.locator('#login-form [name=password]').getAttribute('type'),'text');
    await page.locator('#toggle-password').click();
    assert.equal(await page.locator('#login-form [name=password]').getAttribute('type'),'password');
    await page.locator('#login-form button[type=submit]').click();
    await page.locator('#workspace').waitFor({state:'visible'});
    await goTab('profiles');
    await page.locator('#profile-form [name=name]').fill('Shop kiểm thử');
    await page.locator('#profile-form [name=platform]').selectOption('tiktok');
    await page.locator('#profile-form button').click();
    await page.getByRole('heading',{name:'Shop kiểm thử',exact:true}).waitFor();
    await goTab('products');
    await page.locator('#product-form [name=name]').fill('Áo kiểm thử');
    await page.locator('#product-form [name=price]').fill('99000');
    await page.locator('#product-form [name=tiktok_link]').fill('https://shop.tiktok.com/test');
    await page.locator('#product-form button').click();
    await page.getByRole('heading',{name:'Áo kiểm thử',exact:true}).waitFor();
    await goTab('captions');
    await page.locator('#caption-form [name=name]').fill('Caption test');
    await page.locator('#caption-form [name=variants]').fill('Mua {ten_san_pham} {gia} {link}\nKhám phá {ten_san_pham}');
    await page.locator('#caption-form button').click();
    await page.getByRole('heading',{name:'Caption test',exact:true}).waitFor();
    const media=path.join('/tmp','fbtt-browser-video.mp4');
    require('node:child_process').execFileSync('ffmpeg',['-v','error','-y','-f','lavfi','-i','color=c=blue:s=180x320:d=1','-c:v','libx264',media]);
    await goTab('media');
    await page.locator('#media-form input').setInputFiles(media);
    assert.equal(await page.locator('#upload-file-name').textContent(),'fbtt-browser-video.mp4');
    await page.evaluate(({bytes})=>{
      const file=new File([Uint8Array.from(atob(bytes),c=>c.charCodeAt(0))],'fbtt-browser-video.mp4',{type:'video/mp4'});
      const transfer=new DataTransfer();transfer.items.add(file);
      document.querySelector('#dropzone').dispatchEvent(new DragEvent('drop',{bubbles:true,dataTransfer:transfer}));
    },{bytes:fs.readFileSync(media).toString('base64')});
    await page.locator('#media-form button').click();
    await page.getByRole('heading',{name:'fbtt-browser-video.mp4',exact:true}).waitFor();
    await page.getByRole('button',{name:'Gán tài khoản',exact:true}).click();
    await page.getByText('Shop kiểm thử: chưa dùng',{exact:true}).waitFor();
    await goTab('jobs');
    await page.locator('#job-form [name=scheduled]').fill('2026-12-01T12:00');
    await page.locator('#job-form button').click();
    await page.getByRole('button',{name:'Duyệt đăng',exact:true}).waitFor();
    await page.getByRole('button',{name:'Duyệt đăng',exact:true}).click();
    await page.locator('#job-list .badge').filter({hasText:'Đã duyệt'}).waitFor();
    const jobs=await (await page.request.get('http://127.0.0.1:8765/api/jobs')).json();
    const jid=jobs[0].id;
    async function injectTimeout(){
      const r=await page.request.post(`http://127.0.0.1:8765/__test/jobs/${jid}/uncertain`,{headers:{'X-Requested-With':'FBTT'}});
      assert.equal(r.status(),200);
      await page.locator('#refresh').click();
      await page.locator(`[data-resolve-job="${jid}"]`).waitFor();
    }
    await injectTimeout();
    let resolution=page.locator(`[data-resolve-job="${jid}"]`);
    await resolution.locator('[name=outcome]').selectOption('not_published');
    await resolution.locator('[name=confirmed]').check();
    await resolution.getByRole('button',{name:'Lưu đối soát'}).click();
    await page.locator('#job-list .badge').filter({hasText:'Chờ duyệt'}).waitFor();
    assert.equal((await (await page.request.get('http://127.0.0.1:8765/api/jobs')).json())[0].status,'pending');
    await page.getByRole('button',{name:'Duyệt đăng',exact:true}).click();
    await page.locator('#job-list .badge').filter({hasText:'Đã duyệt'}).waitFor();
    await injectTimeout();
    resolution=page.locator(`[data-resolve-job="${jid}"]`);
    await resolution.locator('[name=outcome]').selectOption('published');
    await resolution.locator('[name=remote_id]').fill('verified-video-123');
    await resolution.locator('[name=confirmed]').check();
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true,'Reconciliation form mobile overflow');
    fs.mkdirSync('/tmp/fbtt-evidence',{recursive:true});
    await page.screenshot({path:'/tmp/fbtt-evidence/reconciliation.png',fullPage:true});
    await resolution.getByRole('button',{name:'Lưu đối soát'}).click();
    await page.locator('#job-list .badge').filter({hasText:'Chờ gắn Shop link'}).waitFor();
    await page.getByRole('button',{name:'Lịch sử đối soát',exact:true}).click();
    await page.getByText(/admin · Đã đăng/).waitFor();
    const history=await (await page.request.get(`http://127.0.0.1:8765/api/jobs/${jid}/resolutions`)).json();
    assert.equal(history.length,2);
    await page.setViewportSize({width:1440,height:1000});
    await goTab('settings');
    await page.locator('#pause').click();
    await page.getByText('Hệ thống đang tạm dừng.',{exact:false}).waitFor();
    await page.locator('#toast').waitFor({state:'hidden'});
    await page.setViewportSize({width:390,height:844});
    await goTab('overview');
    await page.waitForTimeout(100);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true,'Mobile overflow');
    fs.mkdirSync('/tmp/fbtt-evidence',{recursive:true});
    await page.screenshot({path:'/tmp/fbtt-evidence/mobile.png',fullPage:true});
    await page.setViewportSize({width:1440,height:1000});
    await page.screenshot({path:'/tmp/fbtt-evidence/desktop.png',fullPage:true});
    for(const width of [1440,390,320]){
      await page.setViewportSize({width,height:1000});
      for(const name of ['overview','profiles','media','products','captions','schedules','jobs','events','settings']){
        await goTab(name);
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true,`Overflow: ${name} @ ${width}`);
        await page.screenshot({path:`/tmp/fbtt-evidence/${name}-${width}.png`,fullPage:true});
      }
    }
    // The drawer closes with Escape and returns focus to its trigger.
    await page.locator('#open-nav').click();
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#open-nav').getAttribute('aria-expanded'),'false');
    await page.setViewportSize({width:1440,height:1000});
    assert.deepEqual(errors,[]);
    await page.locator('#logout').click();
    await page.locator('#login').waitFor({state:'visible'});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:'/tmp/fbtt-evidence/login-mobile.png',fullPage:true});
    fs.unlinkSync(media);
    console.log('PASS browser: login → profile → product → caption → upload → assign → preview/approve → reconcile not-published/published + audit → pause → 9 pages at 1440/390/320px → drawer keyboard + password toggle + file drop → logout; no JS errors');
  }finally{if(browser)await browser.close();server.kill('SIGTERM');}
})().catch(e=>{console.error(e);process.exitCode=1});
