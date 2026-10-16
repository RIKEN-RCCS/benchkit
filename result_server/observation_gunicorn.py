"""TLS-only, loopback-bound hosting for observation_app:create_app()."""

from utils.runner_observation_service import service_settings

_settings = service_settings()
bind = _settings.bind
certfile = _settings.certificate
keyfile = _settings.tls_key
workers = 1
timeout = 30
graceful_timeout = 30
preload_app = False
accesslog = None
errorlog = "-"
forwarded_allow_ips = ""
secure_scheme_headers = {}
