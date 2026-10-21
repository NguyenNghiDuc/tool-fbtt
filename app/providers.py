"""Official OAuth adapters. All HTTP failures are reduced to safe, token-free errors."""
import base64
import hashlib
from urllib.parse import urlencode

import httpx


class ProviderError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class Providers:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.transport = transport

    def config(self, platform):
        prefix = 'FACEBOOK' if platform == 'facebook' else 'TIKTOK'
        client = self.settings.get(prefix + '_CLIENT_ID')
        secret = self.settings.get(prefix + '_CLIENT_SECRET')
        if not client or not secret:
            raise ProviderError('oauth_not_configured')
        return client, secret

    def redirect_uri(self, platform):
        return self.settings['BASE_URL'].rstrip('/') + '/oauth/' + platform + '/callback'

    def authorize_url(self, platform, state, verifier):
        client, _ = self.config(platform)
        params = dict(redirect_uri=self.redirect_uri(platform), state=state, response_type='code')
        if platform == 'facebook':
            params.update(client_id=client, scope='pages_show_list,pages_read_engagement,pages_manage_posts')
            base = f'https://www.facebook.com/{self.settings["FACEBOOK_API_VERSION"]}/dialog/oauth'
        else:
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            params.update(client_key=client, scope='user.info.basic,video.publish',
                          code_challenge=challenge, code_challenge_method='S256')
            base = 'https://www.tiktok.com/v2/auth/authorize/'
        return base + '?' + urlencode(params)

    async def request(self, method, url, **kwargs):
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=30) as client:
                response = await client.request(method, url, **kwargs)
            if response.status_code in (401, 403):
                raise ProviderError('token_revoked')
            if response.status_code == 429:
                raise ProviderError('rate_limited')
            response.raise_for_status()
            data = response.json()
            if data.get('error') and (not isinstance(data['error'], dict) or data['error'].get('code') not in (None, 'ok')):
                raise ProviderError('provider_rejected')
            return data
        except (httpx.HTTPError, ValueError, AttributeError):
            raise ProviderError('provider_unavailable') from None

    async def exchange(self, platform, code, verifier, external_id):
        client, secret = self.config(platform)
        if platform == 'tiktok':
            data = await self.request('POST', 'https://open.tiktokapis.com/v2/oauth/token/', data={
                'client_key': client, 'client_secret': secret, 'code': code,
                'grant_type': 'authorization_code', 'redirect_uri': self.redirect_uri(platform),
                'code_verifier': verifier,
            })
            return dict(external_id=data['open_id'], access_token=data['access_token'],
                        refresh_token=data.get('refresh_token'), expires_in=data['expires_in'])
        base = f'https://graph.facebook.com/{self.settings["FACEBOOK_API_VERSION"]}'
        short = await self.request('GET', base + '/oauth/access_token', params={
            'client_id': client, 'client_secret': secret, 'code': code,
            'redirect_uri': self.redirect_uri(platform),
        })
        long = await self.request('GET', base + '/oauth/access_token', params={
            'grant_type': 'fb_exchange_token', 'client_id': client, 'client_secret': secret,
            'fb_exchange_token': short['access_token'],
        })
        pages = await self.request('GET', base + '/me/accounts', params={
            'fields': 'id,name,access_token', 'limit': 100,
        }, headers={'Authorization': 'Bearer ' + long['access_token']})
        while True:
            page = next((p for p in pages.get('data', []) if p['id'] == external_id), None)
            if page:
                return dict(external_id=page['id'], access_token=page['access_token'], refresh_token=None,
                            expires_in=long.get('expires_in'))
            after = pages.get('paging', {}).get('cursors', {}).get('after')
            if not pages.get('paging', {}).get('next') or not after:
                raise ProviderError('page_not_authorized')
            pages = await self.request('GET', base + '/me/accounts', params={
                'fields': 'id,name,access_token', 'limit': 100, 'after': after,
            }, headers={'Authorization': 'Bearer ' + long['access_token']})

    async def refresh(self, platform, token):
        client, secret = self.config(platform)
        if platform != 'tiktok':
            raise ProviderError('reauthorization_required')
        data = await self.request('POST', 'https://open.tiktokapis.com/v2/oauth/token/', data={
            'client_key': client, 'client_secret': secret,
            'grant_type': 'refresh_token', 'refresh_token': token,
        })
        return data
