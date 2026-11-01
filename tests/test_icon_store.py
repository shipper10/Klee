import asyncio
import io
import json

from aiohttp import web
from aiohttp.test_utils import TestServer
from genshin.models.genshin import constants as gc
from PIL import Image

from app import icon_sync, images
from app.asset_store import AssetStore, key_for_url


def png(color=(200, 50, 50)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), color).save(buf, "PNG")
    return buf.getvalue()


class FakeFiles:
    def __init__(self, objects):
        self.objects = objects

    async def download(self, key):
        if key not in self.objects:
            raise KeyError(key)
        return self.objects[key]

    async def upload(self, key, data, opts=None):
        self.objects[key] = data

    async def list(self, folder, opts=None):
        pre = folder + "/"
        names = [k[len(pre):] for k in self.objects if k.startswith(pre)]
        off = (opts or {}).get("offset", 0)
        return [{"name": n} for n in names][off:off + (opts or {}).get("limit", 1000)]


class FakeStorage:
    def __init__(self):
        self.objects = {}
        self.created = []

    def from_(self, bucket):
        return FakeFiles(self.objects)

    async def create_bucket(self, name, options=None):
        self.created.append(name)


def make_store():
    st = FakeStorage()
    return st, AssetStore(st)


def test_key_is_storage_safe_and_stable():
    k = key_for_url("https://enka.network/ui/UI_AvatarIcon_Furina.png")
    assert k == "icons/enka.network_ui_UI_AvatarIcon_Furina.png" and key_for_url("https://enka.network/ui/UI_AvatarIcon_Furina.png") == k
    assert "?" not in key_for_url("https://a.com/x.png?token=1&b=2")


async def test_downloaded_icon_is_saved_then_served_from_store(monkeypatch):
    hits = []

    async def ok(request):
        hits.append(1)
        return web.Response(body=png(), content_type="image/png")

    app = web.Application()
    app.router.add_get("/a.png", ok)
    st, store = make_store()
    async with TestServer(app) as server:
        monkeypatch.setattr(images, "is_allowed_url", lambda u: True)
        url = str(server.make_url("/a.png"))
        f1 = images.ImageFetcher(store=store)
        assert (await f1.fetch_first([("k", [url])])).images["k"] == png()
        await f1.close()
        assert key_for_url(url) in st.objects and len(hits) == 1
        # a fresh process (empty memory) must not hit the network again
        f2 = images.ImageFetcher(store=store)
        assert (await f2.fetch_first([("k", [url])])).images["k"] == png()
        await f2.close()
        assert len(hits) == 1


async def test_corrupt_stored_copy_is_ignored_and_refetched(monkeypatch):
    async def ok(request):
        return web.Response(body=png(), content_type="image/png")

    app = web.Application()
    app.router.add_get("/a.png", ok)
    st, store = make_store()
    async with TestServer(app) as server:
        monkeypatch.setattr(images, "is_allowed_url", lambda u: True)
        url = str(server.make_url("/a.png"))
        st.objects[key_for_url(url)] = b"garbage"
        f = images.ImageFetcher(store=store)
        assert (await f.fetch_first([("k", [url])])).images["k"] == png()
        await f.close()
        assert st.objects[key_for_url(url)] == png()  # repaired


async def test_recently_failed_url_is_not_retried_immediately(monkeypatch):
    hits = []

    async def gone(request):
        hits.append(1)
        return web.Response(status=404)

    app = web.Application()
    app.router.add_get("/x.png", gone)
    async with TestServer(app) as server:
        monkeypatch.setattr(images, "is_allowed_url", lambda u: True)
        url = str(server.make_url("/x.png"))
        f = images.ImageFetcher()
        await f.fetch_first([("k", [url])])
        res = await f.fetch_first([("k", [url])])
        await f.close()
    assert len(hits) == 1 and res.failed == 1


async def test_store_errors_never_break_fetching(monkeypatch):
    class Broken:
        def from_(self, b):
            raise RuntimeError("down")

        async def create_bucket(self, *a, **k):
            raise RuntimeError("down")

    store = AssetStore(Broken())
    await store.ensure_bucket()
    assert await store.get("icons/x") is None and await store.put("icons/x", b"1") is False
    assert await store.list_keys("icons") == set()


async def test_sync_downloads_only_missing_and_force_redownloads(monkeypatch):
    gc.CHARACTER_NAMES = {"en-us": {
        1: gc.DBChar(1, "Ayaka", "Ayaka", "Cryo", 5),
        2: gc.DBChar(2, "Lisa", "Lisa", "Electro", 4),
        3: gc.DBChar(3, "PlayerBoy", "Traveler", "", 5),
    }}

    async def no_update(langs):
        return None

    monkeypatch.setattr(icon_sync.extdb, "update_characters_any", no_update)
    st, store = make_store()
    st.objects[key_for_url(icon_sync.icon_url("Ayaka"))] = png()
    f = images.ImageFetcher(store=store)
    calls = []

    async def fake_refresh(url):
        calls.append(url)
        return ("Lisa" in url), "HTTP 404"

    monkeypatch.setattr(f, "refresh", fake_refresh)
    rep = await icon_sync.sync_icons(f, store)
    assert rep.characters == 2 and rep.already_stored == 1 and rep.downloaded == 1 and rep.failed == 0
    assert calls == [icon_sync.icon_url("Lisa")] and "meta/characters.json" in st.objects
    calls.clear()
    rep = await icon_sync.sync_icons(f, store, force=True)
    assert len(calls) == 2 and rep.failed == 1 and "brand-new" in rep.text()


async def test_character_table_restored_from_store():
    st, store = make_store()
    gc.CHARACTER_NAMES = {"en-us": {5: gc.DBChar(5, "Nilou", "Nilou", "Hydro", 5)}}
    st.objects["meta/characters.json"] = json.dumps(gc.CHARACTER_NAMES).encode()
    gc.CHARACTER_NAMES = {}
    assert await icon_sync.load_saved_table(store)
    assert gc.CHARACTER_NAMES["en-us"][5].icon_name == "Nilou"
