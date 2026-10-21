"""Classify errors without recording exception messages, URLs, tokens or traceback locals."""

ERROR_TYPES = frozenset({
    'RuntimeError', 'ValueError', 'TypeError', 'KeyError', 'AttributeError',
    'OSError', 'FileNotFoundError', 'PermissionError', 'TimeoutError',
    'OperationalError', 'IntegrityError', 'DatabaseError', 'InvalidToken',
    'ConnectError', 'ConnectTimeout', 'ReadTimeout', 'WriteTimeout',
    'PoolTimeout', 'HTTPStatusError', 'RemoteProtocolError', 'ProviderError',
    'PublishError', 'HTTPException',
})


def error_type(exc):
    name = type(exc).__name__
    return name if name in ERROR_TYPES else 'UnexpectedError'
