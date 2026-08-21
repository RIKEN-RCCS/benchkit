import os

from flask import render_template


HOME_GUIDE_LINKS = {
    "add_app": "https://github.com/RIKEN-RCCS/benchkit/blob/main/docs/guides/add-app.md",
    "add_site": "https://github.com/RIKEN-RCCS/benchkit/blob/main/docs/guides/add-site.md",
    "add_estimation": "https://github.com/RIKEN-RCCS/benchkit/blob/main/docs/guides/add-estimation.md",
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

    app.add_url_rule(f"{prefix}/", endpoint="home", view_func=homepage, strict_slashes=False)
