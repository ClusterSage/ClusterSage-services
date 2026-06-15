import logging
from pythonjsonlogger import jsonlogger

def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
