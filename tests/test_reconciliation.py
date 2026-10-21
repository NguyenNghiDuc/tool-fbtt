import time
import httpx
from .test_publishing import PublishingFixture


class ReconciliationTest(PublishingFixture):
    def uncertain(self, platform='facebook'):
        job = self.ready(platform)
        self.app.state.db.execute("UPDATE jobs SET status='uncertain',error='network_outcome_unknown',remote_id='old-reference',started=? WHERE id=?", (int(time.time()), job['id']))
        return job

    def resolve(self, job, outcome='not_published', **values):
        return self.client.post(f'/api/jobs/{job["id"]}/resolve', json={
            'outcome': outcome, 'confirmed': True, **values})

    def test_verified_published_releases_profile_without_reposting(self):
        job = self.uncertain()
        result = self.resolve(job, 'published', remote_id='verified-post-123')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['status'], 'success')
        self.assertEqual(result.json()['remote_id'], 'verified-post-123')
        self.assertEqual(self.app.state.db.query('SELECT used FROM assignments')[0]['used'], 1)
        self.assertEqual(self.client.post('/api/worker/tick').json()['claimed'], 0)
        history = self.client.get(f'/api/jobs/{job["id"]}/resolutions').json()
        self.assertEqual(history[0]['username'], 'admin')
        self.assertEqual(history[0]['previous_remote_id'], 'old-reference')
        self.assertEqual(history[0]['previous_error'], 'network_outcome_unknown')
        # The daily limit still counts the verified published job.
        self.assertIsNotNone(result.json()['started'])
        self.assertEqual(self.resolve(job, 'published', remote_id='verified-post-123').status_code, 409)

    def test_verified_not_published_requires_fresh_approval(self):
        job = self.uncertain()
        result = self.resolve(job)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['status'], 'pending')
        self.assertIsNone(result.json()['remote_id'])
        self.assertIsNone(result.json()['started'])
        self.assertEqual(self.app.state.db.query('SELECT used FROM assignments')[0]['used'], 0)
        self.assertEqual(self.client.post('/api/worker/tick').json()['claimed'], 0)
        duplicate = {k: job[k] for k in ('profile_id','media_id','product_id','caption_id','scheduled')}
        self.assertEqual(self.client.post('/api/jobs', json=duplicate).status_code, 409)
        self.assertEqual(self.client.post(f'/api/jobs/{job["id"]}/approve', json={}).status_code, 200)
        self.assertEqual(self.client.post('/api/worker/tick').json()['claimed'], 1)
        self.assertEqual(self.client.get('/api/jobs').json()[0]['status'], 'success')

    def test_verification_fields_and_state_are_required(self):
        job = self.uncertain()
        url = f'/api/jobs/{job["id"]}/resolve'
        self.assertEqual(self.client.post(url, json={'outcome':'not_published'}).status_code, 422)
        self.assertEqual(self.resolve(job, 'published').status_code, 422)
        self.assertEqual(self.resolve(job, 'published', remote_id='https://example.com/token=secret').status_code, 422)
        self.assertEqual(self.resolve({'id':99999}).status_code, 404)
        self.app.state.db.execute("UPDATE jobs SET status='processing' WHERE id=?", (job['id'],))
        self.assertEqual(self.resolve(job).status_code, 409)
        self.assertEqual(self.client.get(f'/api/jobs/{job["id"]}/resolutions').json(), [])

    def test_tiktok_published_still_needs_manual_shop_link(self):
        job = self.uncertain('tiktok')
        self.assertEqual(self.resolve(job, 'published', remote_id='video123').json()['status'], 'manual_link')
        self.assertEqual(self.client.post(f'/api/jobs/{job["id"]}/shop-linked').status_code, 200)

    def test_viewers_cannot_resolve_or_read_audit(self):
        job = self.uncertain()
        self.client.post('/api/users', json={'username':'viewer','password':'viewer-password-123','role':'viewer'})
        self.client.post('/api/logout')
        self.login('viewer', 'viewer-password-123')
        self.assertEqual(self.resolve(job).status_code, 403)
        self.assertEqual(self.client.get(f'/api/jobs/{job["id"]}/resolutions').status_code, 403)
        self.client.post('/api/logout')
        self.assertEqual(self.resolve(job).status_code, 401)

    def test_processing_deadline_survives_poll_failures_and_disabled_publisher(self):
        job = self.ready('tiktok')
        self.client.post('/api/worker/tick')
        self.app.state.providers.transport = httpx.MockTransport(lambda r: httpx.Response(500))
        self.client.post('/api/worker/tick')
        row = self.client.get('/api/jobs').json()[0]
        self.assertEqual(row['status'], 'processing')
        self.assertEqual(row['error'], 'platform_server_error')
        self.app.state.db.execute('UPDATE jobs SET processing_since=? WHERE id=?', (int(time.time())-1801,job['id']))
        self.app.state.cfg['PUBLISH_ENABLED'] = 'false'
        self.client.post('/api/system/pause', json={'paused':True})
        self.client.post('/api/worker/tick')
        row = self.client.get('/api/jobs').json()[0]
        self.assertEqual(row['status'], 'uncertain')
        self.assertEqual(row['error'], 'processing_timeout_check_platform')
        self.assertEqual(self.resolve(job).json()['status'], 'pending')
        self.assertEqual(len(self.app.state.db.query("SELECT * FROM events WHERE message LIKE '%processing_timeout_check_platform%'")), 1)

    def test_bad_poll_response_does_not_crash_tick_or_auto_retry(self):
        self.ready('tiktok')
        self.client.post('/api/worker/tick')
        self.app.state.providers.transport = httpx.MockTransport(lambda r: httpx.Response(200, json=['secret-never-log']))
        result = self.client.post('/api/worker/tick')
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['claimed'], 0)
        self.assertEqual(self.client.get('/api/jobs').json()[0]['status'], 'processing')
        self.assertNotIn('secret-never-log', self.client.get('/api/events').text)

    def test_late_poll_result_cannot_overwrite_manual_resolution(self):
        job = self.ready('tiktok')
        self.client.post('/api/worker/tick')
        def response(request):
            self.app.state.db.execute("UPDATE jobs SET status='pending',remote_id=NULL WHERE id=?", (job['id'],))
            return httpx.Response(200,json={'data':{'status':'PUBLISH_COMPLETE'}})
        self.app.state.providers.transport = httpx.MockTransport(response)
        self.client.post('/api/worker/tick')
        self.assertEqual(self.client.get('/api/jobs').json()[0]['status'], 'pending')
        self.assertEqual(self.app.state.db.query('SELECT used FROM assignments')[0]['used'], 0)

    def test_concurrent_resolutions_only_commit_one_decision(self):
        from concurrent.futures import ThreadPoolExecutor
        job = self.uncertain()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.resolve(job), range(2)))
        self.assertEqual(sorted(r.status_code for r in results), [200,409])
        self.assertEqual(len(self.client.get(f'/api/jobs/{job["id"]}/resolutions').json()), 1)

    def test_verified_posted_allows_next_video_to_be_claimed(self):
        job = self.uncertain()
        media = self.app.state.db.query('SELECT * FROM media WHERE id=?',(job['media_id'],))[0]
        mid = self.app.state.db.execute('INSERT INTO media(name,path,hash,metadata,created) VALUES (?,?,?,?,?)',
            ('next.mp4',media['path'],'next-video-hash',media['metadata'],int(time.time())))
        self.client.post(f'/api/media/{mid}/assign',json={'profile_ids':[job['profile_id']]})
        body = {k:job[k] for k in ('profile_id','product_id','caption_id','scheduled')}
        body['media_id'] = mid
        next_job = self.client.post('/api/jobs',json=body).json()
        self.client.post(f'/api/jobs/{next_job["id"]}/approve',json={})
        self.assertEqual(self.client.post('/api/worker/tick').json()['claimed'],0)
        self.resolve(job,'published',remote_id='confirmed-first-post')
        self.assertEqual(self.client.post('/api/worker/tick').json()['claimed'],1)
        statuses = {j['id']:j['status'] for j in self.client.get('/api/jobs').json()}
        self.assertEqual(statuses[next_job['id']],'success')

    def test_upgrade_preserves_existing_processing_job_and_deadline(self):
        from app.main import create_app
        job = self.ready('tiktok')
        self.client.post('/api/worker/tick')
        self.app.state.db.execute('UPDATE jobs SET started=? WHERE id=?',(int(time.time())-1801,job['id']))
        # Recreate the pre-upgrade schema, which had no processing_since column.
        self.app.state.db.execute('ALTER TABLE jobs DROP COLUMN processing_since')
        upgraded = create_app(self.app.state.cfg,background=False)
        restored = upgraded.state.db.query('SELECT * FROM jobs WHERE id=?',(job['id'],))[0]
        self.assertEqual(restored['status'],'processing')
        self.assertEqual(restored['remote_id'],'tt-post-1')
        upgraded.state.expire_processing()
        self.assertEqual(upgraded.state.db.query('SELECT status FROM jobs WHERE id=?',(job['id'],))[0]['status'],'uncertain')
