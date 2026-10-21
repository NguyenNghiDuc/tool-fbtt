from .test_media import MediaFixture

class CommerceFixture(MediaFixture):
    def product(self):
        r = self.client.post('/api/products', json={'name': 'Áo', 'price': 120000, 'shopee_link': 'https://shopee.vn/a', 'tiktok_link': 'https://shop.tiktok.com/a'})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()


class CommerceTest(CommerceFixture):
    def test_product_crud_links_and_assignment(self):
        product = self.product()
        mid = self.upload().json()['id']
        self.assertEqual(self.client.post(f'/api/media/{mid}/products', json={'product_ids': [product['id']]}).status_code, 200)
        self.assertEqual(self.client.get(f'/api/media/{mid}/products').json()[0]['name'], 'Áo')
        self.assertEqual(self.client.post('/api/products', json={'name': 'x', 'price': -1}).status_code, 422)
        self.assertEqual(self.client.post('/api/products', json={'name': 'x', 'price': 1, 'shopee_link': 'javascript:alert(1)'}).status_code, 422)
        self.assertEqual(self.client.delete(f'/api/products/{product["id"]}').status_code, 200)
        self.assertEqual(self.client.get(f'/api/media/{mid}/products').json(), [])

    def test_csv_import_is_atomic(self):
        self.assertEqual(self.client.post('/api/products/import', content='name,price\nGood,100\nBad,-1').status_code, 422)
        self.assertEqual(self.client.get('/api/products').json(), [])
        self.assertEqual(self.client.post('/api/products/import', content='name,price\nA,100\nB,200').json()['imported'], 2)

    def test_caption_rotation_disclosure_and_validation(self):
        p, product = self.profile(), self.product()
        r = self.client.post('/api/captions', json={'name': 'Sale', 'variants': ['{ten_san_pham} {gia} {link} {hashtag}', 'Mua {ten_san_pham}!'], 'hashtags': ['#sale', '#ao']})
        self.assertEqual(r.status_code, 201, r.text)
        body = {'product_id': product['id'], 'profile_id': p['id'], 'caption_id': r.json()['id']}
        first = self.client.post('/api/captions/preview', json=body).json()
        second = self.client.post('/api/captions/preview', json=body).json()
        self.assertNotEqual(first['variant'], second['variant'])
        self.assertIn('#quảngcáo', first['text'])
        self.assertTrue(first['manual_shop_link'])
        self.assertEqual(self.client.post('/api/captions', json={'name': 'bad', 'variants': ['{ten_san_pham.__class__}']}).status_code, 422)
        product['available'] = False
        self.client.put(f'/api/products/{product["id"]}', json=product)
        self.assertEqual(self.client.post('/api/captions/preview', json=body).status_code, 409)
