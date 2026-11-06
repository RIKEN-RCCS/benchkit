"""App-specific input locations and compiler adjustment; no archive extraction."""
from pathlib import Path
import re
import sys

READ_ONLY = {'BASENAME_ORG', 'OBS_IN_NAME', 'GTOPO30_IN_DIR', 'DEM50M_IN_DIR',
             'GLCCV2_IN_DIR', 'LU100M_IN_DIR'}
ASSIGN = re.compile(r'''^(\s*)([A-Za-z0-9_]+)(\s*=\s*)(["'])(.*?)\4''')


def configure(work, shared):
    work, shared = Path(work).resolve(), Path(shared).resolve()
    if not (shared / 'scale_database').is_dir():
        raise ValueError('Expanded scale_database directory is required')
    for member in ['mean', '0001', '0002']:
        inputs = list((shared / 'result/SC23/20210730060000/bdyorg' / member).glob('bdyorg*.nc'))
        if not inputs:
            raise ValueError('Expanded boundary input is missing for ' + member)
        for path in inputs:
            with path.open('rb') as handle:
                handle.read(1)
    obs = shared / 'result/SC23/obs_radar/radar_20210730060030.dat'
    with obs.open('rb') as handle:
        handle.read(1)
    changed = set()
    for path in (work / 'conf').rglob('*.conf'):
        lines = []
        for line in path.read_text().splitlines(keepends=True):
            match = ASSIGN.match(line)
            if match and match[2].upper() in READ_ONLY:
                value = match[5]
                prefix = str(work) + '/'
                if value.startswith(prefix):
                    relative = value[len(prefix):]
                    if relative.startswith(('result/SC23/', 'scale_database/')):
                        value = str(shared / relative)
                        line = line[:match.start(5)] + value + line[match.end(5):]
                        changed.add(match[2].upper())
            lines.append(line)
        path.write_text(''.join(lines))
    if not {'BASENAME_ORG', 'OBS_IN_NAME', 'GTOPO30_IN_DIR'} <= changed:
        raise ValueError('Expected input declarations were not found')
    # Writes and read/write restart fields must stay in the private run directory.
    for path in (work / 'conf').rglob('*.conf'):
        for line in path.read_text().splitlines():
            match = ASSIGN.match(line)
            if match and str(shared) + '/' in match[5] and match[2].upper() not in READ_ONLY:
                raise ValueError('Shared path in a writable configuration field')


def workaround(source):
    path = Path(source) / 'scale/scale-rm/src/Makefile'
    marker = '# NVIDIA HPC SDK Bug 6861191 workaround'
    text = path.read_text()
    if marker not in text:
        path.write_text(text + '\n' + marker + '\n'
                        'MKINIT_FFLAGS := $(filter-out -fast -O% -Mvect%,$(FFLAGS)) -O1\n'
                        '$(BUILD_DIR)/mod_mkinit.o: FFLAGS = $(MKINIT_FFLAGS)\n')


if __name__ == '__main__':
    if sys.argv[1] == 'workaround':
        workaround(sys.argv[2])
    else:
        configure(sys.argv[2], sys.argv[3])
