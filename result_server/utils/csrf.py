"""CSRF extension setup for the result server."""

from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect()


def init_csrf(app, *, exempt_blueprints=()):
    """Initialize CSRF protection and exempt non-browser API blueprints."""
    for blueprint in exempt_blueprints:
        csrf.exempt(blueprint)
    csrf.init_app(app)
    return csrf
