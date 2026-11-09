document.addEventListener("DOMContentLoaded", function () {
    const root = document.querySelector("[data-execution-management]");
    if (!root) return;
    const links = Array.from(root.querySelectorAll("[data-execution-tab]"));
    const panels = Array.from(root.querySelectorAll("[data-execution-panel]"));
    const lookup = root.querySelector("[data-history-lookup]");
    const lookupStatus = lookup?.querySelector("[data-history-status]");
    let lookupRequest = null;
    let historyLoaded = false;
    const anchors = {
        "execution-history": "runs",
        "profile-budget": "profiles",
        "profile-editor": "profiles",
        "trigger-editor": "triggers"
    };

    function cancelHistoryLookup() {
        if (!lookupRequest) return;
        const request = lookupRequest;
        lookupRequest = null;
        request.abort();
        lookupStatus.textContent = "";
    }

    async function loadHistoryResults() {
        if (!lookup || historyLoaded || lookupRequest) return;
        const request = new AbortController();
        lookupRequest = request;
        lookupStatus.textContent = "Checking stored Results...";
        try {
            const response = await fetch(lookup.dataset.historyLookup, {
                signal: request.signal,
                credentials: "same-origin",
                redirect: "error",
            });
            if (!response.ok) throw new Error("History lookup failed");
            const fragment = new DOMParser().parseFromString(await response.text(), "text/html");
            const content = fragment.querySelector("[data-history-content]");
            if (!content) throw new Error("History lookup response is incomplete");
            if (lookupRequest !== request) return;
            root.querySelector("[data-history-content]").replaceWith(content);
            if (content.hasAttribute("data-history-lookup-unavailable")) {
                lookupStatus.textContent = "Result lookup unavailable";
                return;
            }
            historyLoaded = true;
            lookup.hidden = true;
        } catch (error) {
            if (lookupRequest === request) lookupStatus.textContent = "Result lookup unavailable";
        } finally {
            if (lookupRequest === request) lookupRequest = null;
        }
    }

    function select(view, explicit = false) {
        if (!links.some(link => link.dataset.executionTab === view)) view = "runs";
        panels.forEach(panel => { panel.hidden = panel.dataset.executionPanel !== view; });
        links.forEach(link => {
            if (link.dataset.executionTab === view) link.setAttribute("aria-current", "page");
            else link.removeAttribute("aria-current");
        });
        if (view !== "runs") cancelHistoryLookup();
        else if (explicit || lookup?.hasAttribute("data-history-auto")) loadHistoryResults();
    }

    function restore() {
        const url = new URL(window.location.href);
        const anchor = document.getElementById(url.hash.slice(1));
        const anchoredView = anchors[url.hash.slice(1)];
        if (anchoredView) {
            select(anchoredView, true);
            if (anchor) {
                const editor = anchor.closest("details.execution-editor");
                if (editor) editor.open = true;
                anchor.scrollIntoView();
            }
        } else if (url.searchParams.has("edit")) select("profiles");
        else if (url.searchParams.has("edit_trigger")) select("triggers");
        else select(url.searchParams.get("tab") || "runs", true);
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
            select(link.dataset.executionTab, true);
        });
    });
    window.addEventListener("popstate", restore);
    window.addEventListener("hashchange", restore);
    // A legacy fragment must reveal its panel before the browser can reach it.
    lookup?.querySelector("a").addEventListener("click", function (event) {
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        loadHistoryResults();
    });
    if (window.location.hash) restore();
    else if (lookup?.hasAttribute("data-history-auto") &&
             links.some(link => link.dataset.executionTab === "runs" && link.hasAttribute("aria-current"))) {
        loadHistoryResults();
    }
});
