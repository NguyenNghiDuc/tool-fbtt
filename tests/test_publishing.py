import time
import httpx
from .test_scheduling import SchedulingFixture

class PublishingFixture(SchedulingFixture):
    def setUp(self):
        super().setUp()
        self.app.state.cfg['PUBLISH_ENABLED'] = 'true'
        self.mode = 'ok'
        self.sent = []
        def handler(request):
            self.sent.append(request)
            if request.url.path.endswith('/me'):
                return httpx.Response(200, json={'id': '123'})
            if request.url.path.endswith('/videos'):
                if self.mode == 'rate':
                    return httpx.Response(429)
                if self.mode == 'timeout':
                    raise httpx.ReadTimeout('secret-token-in-url', request=request)
                return httpx.Response(200, json={'id': 'fb-post-1'})
            if 'creator_info' in request.url.path:
                return httpx.Response(200, json={'data': {'privacy_level_options': ['SELF_ONLY'], 'max_video_post_duration_sec': 60}})
            if '/video/init/' in request.url.path:
                return httpx.Response(200, json={'data': {'publish_id': 'tt-post-1', 'upload_url': 'https://open-upload.tiktokapis.com/upload'}})
            if '/status/fetch/' in request.url.path:
                return httpx.Response(200, json={'data': {'status': 'PUBLISH_COMPLETE'}})
            return httpx.Response(200, json={})
        self.app.state.providers.transport = httpx.MockTransport(handler)

    def ready(self, platform='facebook'):
        body = self.prepare()
        self.app.state.db.execute("UPDATE profiles SET platform=?,external_id='123',access_token=?,token_status='connected' WHERE id=?",
            (platform, self.app.state.cipher.encrypt(b'secret-access').decode(), body['profile_id']))
        body['scheduled'] = int(time.time()) - 1
        job = self.client.post('/api/jobs', json=body).json()
        self.client.post(f'/api/jobs/{job["id"]}/approve', json={})
        return job


class PublishingTest(PublishingFixture):
    def test_facebook_publish_pause_no_duplicate(self):
        job = self.ready()
        self.client.post('/api/system/pause', json={'paused': True})
        self.assertEqual(self.client.post('/api/worker/tick').json()['claimed'], 0)
        self.client.post('/api/system/pause', json={'paused': False})
        self.assertEqual(self.client.post('/api/worker/tick').json()['claimed'], 1)
        self.assertEqual(self.client.get('/api/jobs').json()[0]['status'], 'success')
        self.assertEqual(self.client.post('/api/worker/tick').json()['claimed'], 0)
        self.assertEqual(len([r for r in self.sent if r.url.path.endswith('/videos')]), 1)
        self.assertEqual(self.app.state.db.query('SELECT used FROM assignments')[0]['used'], 1)

    def test_bounded_rate_limit_retry(self):
        self.ready()
        self.mode = 'rate'
        for _ in range(3):
            self.app.state.db.execute('UPDATE jobs SET scheduled=?', (int(time.time())-1,))
            self.client.post('/api/worker/tick')
        row = self.client.get('/api/jobs').json()[0]
        self.assertEqual(row['status'], 'failed')
        self.assertEqual(row['attempts'], 3)

    def test_ambiguous_timeout_is_not_reposted_or_leaked(self):
        self.ready()
        self.mode = 'timeout'
        self.client.post('/api/worker/tick')
        row = self.client.get('/api/jobs').json()[0]
        self.assertEqual(row['status'], 'uncertain')
        self.assertNotIn('secret-token', self.client.get('/api/events').text)
        self.assertEqual(self.client.post('/api/worker/tick').json()['claimed'], 0)

    def test_tiktok_processing_then_manual_shop_link(self):
        job = self.ready('tiktok')
        self.client.post('/api/worker/tick')
        self.assertEqual(self.client.get('/api/jobs').json()[0]['status'], 'processing')
        self.client.post('/api/worker/tick')
        self.assertEqual(self.client.get('/api/jobs').json()[0]['status'], 'manual_link')
        self.assertEqual(self.client.post(f'/api/jobs/{job["id"]}/shop-linked').status_code, 200)
        init = next(r for r in self.sent if '/video/init/' in r.url.path)
        self.assertIn(b'SELF_ONLY', init.content)


    def test_one_profile_failure_does_not_block_another(self):
        first = self.ready('facebook')
        p = self.profile(status='active')
        self.client.post(f'/api/media/{first["media_id"]}/assign',json={'profile_ids':[p['id']]})
        second = self.client.post('/api/jobs',json={'profile_id':p['id'],'media_id':first['media_id'],
            'product_id':first['product_id'],'caption_id':first['caption_id'],'scheduled':int(time.time())-1}).json()
        self.client.post(f'/api/jobs/{second["id"]}/approve',json={'acknowledged':True})
        self.assertEqual(self.client.post('/api/worker/tick').json()['claimed'],2)
        rows = {r['id']:r for r in self.client.get('/api/jobs').json()}
        self.assertEqual(rows[first['id']]['status'],'success')
        self.assertEqual(rows[second['id']]['status'],'failed')

    def test_daily_limit_blocks_third_post(self):
        first = self.ready()
        self.client.post('/api/worker/tick')
        for index in (2,3):
            source = self.app.state.db.query('SELECT * FROM media')[0]
            mid = self.app.state.db.execute('INSERT INTO media(name,path,hash,metadata,created) VALUES (?,?,?,?,?)',
                ('test'+str(index),source['path'],str(index),source['metadata'],int(time.time())))
            self.client.post(f'/api/media/{mid}/assign',json={'profile_ids':[first['profile_id']]})
            job = self.client.post('/api/jobs',json={'profile_id':first['profile_id'],'media_id':mid,
                'product_id':first['product_id'],'caption_id':first['caption_id'],'scheduled':int(time.time())-1}).json()
            self.client.post(f'/api/jobs/{job["id"]}/approve',json={})
            response = self.client.post('/api/worker/tick').json()
            self.assertEqual(response['claimed'],1 if index==2 else 0)

    def test_network_connect_retry_and_atomic_claim(self):
        self.ready()
        def fail(request):
            raise httpx.ConnectError('sensitive detail',request=request)
        self.app.state.providers.transport = httpx.MockTransport(fail)
        self.client.post('/api/worker/tick')
        self.assertEqual(self.client.get('/api/jobs').json()[0]['status'],'queued')
        self.app.state.db.execute('UPDATE jobs SET scheduled=?',(int(time.time())-1,))
        self.assertEqual(len(self.app.state.claim(int(time.time()))),1)
        self.assertEqual(len(self.app.state.claim(int(time.time()))),0)
