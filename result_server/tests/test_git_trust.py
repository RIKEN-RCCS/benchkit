from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
import os
import subprocess

from utils.estimate_version_snapshot import read_estimation_version_reference


def repository(tmp_path):
    path = tmp_path/'repository'
    path.mkdir(mode=0o700)
    subprocess.run(['git','init','-q',str(path)],check=True)
    subprocess.run(['git','-C',str(path),'config','user.name','Example'],check=True)
    subprocess.run(['git','-C',str(path),'config','user.email','example@example.invalid'],check=True)
    subprocess.run(['git','-C',str(path),'commit','-qm','Empty','--allow-empty'],check=True)
    return path


def test_trusted_repository_resolves(tmp_path):
    path=repository(tmp_path)
    value=read_estimation_version_reference(path,'refs/heads/master',trusted_root=path,expected_owner=os.geteuid())
    # Do not depend on Git's initial branch setting.
    head=subprocess.check_output(['git','-C',str(path),'rev-parse','HEAD'],text=True).strip()
    value=read_estimation_version_reference(path,head,trusted_root=path,expected_owner=os.geteuid())
    assert value['commit']==head


def test_owner_writes_and_unselected_roots_never_run_git(tmp_path,monkeypatch):
    path=repository(tmp_path)
    def forbidden(*args,**kwargs):raise AssertionError('Git executed')
    monkeypatch.setattr(subprocess,'run',forbidden)
    assert read_estimation_version_reference(path,'a'*40)['commit'] is None
    assert read_estimation_version_reference(path,'a'*40,trusted_root=path,expected_owner=os.geteuid()+1)['commit'] is None
    path.chmod(0o770)
    assert read_estimation_version_reference(path,'a'*40,trusted_root=path)['commit'] is None


def test_unexpected_owner_and_external_git_inputs_rejected(tmp_path,monkeypatch):
    path=repository(tmp_path)
    def forbidden(*args,**kwargs):raise AssertionError('Git executed')
    monkeypatch.setattr(subprocess,'run',forbidden)
    assert read_estimation_version_reference(path,'a'*40,trusted_root=path,expected_owner=os.geteuid()+1)['commit'] is None
    (path/'.git/objects/info/alternates').write_text('/synthetic/untrusted\n')
    assert read_estimation_version_reference(path,'a'*40,trusted_root=path,expected_owner=os.geteuid())['commit'] is None
