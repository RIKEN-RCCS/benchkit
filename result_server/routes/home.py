import os

from flask import abort, render_template

from utils.portal_version import portal_release_notes


HOME_GUIDE_LINKS = {
    "add_app": "https://github.com/RIKEN-RCCS/benchkit/blob/main/docs/guides/add-app.md",
    "benchpark_fn_apps": "https://github.com/RIKEN-RCCS/benchpark/blob/FN_apps/User_Guide.md",
    "benchpark_upstream": "https://github.com/llnl/benchpark",
}


def build_home_guide_links():
    links = dict(HOME_GUIDE_LINKS)
    links["discord"] = os.environ.get("CX_DISCORD_INVITE_URL", "")
    return links


def register_home_routes(app, prefix=""):
    def homepage():
        return render_template(
            "home.html",
            guide_links=build_home_guide_links(),
        )

    def changes():
        return render_template(
            "changes.html",
            release_notes=portal_release_notes(),
        )

    def about():
        site_info = app.config.get("PUBLIC_SITE_INFO")
        if not site_info:
            abort(404)
        return render_template("about.html", site_info=site_info)

    app.add_url_rule(f"{prefix}/", endpoint="home", view_func=homepage, strict_slashes=False)
    app.add_url_rule(
        f"{prefix}/changes",
        endpoint="changes",
        view_func=changes,
        strict_slashes=False,
    )
    app.add_url_rule(f"{prefix}/about", endpoint="about", view_func=about, strict_slashes=False)
