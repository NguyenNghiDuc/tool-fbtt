import csv
import io
import json
import random
from string import Formatter
from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field, HttpUrl

class Product(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    price: float = Field(ge=0, allow_inf_nan=False)
    image: HttpUrl | None = None
    shopee_link: HttpUrl | None = None
    tiktok_link: HttpUrl | None = None
    commission: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)
    niche: str = Field(default='', max_length=100)
    available: bool = True

class ProductAssignment(BaseModel):
    product_ids: list[int] = Field(max_length=50)

class Caption(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    variants: list[str] = Field(min_length=1, max_length=100)
    hashtags: list[str] = Field(default_factory=list, max_length=100)
    niche: str = Field(default='', max_length=100)

class Preview(BaseModel):
    product_id: int
    profile_id: int
    caption_id: int

ALLOWED = {'ten_san_pham', 'gia', 'link', 'hashtag'}

def install(app, db, cfg, current_user, admin, publisher, get_profile, get_media, event):
    def find(kind, rid):
        rows = db.query('SELECT body FROM records WHERE kind=? AND id=?', (kind, rid))
        if not rows:
            raise HTTPException(404, f'{kind} not found')
        return dict(json.loads(rows[0]['body']), id=rid)
    def save(kind, body, rid=None):
        data = body.model_dump(mode='json')
        if rid is None:
            rid = db.record(kind, data)
        else:
            find(kind, rid)
            db.execute('UPDATE records SET body=? WHERE id=?', (json.dumps(data), rid))
        return dict(data, id=rid)
    @app.get('/api/products')
    def products(user=Depends(current_user)):
        return db.records('product')
    @app.post('/api/products', status_code=201)
    def add_product(body: Product, user=Depends(admin)):
        return save('product', body)
    @app.put('/api/products/{pid}')
    def edit_product(pid: int, body: Product, user=Depends(admin)):
        return save('product', body, pid)
    @app.delete('/api/products/{pid}')
    def delete_product(pid: int, user=Depends(admin)):
        find('product', pid)
        db.execute('DELETE FROM records WHERE id=?', (pid,))
        return {'ok': True}
    @app.post('/api/products/import')
    async def import_csv(request: Request, user=Depends(admin)):
        raw = await request.body()
        if len(raw) > 2 * 1024 * 1024:
            raise HTTPException(413, 'Maximum CSV size: 2 MiB')
        try:
            rows = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
            if len(rows) > 5000:
                raise ValueError('Too many rows')
            parsed = [Product.model_validate({k: v for k, v in row.items() if v != ''}) for row in rows]
        except (ValueError, TypeError):
            raise HTTPException(422, 'Invalid CSV; no products imported') from None
        with db.connect() as conn:
            ids = [conn.execute('INSERT INTO records(kind,body) VALUES (?,?)',
                   ('product', p.model_dump_json())).lastrowid for p in parsed]
        return {'imported': len(ids), 'ids': ids}
    @app.post('/api/media/{mid}/products')
    def assign_products(mid: int, body: ProductAssignment, user=Depends(admin)):
        get_media(mid)
        for pid in body.product_ids:
            find('product', pid)
        with db.connect() as conn:
            conn.execute('DELETE FROM media_products WHERE media_id=?', (mid,))
            for pid in set(body.product_ids):
                conn.execute('INSERT INTO media_products VALUES (?,?)', (mid, pid))
        return {'ok': True}
    @app.get('/api/media/{mid}/products')
    def media_products(mid: int, user=Depends(current_user)):
        get_media(mid)
        return [find('product', r['product_id']) for r in db.query('SELECT product_id FROM media_products WHERE media_id=?', (mid,))]
    @app.get('/api/captions')
    def captions(user=Depends(current_user)):
        return db.records('caption')
    @app.post('/api/captions', status_code=201)
    def add_caption(body: Caption, user=Depends(admin)):
        for text in body.variants:
            try:
                for _, key, spec, conversion in Formatter().parse(text):
                    if key is not None and (key not in ALLOWED or spec or conversion):
                        raise ValueError()
                if len(text) > 2000:
                    raise ValueError()
            except ValueError:
                raise HTTPException(422, 'Use only {ten_san_pham}, {gia}, {link}, {hashtag}; max 2000 characters')
        return save('caption', body)
    def render(product_id, profile_id, caption_id):
        product = find('product', product_id)
        profile = get_profile(profile_id)
        caption = find('caption', caption_id)
        if not product['available']:
            raise HTTPException(409, 'Product unavailable; publishing blocked')
        link = product['shopee_link'] if profile['platform'] == 'facebook' else product['tiktok_link']
        tags = random.SystemRandom().sample(caption['hashtags'], min(4, len(caption['hashtags'])))
        key = f'caption_rotation:{caption_id}:{profile_id}'
        # Rotation is persistent, never repeats adjacent variants when >1 are configured.
        with db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT id,body FROM records WHERE kind=?', (key,)).fetchone()
            index = (json.loads(row['body'])['index'] + 1) % len(caption['variants']) if row else 0
            if row:
                conn.execute('UPDATE records SET body=? WHERE id=?', (json.dumps({'index': index}), row['id']))
            else:
                conn.execute('INSERT INTO records(kind,body) VALUES (?,?)', (key, json.dumps({'index': index})))
        text = caption['variants'][index].format(ten_san_pham=product['name'], gia=f"{product['price']:,.0f}",
                    link=link or '', hashtag=' '.join(tags))
        if '#quảngcáo' not in text.lower():
            text += '\n#quảngcáo'
        return {'text': text, 'manual_shop_link': profile['platform'] == 'tiktok', 'variant': index}
    @app.post('/api/captions/preview')
    def preview(body: Preview, user=Depends(current_user)):
        return render(body.product_id, body.profile_id, body.caption_id)
    app.state.render_caption = render
    app.state.find_record = find
    from .scheduling import install as scheduling
    scheduling(app, db, cfg, current_user, admin, publisher, get_profile, get_media, event)
