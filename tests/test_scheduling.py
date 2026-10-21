import time
from datetime import datetime
from zoneinfo import ZoneInfo
from .test_commerce import CommerceFixture

class SchedulingFixture(CommerceFixture):
    def prepare(self):
        p = self.profile(status='active')
        mid = self.upload().json()['id']
        self.client.post(f'/api/media/{mid}/assign', json={'profile_ids': [p['id']]})
        product = self.product()
        caption = self.client.post('/api/captions', json={'name': 'sale', 'variants': ['Buy {ten_san_pham} {link}']}).json()
        return dict(profile_id=p['id'], media_id=mid, product_id=product['id'], caption_id=caption['id'], scheduled=int(time.time()) + 60)


class SchedulingTest(SchedulingFixture):
    def test_approval_reservation_cancel_and_move(self):
        body = self.prepare()
        r = self.client.post('/api/jobs', json=body)
        self.assertEqual(r.status_code, 201, r.text)
        job = r.json()
        self.assertEqual(job['status'], 'pending')
        self.assertEqual(self.client.post('/api/jobs', json=body).status_code, 409)
        self.assertEqual(self.client.put(f'/api/jobs/{job["id"]}/time', json={'scheduled': body['scheduled']+600}).status_code, 200)
        self.assertEqual(self.client.post(f'/api/jobs/{job["id"]}/approve', json={}).json()['status'], 'queued')
        self.assertEqual(self.client.post(f'/api/jobs/{job["id"]}/approve', json={}).status_code, 409)
        self.assertEqual(self.client.post(f'/api/jobs/{job["id"]}/cancel').json()['status'], 'cancelled')
        self.assertEqual(self.client.post('/api/jobs', json=body).status_code, 201)

    def test_planner_idempotence_pause_and_validation(self):
        body = self.prepare()
        schedule = {k: body[k] for k in ('profile_id','product_id','caption_id')}
        schedule.update(times=['15:00'], jitter_minutes=10)
        self.assertEqual(self.client.post('/api/schedules', json=schedule).status_code, 201)
        now = int(datetime(2026,10,21,8,0,tzinfo=ZoneInfo('Asia/Ho_Chi_Minh')).timestamp())
        self.client.post('/api/system/pause', json={'paused': True})
        self.assertEqual(self.app.state.plan(now), [])
        self.client.post('/api/system/pause', json={'paused': False})
        jobs = self.app.state.plan(now)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['status'], 'pending')
        self.assertEqual(self.app.state.plan(now), [])
        schedule['times'] = ['25:70']
        self.assertEqual(self.client.post('/api/schedules', json=schedule).status_code, 422)

    def test_viewer_cannot_publish(self):
        body = self.prepare()
        self.client.post('/api/users', json={'username':'viewer','password':'viewer-password-123','role':'viewer'})
        self.client.post('/api/logout')
        self.login('viewer','viewer-password-123')
        self.assertEqual(self.client.post('/api/jobs', json=body).status_code, 403)
