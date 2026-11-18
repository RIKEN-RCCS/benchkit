"""Validate an explicitly selected local repository before running Git."""
from pathlib import Path
import stat


def validate(repository, trusted_root, expected_owner=0):
    if trusted_root is None or type(expected_owner) is not int or expected_owner < 0:
        return False
    try:
        root = Path(trusted_root)
        repo = Path(repository)
        if not root.is_absolute() or not repo.is_absolute() or root.resolve() != root or repo.resolve() != repo:
            return False
        if repo != root and root not in repo.parents:
            return False
        # Every traversed component and every Git input must have the expected
        # owner and deny writes by other identities. Follow no repository links.
        for parent in [root, *root.parents]:
            info = parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or parent.resolve() != parent:
                return False
            sticky_root = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
            if parent == root:
                if info.st_uid != expected_owner or info.st_mode & 0o022:
                    return False
            elif (info.st_uid not in {0, expected_owner} or info.st_mode & 0o022) and not sticky_root:
                return False
        metadata = repo / '.git'
        if not metadata.is_dir():
            return False
        if (metadata/'commondir').exists() or (metadata/'objects/info/alternates').exists():
            return False
        paths = [repo, *[p for p in repo.parents if p == root or root in p.parents], metadata, *metadata.rglob('*')]
        for path in paths:
            info = path.lstat()
            if info.st_uid != expected_owner or info.st_mode & 0o022:
                return False
            if not stat.S_ISREG(info.st_mode) and not stat.S_ISDIR(info.st_mode):
                return False
        config = metadata / "config"
        if config.exists():
            import re
            if re.search(r"(?im)^\s*\[\s*include", config.read_text()):
                return False
        return True
    except (OSError, ValueError):
        return False
