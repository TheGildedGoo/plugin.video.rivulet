"""The optional Pillow texture check validates drawings without writing files."""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def drawings():
    pytest.importorskip('PIL')
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('dialog_textures', root / 'tools/make_dialog_textures.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_shipped_dialog_textures_check_without_writing(drawings):
    paths = [Path(drawings.MEDIA) / name for name in drawings.textures()]
    before = {path: path.read_bytes() for path in paths}
    assert drawings.main(['--check']) == 0
    assert before == {path: path.read_bytes() for path in paths}


def test_check_names_missing_files_without_creating_a_directory(drawings, monkeypatch, tmp_path, capsys):
    folder = tmp_path / 'missing'
    monkeypatch.setattr(drawings, 'MEDIA', str(folder))
    assert drawings.main(['--check']) == 1
    assert not folder.exists()
    assert 'dlg_panel.png' in capsys.readouterr().out


def test_check_detects_mismatched_pixels_without_rewriting(drawings, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(drawings, 'MEDIA', str(tmp_path))
    assert drawings.main([]) == 0
    path = tmp_path / 'dlg_panel.png'
    path.write_bytes(b'not an image')
    before = {p: p.read_bytes() for p in tmp_path.iterdir()}
    assert drawings.main(['--check']) == 1
    assert 'dlg_panel.png' in capsys.readouterr().out
    assert before == {p: p.read_bytes() for p in tmp_path.iterdir()}
