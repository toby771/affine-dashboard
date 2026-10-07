from flask import Flask

from .config import Config
from .jinja import register_filters
from .routes import register_routes


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    register_filters(app)
    register_routes(app)

    return app
