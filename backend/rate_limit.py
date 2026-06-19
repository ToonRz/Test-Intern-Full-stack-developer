"""
Shared rate-limit state — extracted from backend.main so router modules can
import it without creating a circular dependency.

slowapi's @limiter.limit(...) decorator requires a Limiter instance at
module-import time. Wiring it through a dedicated module avoids
`backend.main <-> backend.routers.auth` cycle.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
