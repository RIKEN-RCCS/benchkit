"use strict";

function runnerPicker(form) {
    const connection = form.elements.connection_id;
    const observations = JSON.parse(document.getElementById("budget-runner-data").textContent);
    const statusLabel = runner => {
        if (!runner.fresh) return `Observation unavailable or expired; last success ${runner.age}`;
        return [runner.heartbeat, runner.paused ? "paused" : "", runner.protected ? "protected" : ""].filter(Boolean).join(", ");
    };
    const updateMatches = () => {
        const observed = observations[connection.value];
        const runners = observed?.runners || [];
        for (const role of ["build", "run"]) {
            const matches = form.querySelector(`[data-tag-matches="${role}"]`);
            const tag = form.elements[`${role}_tag`].value;
            matches.hidden = !tag;
            if (!tag) continue;
            const found = runners.filter(runner => runner.fresh && runner.tags.includes(tag));
            const online = found.filter(runner => runner.heartbeat === "online" && !runner.paused).length;
            matches.textContent = found.length ? `${found.length} matching runners; ${online} online, not paused.`
                : "No current match; availability unverified.";
            if (observed?.runners_url) {
                const link = document.createElement("a");
                const url = new URL(observed.runners_url, location.href);
                url.searchParams.set("q", tag);
                link.href = url.href;
                link.target = "_blank";
                link.rel = "noopener";
                link.textContent = "View runners";
                link.setAttribute("aria-label", `View ${role} runners (new tab)`);
                matches.append(" ", link);
            }
        }
    };
    const updateChoices = () => {
        const observed = observations[connection.value];
        for (const role of ["build", "run"]) {
            const wrapper = form.querySelector(`[data-runner-picker="${role}"]`);
            const select = wrapper.querySelector("select");
            const status = wrapper.querySelector("[role=status]");
            wrapper.hidden = false;
            select.replaceChildren(new Option("Choose a runner to fill the tag below", ""));
            for (const runner of observed?.runners || []) {
                for (const tag of runner.tags) {
                    const option = new Option(`${runner.label} (#${runner.id}) / ${tag} / ${statusLabel(runner)}`, tag);
                    option.disabled = !runner.fresh;
                    select.add(option);
                }
            }
            select.disabled = !Array.from(select.options).some(option => option.value && !option.disabled);
            status.textContent = !connection.value ? "Select a GitLab connection." : !observed || observed.state === "not_observed"
                ? "No observations for this connection. Manual tags remain available."
                : observed.state !== "current" ? "Observations unavailable or expired. Existing tags are unchanged."
                : select.disabled ? "No current tagged runners observed. Manual tags remain available."
                : "";
            status.hidden = !status.textContent;
        }
        updateMatches();
    };
    for (const role of ["build", "run"]) {
        const select = form.querySelector(`[data-runner-picker="${role}"] select`);
        select.addEventListener("change", () => {
            if (select.value) form.elements[`${role}_tag`].value = select.value;
            updateMatches();
            form.dispatchEvent(new Event("runner-tag-change"));
        });
        form.elements[`${role}_tag`].addEventListener("input", () => {
            select.value = "";
            updateMatches();
        });
    }
    connection.addEventListener("change", updateChoices);
    updateChoices();
    return updateChoices;
}

const form = document.querySelector("[data-budget-setup]");
if (form) {
    const catalog = JSON.parse(document.getElementById("budget-execution-data").textContent);
    const system = form.elements.system;
    const account = form.elements.account_id;
    const connection = form.elements.connection_id;
    const updateChoices = runnerPicker(form);
    const fill = (names, record) => {
        for (const name of names) form.elements[name].value = record[name] || "";
    };
    const loadAccount = () => {
        const record = catalog.find(item => item.id === account.value) || {};
        if (record.id) fill(["build_tag", "run_tag"], record);
        form.elements.loaded_account_id.value = account.value;
        if (record.connection_id) {
            connection.value = record.connection_id;
        }
        updateChoices();
        filterSettings();
        form.dispatchEvent(new Event("execution-settings-change"));
    };
    const filterSettings = () => {
        for (const option of account.options) {
            const available = !option.value || option.dataset.system === system.value;
            option.hidden = !available && !option.selected;
            option.disabled = !available && !option.selected;
        }
        const record = catalog.find(item => item.id === account.value);
        account.setCustomValidity(account.value && (!record || record.system !== system.value)
            ? "Select settings for the managed system, or choose New execution settings." : "");
    };
    system.addEventListener("input", filterSettings);
    account.addEventListener("change", loadAccount);
    form.addEventListener("invalid", event => {
        const details = event.target.closest("details");
        if (details) details.open = true;
    }, true);
    filterSettings();
    updateChoices();
}

