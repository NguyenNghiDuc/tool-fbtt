import subprocess
from pathlib import Path
from .test_profiles import ProfilesFixture

class MediaFixture(ProfilesFixture):
    def setUp(self):
        super().setUp()
        self.video_path = Path(self.tmp.name) / 'sample.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=180x320:d=1',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(self.video_path)], check=True, capture_output=True)

    def upload(self):
        return self.client.post('/api/media', files={'file': ('sample.mp4', self.video_path.read_bytes(), 'video/mp4')})


class MediaTest(MediaFixture):
    def test_valid_upload_duplicate_and_corrupt_cleanup(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.text)
        self.assertTrue(response.json()['vertical'])
        self.assertEqual(self.upload().status_code, 409)
        self.assertEqual(self.client.post('/api/media', files={'file': ('bad.mp4', b'garbage')}).status_code, 422)
        self.assertEqual(len(list((Path(self.tmp.name) / 'videos').glob('*.mp4'))), 1)
        self.assertNotIn('path', response.json())

    def test_assignment_warning_and_thumbnail(self):
        mid = self.upload().json()['id']
        p1, p2 = self.profile(), self.profile()
        r = self.client.post(f'/api/media/{mid}/assign', json={'profile_ids': [p1['id'], p2['id']]})
        self.assertTrue(r.json()['duplicate_warning'])
        self.assertEqual(self.client.post(f'/api/media/{mid}/thumbnail').status_code, 200)
        self.assertEqual(self.client.get(f'/api/media/{mid}/thumbnail').headers['content-type'], 'image/jpeg')
        self.assertEqual(self.client.post(f'/api/media/{mid}/assign', json={'profile_ids': [999]}).status_code, 404)

    def test_folder_scan(self):
        inbox = Path(self.tmp.name) / 'inbox'
        inbox.mkdir()
        (inbox / 'video.mp4').write_bytes(self.video_path.read_bytes())
        response = self.client.post('/api/media/scan')
        self.assertIn('id', response.json()[0])
        self.assertFalse((inbox / 'video.mp4').exists())
