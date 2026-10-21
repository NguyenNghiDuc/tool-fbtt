from .test_publishing import PublishingFixture

class ComplianceTest(PublishingFixture):
    def test_claim_warning_requires_acknowledgment(self):
        body = self.prepare()
        job = self.client.post('/api/jobs',json=body).json()
        self.app.state.db.execute('UPDATE jobs SET caption=? WHERE id=?', ('Cam kết chữa khỏi bệnh 100% #quảngcáo',job['id']))
        self.assertTrue(self.client.get(f'/api/jobs/{job["id"]}/review').json()['requires_acknowledgment'])
        self.assertEqual(self.client.post(f'/api/jobs/{job["id"]}/approve',json={}).status_code,409)
        self.assertEqual(self.client.post(f'/api/jobs/{job["id"]}/approve',json={'acknowledged':True}).status_code,200)
    def test_duplicate_media_warning(self):
        body = self.prepare()
        p = self.profile()
        self.client.post(f'/api/media/{body["media_id"]}/assign',json={'profile_ids':[p['id']]})
        job = self.client.post('/api/jobs',json=body).json()
        self.assertTrue(self.client.get(f'/api/jobs/{job["id"]}/review').json()['requires_acknowledgment'])
