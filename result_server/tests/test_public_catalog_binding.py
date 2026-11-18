import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from flask import Flask

from utils.cx_persistence import catalog_for
from utils.public_delivery import PublicCatalog
from utils.result_catalog import ResultCatalog


def test_public_catalog_binding(tmp_path, monkeypatch):
    monkeypatch.setattr('utils.cx_persistence.configured_store', lambda: None)
    app = Flask(__name__)
    with app.app_context():
        app.config['PUBLIC_EXPORT_OWNER_UID'] = 123
        assert isinstance(catalog_for(tmp_path / 'catalog.db', tmp_path), PublicCatalog)


def test_regular_catalog_binding(tmp_path, monkeypatch):
    monkeypatch.setattr('utils.cx_persistence.configured_store', lambda: None)
    with Flask(__name__).app_context():
        assert type(catalog_for(tmp_path / 'catalog.db', tmp_path)) is ResultCatalog
