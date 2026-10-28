# Staged data

The `top` dataset (Top Tagging Community benchmark; Kasieczka et al.,
SciPost Phys. 7, 014, 2019) as packaged by the OmniLearned authors at
`https://portal.nersc.gov/cfs/dasrepo/omnilearned/top/{train,val,test}/`.
Downloaded 2026-10-23 via `omnilearned dataloader -d top -f <dir>` and
pre-staged at the per-site `CX_input` local-file directory, like this
repo's `petsc-gmres` and `ffb`:

- RIKYU: `/data1/rkp00015/CX_input/omnilearned/top/{train,val,test}/`
- RC_GH200 / RC_DGXSP / RC_GENOA: `/lvs0/dne1/rccs-nghpcadu/CX_input/omnilearned/top/top/{train,val,test}/`
  (the app resolves `<root>/top/<split>/`; checksummed and identical to
  the RIKYU copy)
- Fugaku: `/vol0200/share/ra000009/CX_input/omnilearned/top/{train,val,test}/`
  (single-nested: `BK_OMNILEARNED_DATA` is the parent of `top/`; sizes
  match the table below)

Note the layout: the OmniLearned dataloader appends the dataset name to
the root path, so the staged tree is `<root>/top/<split>/*.h5` plus the
`file_index.npy` and `file_manifest.json` the dataloader generated on
first use (regenerate by running the dataloader once against the staged
copy).

| file | bytes | sha256 |
|---|---:|---|
| train/train_ttbar.h5 | 5,851,554,048 | `46f774962a825742ad35981f3100cbec1677a3c7992463080591f980e4f06a49` |
| val/val_ttbar.h5 | 1,947,298,048 | `78168a649956b9a42ac0b5f6dd033d10d2a2c95f42f7676aed45743cea91501f` |
| test/test_ttbar.h5 | 1,952,130,048 | `d4875cb3086bfb37adcd20cbe8937ec7cbd317367153b3da7f4ce6522d4efdd2` |
