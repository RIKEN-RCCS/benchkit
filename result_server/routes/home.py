from flask import render_template

from utils.system_info import get_all_systems_info


GUIDE_LINKS = {
    "add_app": "https://github.com/RIKEN-RCCS/benchkit/blob/develop/docs/guides/add-app.md",
    "add_site": "https://github.com/RIKEN-RCCS/benchkit/blob/develop/docs/guides/add-site.md",
    "add_estimation": "https://github.com/RIKEN-RCCS/benchkit/blob/develop/docs/guides/add-estimation.md",
}


def register_home_routes(app, prefix=""):
    def homepage():
        systems_info = get_all_systems_info()
        systems = [
            {
                "system": system_name,
                "name": info["name"],
                "cpu_name": info["cpu_name"],
                "cpu_per_node": info["cpu_per_node"],
                "cpu_cores": info["cpu_cores"],
                "gpu_name": info["gpu_name"],
                "gpu_per_node": info["gpu_per_node"],
                "memory": info["memory"],
            }
            for system_name, info in systems_info.items()
        ]
        return render_template(
            "home.html",
            systems=systems,
            system_count=len(systems),
            guide_links=GUIDE_LINKS,
        )

    app.add_url_rule(f"{prefix}/", endpoint="home", view_func=homepage, strict_slashes=False)
