from fastapi.testclient import TestClient
from starlette.requests import Request
from app.client_ip import ClientAddresses
from app.main import create_app
from .test_profiles import ProfilesFixture


class ProxyTest(ProfilesFixture):
    def proxy_client(self, peer='10.0.0.2', trusted='10.0.0.2/32'):
        cfg = dict(self.app.state.cfg, TRUSTED_PROXY_CIDRS=trusted)
        app = create_app(cfg, background=False)
        return TestClient(app, client=(peer,1234), headers={'X-Requested-With':'FBTT'})

    def login_as(self, client, forwarded, password='bad'):
        return client.post('/api/login', headers={'X-Forwarded-For':forwarded},
            json={'username':'admin','password':password})

    def test_trusted_proxy_separates_client_login_buckets(self):
        with self.proxy_client() as client:
            for _ in range(10):
                self.assertEqual(self.login_as(client,'198.51.100.1').status_code,401)
            self.assertEqual(self.login_as(client,'198.51.100.1').status_code,429)
            result = self.login_as(client,'198.51.100.2','test-password-123')
            self.assertEqual(result.status_code,200,result.text)

    def test_untrusted_peer_cannot_spoof_forwarded_ip_to_bypass_limit(self):
        with self.proxy_client(peer='10.0.0.3') as client:
            for index in range(10):
                self.assertEqual(self.login_as(client,f'198.51.100.{index}').status_code,401)
            self.assertEqual(self.login_as(client,'203.0.113.1','test-password-123').status_code,429)

    def test_spoofed_prefix_is_ignored_across_trusted_proxy_chain(self):
        with self.proxy_client(trusted='10.0.0.0/24') as client:
            for index in range(10):
                self.assertEqual(self.login_as(client,f'203.0.113.{index}, 198.51.100.5, 10.0.0.1').status_code,401)
            self.assertEqual(self.login_as(client,'203.0.113.99, 198.51.100.5, 10.0.0.1').status_code,429)
            self.assertEqual(self.login_as(client,'198.51.100.6, 10.0.0.1','test-password-123').status_code,200)

    def test_malformed_duplicate_and_ipv6_headers(self):
        addresses = ClientAddresses('10.0.0.2/32,::1/128')
        def request(headers, peer='10.0.0.2'):
            return Request({'type':'http','client':(peer,1234),'headers':headers})
        self.assertEqual(addresses.ip(request([(b'x-forwarded-for',b'bad-ip')])), '10.0.0.2')
        self.assertEqual(addresses.ip(request([(b'x-forwarded-for',b'198.51.100.1'),(b'x-forwarded-for',b'198.51.100.2')])), '10.0.0.2')
        self.assertEqual(addresses.ip(request([(b'x-forwarded-for',b'2001:db8::1')],peer='::1')), '2001:db8::1')
        self.assertEqual(ClientAddresses().ip(request([(b'x-forwarded-for',b'198.51.100.1')])), '10.0.0.2')
        for invalid in ('*','0.0.0.0/0','::/0','bad'):
            with self.assertRaises(RuntimeError):
                ClientAddresses(invalid)
