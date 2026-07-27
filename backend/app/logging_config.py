import contextvars
import logging
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request

# Context variable to store the trace_id for the current request
trace_id_ctx_var = contextvars.ContextVar("trace_id", default=None)

class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Prefer X-Trace-Id header if provided, otherwise generate one
        trace_id = request.headers.get("X-Trace-Id", str(uuid.uuid4()))
        token = trace_id_ctx_var.set(trace_id)
        
        try:
            response = await call_next(request)
            response.headers["X-Trace-Id"] = trace_id
            return response
        finally:
            trace_id_ctx_var.reset(token)

class TraceIdFilter(logging.Filter):
    """Injects trace_id into log records."""
    def filter(self, record):
        trace_id = trace_id_ctx_var.get()
        record.trace_id = trace_id if trace_id else "N/A"
        return True

def setup_logging():
    logger = logging.getLogger("branding_engine")
    logger.setLevel(logging.INFO)
    
    # Remove existing handlers to avoid duplicates
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [trace_id=%(trace_id)s] [%(name)s] %(message)s"
    )
    handler.setFormatter(formatter)
    
    # Add the filter to the handler
    trace_filter = TraceIdFilter()
    handler.addFilter(trace_filter)
    logger.addHandler(handler)
    
    # Also attach the filter to uvicorn/fastapi loggers if needed
    for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"]:
        l = logging.getLogger(logger_name)
        l.addFilter(trace_filter)
        
        # Ensure they have our formatter if they have handlers
        for h in l.handlers:
            h.setFormatter(formatter)
            h.addFilter(trace_filter)
