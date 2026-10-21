import asyncio
import sqlite3
from unittest.mock import AsyncMock, patch
import httpx
from .test_profiles import ProfilesFixture


class MaintenanceTest(ProfilesFixture):
    def callbacks(self):
        for attribute in ('refresh_tokens','scan_inbox','tick','operations_tick'):
            setattr(self.app.state,attribute,AsyncMock())

    def test_stage_errors_are_diagnostic_redacted_and_isolated(self):
        self.callbacks()
        self.app.state.refresh_tokens.side_effect = RuntimeError('access_token=SECRET123')
        self.app.state.operations_tick.side_effect = httpx.RemoteProtocolError('https://example.com/?token=SECRET123')
        with self.assertLogs('fbtt.maintenance',level='ERROR') as logs:
            asyncio.run(self.app.state.maintenance_cycle())
        self.app.state.scan_inbox.assert_awaited_once()
        self.app.state.tick.assert_awaited_once()
        self.app.state.operations_tick.assert_awaited_once()
        events = self.client.get('/api/events').json()
        messages = ' '.join(e['message'] for e in events)
        self.assertIn('refresh_tokens: RuntimeError',messages)
        self.assertIn('operations: RemoteProtocolError',messages)
        self.assertNotIn('SECRET123',messages+' '.join(logs.output))
        self.assertNotIn('https://',messages+' '.join(logs.output))
        self.app.state.refresh_tokens.side_effect = None
        self.app.state.operations_tick.side_effect = None
        asyncio.run(self.app.state.maintenance_cycle())
        self.assertEqual(self.app.state.refresh_tokens.await_count,2)
        self.assertEqual(self.app.state.tick.await_count,2)

    def test_refresh_interval_and_session_cleanup(self):
        self.callbacks()
        uid = self.client.get('/api/me').json()['id']
        self.app.state.db.execute('INSERT INTO sessions VALUES (?,?,?)',('expired-test-session',uid,1))
        asyncio.run(self.app.state.maintenance_cycle())
        asyncio.run(self.app.state.maintenance_cycle())
        self.app.state.refresh_tokens.assert_awaited_once()
        self.assertEqual(self.app.state.tick.await_count,2)
        self.assertEqual(self.app.state.db.query('SELECT * FROM sessions WHERE hash=?',('expired-test-session',)),[])

    def test_cancellation_is_not_swallowed(self):
        self.callbacks()
        self.app.state.refresh_tokens.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(self.app.state.maintenance_cycle())
        self.app.state.tick.assert_not_awaited()

    def test_event_store_failure_does_not_kill_maintenance(self):
        self.callbacks()
        self.app.state.refresh_tokens.side_effect = KeyError('secret')
        with patch.object(self.app.state.db,'execute',side_effect=sqlite3.OperationalError('secret-path')):
            with self.assertLogs('fbtt.maintenance',level='ERROR') as logs:
                asyncio.run(self.app.state.maintenance_cycle())
        self.app.state.tick.assert_awaited_once()
        self.assertIn('event_store: OperationalError',' '.join(logs.output))
        self.assertNotIn('secret',' '.join(logs.output))
