# SBD H₂O benchmark inputs

These files are copied unchanged from the SBD repository's tracked
`data/h2o/` directory:

- Repository: https://github.com/r-ccs-cms/sbd
- Upstream revision: `02324eee32a49f3203522d230bcbc34ef032a6a6`
- Files: `fcidump.txt`, `h2o-1em5-alpha.txt`, `h2o-1em7-alpha.txt`

SHA-256 checksums:

```text
a3c2302834a33dce7260e8050a3f5180e05dbba1bb748f3e2f6410a7eacbd94d  fcidump.txt
40b29271726daa2be5a5b181535647164e915646710c2641e46dd1ed078a2ee6  h2o-1em5-alpha.txt
1f7af972b56143a9ae6862c02288668656a5bd3fb561337c430e0e478f7cb716  h2o-1em7-alpha.txt
```

The upstream SBD repository distributes these files under its Apache-2.0
license (`LICENSE.txt`). They are retained here so the BenchKit application
can run without private project storage. Set `BK_SBD_INPUT_DIR` to use an
equivalent project-storage copy instead.
