"""Settings > Refresh cached data (lib/ui/cacherefresh.py)."""
import os

from tests.kodistubs import install_kodi_stubs


def test_refresh_deletes_the_cache_files_and_keeps_the_rest(tmp_path, monkeypatch):
    with install_kodi_stubs(reload=('lib.ui.compat', 'lib.ui.cacherefresh')) as ctx:
        import lib.ui.cacherefresh as cacherefresh
        for name in cacherefresh.CACHE_FILES + ('auth.json', 'progress.json'):
            (tmp_path / name).write_text('{}')
        monkeypatch.setattr(cacherefresh, '_cache_dirs', lambda: [str(tmp_path)])
        import lib.ui.logocheck as logocheck
        logocheck.remember('https://img/a.png', True)

        cacherefresh.refresh_from_settings()

        left = sorted(os.listdir(str(tmp_path)))
        assert left == ['auth.json', 'progress.json']
        assert logocheck.state('https://img/a.png') is None
        assert ctx.env.addon.getSetting('cache_generation') != ''
        assert ctx.env.notifications[-1][1] == 'STR30501'


def test_home_drops_its_memory_when_the_generation_changes(monkeypatch):
    from tests.test_homewindow import _RELOAD_MODULE_NAMES

    with install_kodi_stubs(reload=_RELOAD_MODULE_NAMES + ('lib.ui.cacherefresh',)) as ctx:
        hw = ctx.homewindow
        cleared = []
        import lib.ui.cacherefresh as cacherefresh
        monkeypatch.setattr(cacherefresh, 'clear_memory', lambda: cleared.append(True))
        win = hw.HomeWindow('HomeWindow.xml', '/addon/path', 'Default', '1080i')

        hw._drop_memory_if_refreshed(win)          # first build: just records
        assert cleared == []
        ctx.env.addon.setSetting('cache_generation', '123')
        hw._drop_memory_if_refreshed(win)
        assert cleared == [True]
        assert 'cache_generation' in hw._ROW_SETTINGS   # so the rows rebuild too
