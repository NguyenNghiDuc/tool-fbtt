import tempfile
import time
import unittest
from urllib.parse import parse_qs, urlparse

import httpx
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.main import create_app


class ProfilesFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.calls = []
        self.revoked = False
        def handler(request):
            self.calls.append(request)
            if self.revoked:
                return httpx.Response(401, json={'error': 'secret-do-not-leak'})
            if request.url.path == '/v2/oauth/token/':
                return httpx.Response(200, json={'open_id': 'tt-user', 'access_token': 'access-secret',
                                                'refresh_token': 'refresh-secret', 'expires_in': 172800})
            if request.url.path.endswith('/me/accounts'):
                return httpx.Response(200, json={'data': [{'id': '123', 'access_token': 'page-secret'}]})
            return httpx.Response(200, json={'access_token': 'fb-secret', 'expires_in': 5000000})
        self.app = create_app({'DATA_DIR': self.tmp.name, 'ADMIN_PASSWORD': 'test-password-123',
                               'ENCRYPTION_KEY': Fernet.generate_key().decode(),
                               'FACEBOOK_CLIENT_ID': 'fb', 'FACEBOOK_CLIENT_SECRET': 'fb-client-secret',
                               'TIKTOK_CLIENT_ID': 'tt', 'TIKTOK_CLIENT_SECRET': 'tt-client-secret'},
                              transport=httpx.MockTransport(handler), background=False)
        self.client = TestClient(self.app, headers={'X-Requested-With': 'FBTT'})
        self.login()

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def login(self, username='admin', password='test-password-123'):
        result = self.client.post('/api/login', json={'username': username, 'password': password})
        self.assertEqual(result.status_code, 200, result.text)

    def profile(self, platform='tiktok', **kwargs):
        body = {'name': 'Shop', 'platform': platform, **kwargs}
        result = self.client.post('/api/profiles', json=body)
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()

    def authorize(self, p):
        start = self.client.post(f'/api/profiles/{p["id"]}/oauth')
        self.assertEqual(start.status_code, 200, start.text)
        state = parse_qs(urlparse(start.json()['url']).query)['state'][0]
        result = self.client.get(f'/oauth/{p["platform"]}/callback', params={'state': state, 'code': 'abc'}, follow_redirects=False)
        return state, result


class ProfilesTest(ProfilesFixture):
    def test_profile_crud_groups_and_validation(self):
        p = self.profile('facebook', external_id='123', niche='fashion', notes='owner', color='#abcdef')
        self.assertEqual(len(self.client.get('/api/profiles?niche=fashion').json()), 1)
        self.assertNotIn('access_token', p)
        self.assertEqual(self.client.post('/api/profiles', json={'name': 'x', 'platform': 'bad'}).status_code, 422)
        self.assertEqual(self.client.post('/api/profiles', json={'name': 'x', 'platform': 'facebook'}).status_code, 422)
        self.assertEqual(self.client.post('/api/profiles', json={'name': 'x', 'platform': 'facebook', 'external_id': '123'}).status_code, 409)
        body = {k: p[k] for k in ('name', 'platform', 'external_id', 'niche', 'notes', 'color', 'status')}
        body.update(name='New', status='restricted')
        self.assertEqual(self.client.put(f'/api/profiles/{p["id"]}', json=body).json()['status'], 'restricted')
        self.assertEqual(self.client.delete(f'/api/profiles/{p["id"]}').status_code, 200)
        self.assertEqual(self.client.get('/api/profiles').json(), [])

    def test_roles_sessions_and_csrf(self):
        for role in ('viewer', 'publisher'):
            self.assertEqual(self.client.post('/api/users', json={'username': role, 'password': 'role-password-123', 'role': role}).status_code, 201)
        self.client.post('/api/logout')
        self.assertEqual(self.client.get('/api/profiles').status_code, 401)
        self.login('viewer', 'role-password-123')
        self.assertEqual(self.client.get('/api/profiles').status_code, 200)
        self.assertEqual(self.client.post('/api/profiles', json={'name': 'x', 'platform': 'tiktok'}).status_code, 403)
        self.assertEqual(self.client.get('/api/users').status_code, 403)
        self.client.headers.pop('X-Requested-With')
        self.assertEqual(self.client.post('/api/logout').status_code, 403)

    def test_tiktok_oauth_encryption_and_state_replay(self):
        p = self.profile()
        state, result = self.authorize(p)
        self.assertEqual(result.status_code, 303, result.text)
        row = self.app.state.db.query('SELECT * FROM profiles')[0]
        self.assertNotIn('access-secret', row['access_token'])
        self.assertEqual(self.app.state.cipher.decrypt(row['access_token'].encode()), b'access-secret')
        self.assertNotIn('secret', self.client.get('/api/profiles').text)
        self.assertEqual(self.client.get('/oauth/tiktok/callback', params={'state': state, 'code': 'abc'}).status_code, 400)
        self.assertEqual(self.client.get('/oauth/tiktok/callback', params={'state': 'fake', 'code': 'abc'}).status_code, 400)

    def test_facebook_page_oauth(self):
        p = self.profile('facebook', external_id='123')
        _, response = self.authorize(p)
        self.assertEqual(response.status_code, 303)
        row = self.app.state.db.query('SELECT * FROM profiles')[0]
        self.assertEqual(self.app.state.cipher.decrypt(row['access_token'].encode()), b'page-secret')

    def test_refresh_and_revocation_redacted(self):
        p = self.profile()
        self.authorize(p)
        self.app.state.db.execute('UPDATE profiles SET expires=?', (int(time.time()) + 60,))
        self.assertEqual(self.client.post('/api/tokens/refresh').status_code, 200)
        self.assertGreater(self.app.state.db.query('SELECT expires FROM profiles')[0]['expires'], time.time() + 86400)
        self.app.state.db.execute('UPDATE profiles SET expires=?', (int(time.time()) + 60,))
        self.revoked = True
        self.client.post('/api/tokens/refresh')
        self.assertEqual(self.client.get('/api/profiles').json()[0]['token_status'], 'revoked')
        self.assertNotIn('secret-do-not-leak', self.client.get('/api/events').text)

    def test_missing_configuration_and_login_rate_limit(self):
        self.app.state.providers.settings.pop('TIKTOK_CLIENT_SECRET')
        p = self.profile()
        self.assertEqual(self.client.post(f'/api/profiles/{p["id"]}/oauth').status_code, 503)
        for _ in range(10):
            self.assertEqual(self.client.post('/api/login', json={'username': 'admin', 'password': 'bad'}).status_code, 401)
        self.assertEqual(self.client.post('/api/login', json={'username': 'admin', 'password': 'bad'}).status_code, 429)



if __name__ == '__main__':
    unittest.main()
