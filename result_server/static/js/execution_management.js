document.addEventListener("DOMContentLoaded", function () {
    const root = document.querySelector("[data-execution-management]");
    if (!root) return;
    const links = Array.from(root.querySelectorAll("[data-execution-tab]"));
    const panels = Array.from(root.querySelectorAll("[data-execution-panel]"));
    const anchors = {
        "execution-history": "runs",
        "profile-budget": "profiles",
        "profile-editor": "profiles",
        "trigger-editor": "triggers"
    };

    function select(view) {
        if (!links.some(link => link.dataset.executionTab === view)) view = "runs";
        panels.forEach(panel => { panel.hidden = panel.dataset.executionPanel !== view; });
        links.forEach(link => {
            if (link.dataset.executionTab === view) link.setAttribute("aria-current", "page");
            else link.removeAttribute("aria-current");
        });
    }

    function restore() {
        const url = new URL(window.location.href);
        const anchor = document.getElementById(url.hash.slice(1));
        const anchoredView = anchors[url.hash.slice(1)];
        if (anchoredView) {
            select(anchoredView);
            if (anchor) {
                const editor = anchor.closest("details.execution-editor");
                if (editor) editor.open = true;
                anchor.scrollIntoView();
            }
        } else if (url.searchParams.has("edit")) select("profiles");
        else if (url.searchParams.has("edit_trigger")) select("triggers");
        else select(url.searchParams.get("tab") || "runs");
    }

    links.forEach(link => {
        link.addEventListener("click", function (event) {
            if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            const url = new URL(window.location.href);
            url.searchParams.set("tab", link.dataset.executionTab);
            url.searchParams.delete("edit");
            url.searchParams.delete("edit_trigger");
            url.hash = "";
            window.history.pushState(null, "", url);
            select(link.dataset.executionTab);
        });
    });
    window.addEventListener("popstate", restore);
    window.addEventListener("hashchange", restore);
    // A legacy fragment must reveal its panel before the browser can reach it.
    if (window.location.hash) restore();
});
