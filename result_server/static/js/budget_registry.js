"use strict";

function runnerPicker(form) {
    const connection = form.elements.connection_id;
    const observations = JSON.parse(document.getElementById("budget-runner-data").textContent);
    const matches = document.getElementById("budget-tag-matches");
    const statusLabel = runner => {
        if (!runner.fresh) return `Observation unavailable or expired; last success ${runner.age}`;
        return [runner.heartbeat, runner.paused ? "paused" : "", runner.protected ? "protected" : ""].filter(Boolean).join(", ");
    };
    const updateMatches = () => {
        const observed = observations[connection.value];
        const runners = observed?.runners || [];
        const messages = [];
        for (const role of ["build", "run"]) {
            const tag = form.elements[`${role}_tag`].value;
            if (!tag) continue;
            const found = runners.filter(runner => runner.fresh && runner.tags.includes(tag));
            messages.push(`${role === "build" ? "Build" : "Run"}: ${found.length} observed runners match "${tag}"${found.length ? ` (${found.map(runner => `${runner.label}: ${statusLabel(runner)}`).join("; ")})` : "; availability unverified"}.`);
        }
        matches.textContent = messages.join(" ");
        matches.hidden = !messages.length;
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
        fill(["build_tag", "run_tag"], record);
        form.elements.loaded_account_id.value = account.value;
        if (record.connection_id) {
            connection.value = record.connection_id;
        }
        updateChoices();
        form.dispatchEvent(new Event("execution-settings-change"));
    };
    const filterSettings = () => {
        for (const option of account.options) {
            const available = !option.value || option.dataset.system === system.value;
            option.hidden = !available;
            option.disabled = !available;
        }
        if (account.selectedOptions[0]?.disabled) {
            account.value = "";
            loadAccount();
        }
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
    const rows = Array.from(group.querySelectorAll("[data-group-target]"));
    const search = group.querySelector("[data-target-filter]");
    const tagFilter = group.querySelector("[data-target-tag-filter]");
    const all = group.querySelector("[data-select-targets]");
    const update = () => {
        for (const row of rows) {
            const selected = row.querySelector("[name=targets]").checked;
            const select = row.querySelector("[data-target-account]");
            select.disabled = !selected;
            for (const option of select.options) {
                const available = !option.value || option.dataset.system === group.elements.system.value;
                option.disabled = !available;
                option.hidden = !available;
            }
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

const batch = document.querySelector("[data-budget-batch]");
if (batch) {
    runnerPicker(batch);
    const rows = Array.from(batch.querySelectorAll("[data-batch-system]"));
    const all = batch.querySelector("[data-select-systems]");
    const count = batch.querySelector("[data-batch-count]");
    const updateCount = () => {
        const visible = rows.filter(row => !row.hidden && !row.querySelector("[name=systems]").disabled);
        const checked = visible.filter(row => row.querySelector("[name=systems]").checked);
        all.disabled = !visible.length;
        all.checked = !!visible.length && checked.length === visible.length;
        all.indeterminate = checked.length > 0 && checked.length < visible.length;
        count.textContent = `${checked.length} selected / ${visible.length} available`;
        batch.querySelector("[type=submit]").disabled = !checked.length;
    };
    const filter = () => {
        for (const row of rows) {
            row.hidden = batch.elements.candidate_scope.value !== "all" &&
                (!batch.elements.run_tag.value || row.dataset.runTag !== batch.elements.run_tag.value);
            const checkbox = row.querySelector("[name=systems]");
            if (row.hidden) checkbox.checked = false;
            row.querySelector("[data-budget-name]").disabled = checkbox.disabled || !checkbox.checked;
        }
        updateCount();
    };
    all.addEventListener("change", () => {
        for (const row of rows) {
            const checkbox = row.querySelector("[name=systems]");
            if (!row.hidden && !checkbox.disabled) checkbox.checked = all.checked;
        }
        filter();
    });
    batch.addEventListener("input", event => {
        if (event.target !== all) filter();
    });
    batch.addEventListener("change", filter);
    batch.addEventListener("runner-tag-change", filter);
    filter();
}
