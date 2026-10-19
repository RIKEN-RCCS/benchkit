# GENESIS Agent Review

When changing `estimate.sh` or `estimate.metadata.json` in this directory, run
the common version reminder before reporting the change ready for review.
From the repository root, compare against the existing local PR target ref:

```bash
python3.12 scripts/check_estimation_version.py --app genesis --base refs/remotes/origin/develop
```

Use the actual local target commit/ref if it differs. Do not use an already
updated `HEAD` as the base if it would hide the changes under review. The tool
does not fetch; if the base is unavailable, report that the check could not be
completed rather than treating it as passed.

Report the result and whether a method version update is needed. Comments and
formatting alone may not need one; explain that judgment. A zero exit status
can include a review reminder or an unknown version, so read the output. Do
not automatically bump the version or run estimation. This is an agent review
aid, not an additional benchmark or CI step. It inspects only these two files;
it does not establish that all estimation dependencies were reviewed.
