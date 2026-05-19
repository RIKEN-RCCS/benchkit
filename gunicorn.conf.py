"""Reference Gunicorn configuration for result_server deployments."""

import multiprocessing
import os


bind = os.environ.get("RESULT_SERVER_BIND", "127.0.0.1:8800")
workers = int(
    os.environ.get("RESULT_SERVER_WORKERS", str(multiprocessing.cpu_count() * 2 + 1))
)
worker_class = "sync"
timeout = int(os.environ.get("RESULT_SERVER_TIMEOUT", "60"))
graceful_timeout = int(os.environ.get("RESULT_SERVER_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.environ.get("RESULT_SERVER_KEEPALIVE", "5"))
max_requests = int(os.environ.get("RESULT_SERVER_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.environ.get("RESULT_SERVER_MAX_REQUESTS_JITTER", "50"))
limit_request_line = int(os.environ.get("RESULT_SERVER_LIMIT_REQUEST_LINE", "8190"))
limit_request_field_size = int(
    os.environ.get("RESULT_SERVER_LIMIT_REQUEST_FIELD_SIZE", "8190")
)
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("RESULT_SERVER_LOG_LEVEL", "info")
