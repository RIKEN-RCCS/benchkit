# SBD H₂O benchmark inputs

The SBD H₂O inputs are not committed to the BenchKit repository. `build.sh`
stages them from the SBD repository's tracked `data/h2o/` directory into
`artifacts/` during the build, and `run.sh` reads them from there. This file
records their upstream provenance and checksums.

- Repository: https://github.com/r-ccs-cms/sbd
- Upstream revision: `02324eee32a49f3203522d230bcbc34ef032a6a6`
- Files: `fcidump.txt`, `h2o-1em4-alpha.txt`, `h2o-1em5-alpha.txt`,
  `h2o-1em6-alpha.txt`, `h2o-1em7-alpha.txt`

SHA-256 checksums:

```text
a3c2302834a33dce7260e8050a3f5180e05dbba1bb748f3e2f6410a7eacbd94d  fcidump.txt
858c1ef9d430aafe0c325281c7257c2e6cb0e77310a707c1109c55747db02139  h2o-1em4-alpha.txt
40b29271726daa2be5a5b181535647164e915646710c2641e46dd1ed078a2ee6  h2o-1em5-alpha.txt
c36920e57507d27dd49d2b729662cbb5a92afce26d61fb0e044e2691599eb804  h2o-1em6-alpha.txt
1f7af972b56143a9ae6862c02288668656a5bd3fb561337c430e0e478f7cb716  h2o-1em7-alpha.txt
```

The upstream SBD repository distributes these files under its Apache-2.0
license (`LICENSE.txt`). `build.sh` copies them from its `bk_fetch_source`
clone of the repository, so the BenchKit application runs without committing
the inputs or relying on private project storage. Set `BK_SBD_INPUT_DIR` to
use an equivalent project-storage copy instead.
