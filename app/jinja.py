from .template_filters import timestamp


def register_filters(app):
    app.jinja_env.filters["timestamp"] = timestamp
