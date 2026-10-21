import io
import tarfile
import httpx
from .test_publishing import PublishingFixture

class OperationsTest(PublishingFixture):
    def test_logs_reports_and_csv_formula_safety(self):
        job = self.ready()
        self.app.state.db.execute('UPDATE profiles SET name=?', ('=HYPERLINK("bad")',))
        self.client.post('/api/worker/tick')
        report = self.client.get('/api/reports/summary').json()
        self.assertEqual(report['jobs'], [{'status':'success','count':1}])
        csv = self.client.get('/api/reports/jobs.csv')
        self.assertIn("'=HYPERLINK", csv.text)
        self.assertNotIn('secret-access', csv.text)
    def test_tracking_orders_and_unavailable_product(self):
        p, product = self.profile(), self.product()
        link = self.client.post('/api/links', json={'product_id':product['id'],'profile_id':p['id'],'platform':'shopee'}).json()
        response = self.client.get('/r/' + link['code'], follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get('/api/reports/summary').json()['clicks'][0]['clicks'], 1)
        order = {'product_id':product['id'],'profile_id':p['id'],'order_ref':'order1','revenue':100,'commission':10}
        self.assertEqual(self.client.post('/api/orders', json=order).status_code, 201)
        self.assertEqual(self.client.post('/api/orders', json=order).status_code, 409)
        product['available'] = False
        self.client.put(f'/api/products/{product["id"]}', json=product)
        self.assertEqual(self.client.get('/r/' + link['code']).status_code, 410)
    def test_telegram_outbox_retry_and_redaction(self):
        self.ready()
        self.mode = 'timeout'
        self.client.post('/api/worker/tick')
        self.assertEqual(len(self.client.get('/api/notifications').json()), 1)
        self.assertFalse(self.client.post('/api/notifications/send').json()['configured'])
        self.app.state.cfg.update(TELEGRAM_BOT_TOKEN='bot-secret', TELEGRAM_CHAT_ID='42')
        self.app.state.providers.transport = httpx.MockTransport(lambda r: httpx.Response(500))
        self.client.post('/api/notifications/send')
        self.assertEqual(self.client.get('/api/notifications').json()[0]['attempts'], 1)
        self.assertNotIn('bot-secret', self.client.get('/api/notifications').text)
        self.app.state.db.execute('UPDATE notifications SET next_attempt=0')
        self.app.state.providers.transport = httpx.MockTransport(lambda r: httpx.Response(200,json={'ok':True}))
        self.assertEqual(self.client.post('/api/notifications/send').json()['sent'], 1)
        self.assertEqual(self.client.get('/api/notifications').json()[0]['status'], 'sent')
    def test_backup_contains_database_and_video_not_key(self):
        self.ready()
        response = self.client.post('/api/backups')
        self.assertEqual(response.status_code, 200)
        with tarfile.open(fileobj=io.BytesIO(response.content), mode='r:gz') as archive:
            self.assertIn('app.sqlite3', archive.getnames())
            self.assertTrue(any(n.endswith('.mp4') for n in archive.getnames()))
            self.assertFalse(any('.env' in n for n in archive.getnames()))
