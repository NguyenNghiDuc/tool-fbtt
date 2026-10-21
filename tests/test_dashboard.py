import time
from unittest.mock import patch
from app.security import totp
from .test_profiles import ProfilesFixture

class DashboardTest(ProfilesFixture):
    def test_dashboard_static_and_security_headers(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('lang="vi"', r.text)
        self.assertIn("frame-ancestors 'none'", r.headers['content-security-policy'])
        self.assertEqual(self.client.get('/static/app.js').status_code, 200)
    def test_2fa_enrollment_login_and_replay_protection(self):
        response = self.client.post('/api/2fa/setup', json={'password':'test-password-123'})
        self.assertEqual(response.status_code, 200, response.text)
        secret = response.json()['secret']
        code = totp(secret)
        self.assertEqual(self.client.post('/api/2fa/enable', json={'otp': code}).status_code, 200)
        self.client.post('/api/logout')
        self.assertEqual(self.client.post('/api/login', json={'username':'admin','password':'test-password-123'}).status_code, 401)
        self.assertEqual(self.client.post('/api/login', json={'username':'admin','password':'test-password-123','otp':code}).status_code, 401)
        future = (int(time.time())//30+2)*30
        with patch('time.time',return_value=future):
            r = self.client.post('/api/login', json={'username':'admin','password':'test-password-123','otp':totp(secret,future)})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn(secret, self.client.get('/api/me').text)
