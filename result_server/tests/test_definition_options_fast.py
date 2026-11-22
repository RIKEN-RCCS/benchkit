from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from utils import app_support_matrix,report_selection


def test_names_match_support_matrix_without_parsing_scripts(tmp_path,monkeypatch):
    systems=tmp_path/'system.csv';systems.write_text('system\nZ\nA\nZ\n')
    for name in ['beta','Alpha','no-list']:
        root=tmp_path/name;root.mkdir()
        if name!='no-list':
            (root/'list.csv').write_text('system,enable\nA,yes\n')
            (root/'build.sh').write_text('case "$system" in\nA) ;;\nesac\n')
            (root/'run.sh').write_text('case "$system" in\nA) ;;\nesac\n')
    expected_systems,matrix=app_support_matrix.load_app_system_support_matrix(tmp_path,systems)
    def forbidden(*args):raise AssertionError('Candidate names must not parse scripts')
    monkeypatch.setattr(app_support_matrix,'_file_mentions_system',forbidden)
    actual_systems,apps=app_support_matrix.load_app_system_definitions(tmp_path,systems)
    assert actual_systems==expected_systems and apps==[row['app'] for row in matrix]
    monkeypatch.setattr(report_selection,'load_app_system_definitions',lambda:(actual_systems,apps))
    assert report_selection.definition_options('selected','new-system','case')=={
        'systems':['A','Z','new-system'],'codes':['Alpha','beta','selected'],'exps':['case']}


def test_definition_changes_are_visible_without_restart_or_user_cache(tmp_path):
    systems=tmp_path/'system.csv';systems.write_text('system\nA\n')
    assert app_support_matrix.load_app_system_definitions(tmp_path,systems)==(['A'],[])
    root=tmp_path/'new-app';root.mkdir();(root/'list.csv').write_text('system,enable\nA,no\n')
    assert app_support_matrix.load_app_system_definitions(tmp_path,systems)==(['A'],['new-app'])
