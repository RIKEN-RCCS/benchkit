# Benchpark CI integration

Benchpark CI can remain an independent repository. The Portal manages its
profiles, manual execution, schedules and execution history using the same
screens as Benchkit. The producer remains responsible for site configuration,
experiment execution and conversion to the shared Result JSON format.

## Connection and profile

Declare the target in `RESULT_SERVER_GITLAB_TARGETS` and its backend in
`RESULT_SERVER_GITLAB_TARGET_BACKENDS` on the console and trigger runner:

```sh
RESULT_SERVER_GITLAB_TARGETS=kit=gitlab.example.org/group/benchkit,park=gitlab.example.org/group/benchpark-ci
RESULT_SERVER_GITLAB_TARGET_BACKENDS='{"park":"benchpark"}'
```

Targets without a backend declaration retain the Benchkit input contract.
Use a dedicated trigger token (`RESULT_SERVER_GITLAB_TRIGGER_TOKEN_PARK` for
this example). No repository or target is selected by guessing an app name.

In Execution Profiles choose **Benchpark CI**, the `park` target, a site
configuration name and an experiment file such as
`config/experiments/example.yaml`. Code, System and Exp scopes describe the
experiment's results; SITE and EXPERIMENT_CONFIG select the actual experiment.
Keep the profile approved and within its validity period. Input settings are
stored in existing profile metadata; no database schema migration is needed.

Manual execution and scheduled triggers must select that same target and an
explicit CI ref. Benchpark manual controls require a typed ref and preselect
the profile target; Benchkit manual controls retain their existing defaults. The producer must support trigger-token pipelines
(`CI_PIPELINE_SOURCE=trigger`). The shared planner sends SITE,
EXPERIMENT_CONFIG, Activity and Portal trigger metadata. It sends the explicit
Portal result URL as BK_PORTAL_RESULT_SERVER with BK_PORTAL_MANAGED=1;
Benchkit's code/system matrix variables are not used to select Benchpark jobs.

Allocation overrides and Budget execution routes currently block submission
for Benchpark. Its site configuration continues to select the scheduler account.
The Portal must not display an unsupported override as an applied allocation.

## Scheduling and ownership

Create a scheduled trigger for the profile with an explicit target/ref, cron
and timezone. Existing Portal controls enable, pause and delete the definition;
the trigger runner supplies deduplication, validity checks and history. A due
minute already submitted is not submitted again. No additional timer is needed.

Before enabling a Portal schedule, review the existing GitLab schedules and
fan-out membership for that site/experiment. Disable the overlapping GitLab
schedule or remove that member through the producer's schedule configuration
under a separate reviewed deployment. Do not enable both owners for the same
workload. Preserve unrelated canary/maintenance schedules. This integration does
not reconcile or delete GitLab schedules, nor enable any Portal schedule on install.

Manual submissions remain in **Trigger Run History** after reloading the page,
with their request number, pipeline link and matching received results. Runner
and manual records share the latest-history list without rewriting stored data.
The submission status records the Portal request; the pipeline link shows CI job
progress. Preview requests are excluded, and result links require the recorded
pipeline identity rather than a reusable manual profile ID.

## Results and compatibility

Benchpark keeps application source_info, FOM/FOM_unit/FOM_version, Exp,
build information and Caliper artifacts in the shared Result format. It adds
execution_backend, ci_project (host/project path), execution_activity and
execution_trigger. The Portal uses the same result list, detail and comparison
views for both producers. Producer fields are added only for identified
Benchpark results; Benchkit-only list/detail/compare output retains its existing shape.
An existing build.harness.name=benchpark also identifies historical Benchpark
results, without rewriting stored data or inferring the producer from Caliper.

New results with a recorded CI project match Portal history by project plus
pipeline ID. An ID shared by multiple projects is ambiguous for an old result
without a project and does not supply Activity or trigger context. Historical
Benchpark records identified by their harness cannot borrow Benchkit run context.
Legacy explicit trigger metadata still provides its existing fallback when no
project was recorded. The Portal
does not change experiment names or assert scientific equivalence across harnesses.

Validate in isolated directories with synthetic credentials and mocked submits.
Test a copied development Result through the list/detail/compare views before
reviewing push, schedule migration or deployment. Do not import the production
application factory or point a test app at a live Portal database.

## Scope of shared changes

The existing planner calls the Benchpark adapter before its unchanged Benchkit
input generation. Benchpark validation, form parsing, manual selection checks,
and producer-specific detail fields live in `result_server/utils/benchpark.py`.
The new profile fields live in `_benchpark_profile_fields.html`.

Profile storage validates and preserves only the new `pipeline` metadata field
when existing clients omit it. Other metadata continues to follow the previous
save behavior. There is no extra profile read during form parsing. Budget
fingerprints and authorization code are unchanged; Benchpark rejects Budget
bindings in its adapter until those execution routes are supported.

The shared history lookup qualifies pipeline IDs by project to prevent mixed
producers from borrowing each other's run context. It retains the previous
child/parent Activity completion and legacy explicit-trigger fallback. No new
scheduler, database schema, role grant, CSRF exemption or ingestion-authentication
path is introduced. A malformed backend declaration blocks planning rather than
sending to a target with an unknown input contract.
