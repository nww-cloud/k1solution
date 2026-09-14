import os

from flask import Flask

from app.extensions import db


def create_app(config_object="config.Config"):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)

    from app.routes.admin import admin_bp
    from app.routes.employees import employees_bp
    from app.routes.leave import leave_bp
    from app.routes.settlement import settlement_bp

    app.register_blueprint(employees_bp)
    app.register_blueprint(leave_bp)
    app.register_blueprint(settlement_bp)
    app.register_blueprint(admin_bp)

    @app.route("/")
    def index():
        from flask import redirect, url_for

        return redirect(url_for("leave.dashboard"))

    with app.app_context():
        from app import models  # noqa: F401
        from app.seed import seed_leave_rules

        db.create_all()
        seed_leave_rules()

    return app
