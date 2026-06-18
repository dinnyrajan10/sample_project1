"""
Nepal Thrift — application entry point (Flask application factory).

This wires together the layered architecture:
    routes (api/v1) → services (app_services) → repositories → core/database

Responsibilities here are intentionally thin:
- Configure the app, logging, security, CORS, rate limiting.
- Run idempotent DB migrations and seed the admin user.
- Register API (v1) blueprints, page blueprints, and error handlers.

Run:  python app.py   (or)   flask --app app run --port 5001
"""
from __future__ import annotations

import os

from flask import Flask

from config import settings
from core.exceptions import register_error_handlers
from core.logging_config import (
    configure_logging,
    logger,
    register_request_tracing,
)


def create_app() -> Flask:
    configure_logging()

    app = Flask(__name__)
    app.secret_key = settings.SECRET_KEY
    app.config["UPLOAD_FOLDER"] = settings.UPLOAD_FOLDER
    app.config["MAX_CONTENT_LENGTH"] = settings.MAX_UPLOAD_BYTES + (1024 * 1024)
    os.makedirs(settings.UPLOAD_FOLDER, exist_ok=True)

    # ── Secure session cookie defaults ────────────────────
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.is_production,
    )

    _init_extensions(app)
    _run_startup_tasks()
    _register_blueprints(app)
    register_error_handlers(app)
    register_request_tracing(app)
    _register_security_headers(app)

    for warning in settings.validate_production():
        logger.warning("CONFIG: %s", warning)

    logger.info("%s initialized (env=%s)", settings.APP_NAME, settings.ENV)
    return app


def _init_extensions(app: Flask) -> None:
    # CORS (APIs only).
    try:
        from flask_cors import CORS

        CORS(app, resources={r"/api/*": {"origins": settings.CORS_ORIGINS}},
             supports_credentials=True)
    except ImportError:
        logger.warning("flask-cors not installed; skipping CORS setup.")

    # Rate limiting / brute-force protection.
    try:
        from flask_limiter import Limiter
        from flask_limiter.util import get_remote_address

        limiter = Limiter(
            get_remote_address,
            app=app,
            default_limits=[settings.RATE_LIMIT_DEFAULT],
            storage_uri="memory://",
        )
        app.extensions["limiter"] = limiter

        # Tighter limits on auth + AI endpoints.
        @limiter.request_filter
        def _exempt_static():
            from flask import request
            return request.path.startswith("/static/")
    except ImportError:
        logger.warning("flask-limiter not installed; rate limiting disabled.")


def _run_startup_tasks() -> None:
    from app_services.admin_seed import seed_admin
    from migrations.schema import migrate

    migrate()
    seed_admin()


def _register_blueprints(app: Flask) -> None:
    from api.v1.routes.ai_routes import bp as ai_bp
    from api.v1.routes.auth_routes import bp as auth_bp
    from api.v1.routes.cart_routes import bp as cart_bp
    from api.v1.routes.checkout_routes import bp as checkout_bp
    from api.v1.routes.health_routes import bp as health_bp
    from api.v1.routes.page_routes import bp as pages_bp
    from api.v1.routes.payment_routes import bp as payments_bp
    from api.v1.routes.product_routes import bp as products_bp

    # Canonical versioned API.
    app.register_blueprint(auth_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(cart_bp)
    app.register_blueprint(checkout_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(ai_bp)
    app.register_blueprint(health_bp)

    # Server-rendered pages + admin form actions.
    app.register_blueprint(pages_bp)

    # Backward-compatibility shims for the existing frontend JS.
    from api.v1.routes.legacy_routes import bp as legacy_bp
    app.register_blueprint(legacy_bp)


def _register_security_headers(app: Flask) -> None:
    @app.after_request
    def _headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        return response


app = create_app()


if __name__ == "__main__":
    app.run(debug=settings.DEBUG, port=settings.PORT)