const group = document.querySelector("[data-budget-group]");
if (group) {
    const settings = JSON.parse(document.getElementById("budget-execution-data").textContent);
    const rows = Array.from(group.querySelectorAll("[data-group-target]"));
    const search = group.querySelector("[data-target-filter]");
    const tagFilter = group.querySelector("[data-target-tag-filter]");
    const all = group.querySelector("[data-select-targets]");
    const update = () => {
        for (const row of rows) {
            const selected = row.querySelector("[name=targets]").checked;
            const select = row.querySelector("[data-target-account]");
            const previous = select.value === group.elements.account_id.value ? "" : select.value;
            const choices = settings.filter(item => item.system === group.elements.system.value &&
                item.id !== group.elements.account_id.value);
            const record = choices.find(item => item.id === previous);
            const invalid = !!previous && !record;
            select.replaceChildren(new Option("Common settings", ""),
                ...choices.map(item => new Option(item.display_label, item.id)));
            if (invalid) select.add(new Option("Unavailable settings; select again", previous));
            select.value = previous;
            select.disabled = !selected;
            select.hidden = !selected || (!choices.length && !invalid);
            select.setCustomValidity(invalid && selected ? "Select settings for the managed system" : "");
            row.querySelector("[data-target-mode]").textContent = !selected ? "Not selected" :
                invalid ? "Unavailable settings" : record ? "Saved settings" : "Common settings";
            row.querySelector("[data-target-mode]").hidden = selected && !select.hidden;
            row.querySelector("[data-target-summary]").hidden = !selected || invalid;
            const connection = Array.from(group.elements.connection_id.options).find(option =>
                option.value === (record ? record.connection_id : group.elements.connection_id.value));
            row.querySelector("[data-target-connection]").textContent = connection?.value ? connection.textContent : "Not selected";
            row.querySelector("[data-target-build]").textContent = (record ? record.build_tag : group.elements.build_tag.value) || "Not specified";
            row.querySelector("[data-target-run]").textContent = (record ? record.run_tag : group.elements.run_tag.value) || "Not specified";
            // Filtering never revokes a previously selected execution target.
            row.hidden = !row.dataset.system.toLowerCase().includes(search.value.toLowerCase()) ||
                (tagFilter.checked && row.dataset.runTag !== group.elements.run_tag.value);
        }
        const visible = rows.filter(row => !row.hidden);
        const selected = rows.filter(row => row.querySelector("[name=targets]").checked);
        const visibleSelected = visible.filter(row => row.querySelector("[name=targets]").checked);
        all.disabled = !visible.length;
        all.checked = !!visible.length && visibleSelected.length === visible.length;
        all.indeterminate = visibleSelected.length > 0 && visibleSelected.length < visible.length;
        group.querySelector("[data-target-count]").textContent = `${selected.length} selected / ${visible.length} visible`;
        group.querySelector("[type=submit]").disabled = !selected.length;
    };
    all.addEventListener("change", () => {
        for (const row of rows.filter(item => !item.hidden)) row.querySelector("[name=targets]").checked = all.checked;
        update();
    });
    group.addEventListener("input", event => { if (event.target !== all) update(); });
    group.addEventListener("change", update);
    group.addEventListener("runner-tag-change", update);
    group.addEventListener("execution-settings-change", update);
    update();
}
