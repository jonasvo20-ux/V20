import os

os.environ["DEMO_MODE"] = "1"

from flask_frozen import Freezer
from app import app

app.config["FREEZER_DESTINATION"] = "build"
app.config["FREEZER_RELATIVE_URLS"] = True

freezer = Freezer(app)


@freezer.register_generator
def api_status():
    yield {}


@freezer.register_generator
def api_history():
    yield {}


@freezer.register_generator
def api_events():
    yield {}


@freezer.register_generator
def api_logs():
    yield {}


@freezer.register_generator
def download_log():
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    if os.path.isdir(log_dir):
        for name in os.listdir(log_dir):
            if name.endswith(".csv"):
                yield {"name": name}

if __name__ == "__main__":
    freezer.freeze()
