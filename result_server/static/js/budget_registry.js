"use strict";

const form = document.querySelector("[data-budget-setup]");
if (form) {
    const catalog = JSON.parse(document.getElementById("budget-execution-data").textContent);
    const system = form.elements.system;
    const account = form.elements.account_id;
    const connection = form.elements.connection_id;
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
}
