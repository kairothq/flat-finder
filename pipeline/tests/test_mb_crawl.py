import gzip
import hashlib
import json
import pathlib
import threading
import time

import mb_crawl
import pytest

# padded with hex digests, not a repeated character: the cache only trusts a file over 2 KB *compressed*
NOISE = "".join(hashlib.sha1(str(i).encode()).hexdigest() for i in range(500))
REAL = "<html><body>" + mb_crawl.STATE + " = {}</body></html>" + NOISE
DENIED = "<html><title>Access Denied</title><body>You don't have permission to access this page.</body></html>"


class Resp:
    def __init__(self, html):
        self.html = html

    def read(self):
        return self.html.encode()


def serve(monkeypatch, html, tmp_path, sent=None):
    """Point the cache at tmp_path and answer every request with html."""
    monkeypatch.setattr(mb_crawl, "CACHE", tmp_path)
    monkeypatch.setattr(mb_crawl, "DELAY", 0)
    monkeypatch.setattr(mb_crawl.urllib.request, "urlopen",
                        lambda req, **kw: (sent.append(req.full_url) if sent is not None else None) or Resp(html))


def cache_file(tmp_path, url):
    return tmp_path / (hashlib.sha1(url.encode()).hexdigest() + ".html.gz")


def test_every_worker_shares_one_request_slot(monkeypatch):
    # three workers must not mean three requests a second: the gate is the whole crawl's rate limit
    monkeypatch.setattr(mb_crawl, "DELAY", 0.05)
    monkeypatch.setattr(mb_crawl, "_slot", 0.0)
    threads = [threading.Thread(target=mb_crawl.wait_turn) for _ in range(9)]
    start = time.monotonic()
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert time.monotonic() - start >= 8 * 0.05  # 9 requests cost at least 8 delays, whoever makes them


def test_a_cache_hit_takes_no_rate_slot(monkeypatch, tmp_path):
    monkeypatch.setattr(mb_crawl, "CACHE", tmp_path)
    monkeypatch.setattr(mb_crawl, "DELAY", 60)
    monkeypatch.setattr(mb_crawl.urllib.request, "urlopen",
                        lambda *a, **k: pytest.fail("asked the site for a page it already had"))
    cache_file(tmp_path, "https://x/a").write_bytes(gzip.compress(REAL.encode(), 9))
    assert mb_crawl.fetch("https://x/a") == REAL  # would sleep a minute if it asked for a slot


def test_a_block_page_is_reported_and_never_cached(monkeypatch, tmp_path):
    serve(monkeypatch, DENIED, tmp_path)
    with pytest.raises(mb_crawl.Blocked):
        mb_crawl.fetch("https://x/a")
    assert list(tmp_path.iterdir()) == []  # not cached, so a later run does not serve the block page
    assert mb_crawl.is_block(DENIED) and not mb_crawl.is_block(REAL)


def test_a_real_page_that_mentions_a_captcha_is_not_a_block(monkeypatch, tmp_path):
    page = REAL.replace("<body>", "<body>captcha widget ")
    serve(monkeypatch, page, tmp_path)
    assert mb_crawl.fetch("https://x/a") == page  # the preloaded state is what says it is a real page


def test_a_half_written_cache_file_is_refetched_instead_of_killing_the_run(monkeypatch, tmp_path):
    sent = []
    serve(monkeypatch, REAL, tmp_path, sent)
    whole = gzip.compress((NOISE * 4).encode(), 9)
    f = cache_file(tmp_path, "https://x/a")
    f.write_bytes(whole[: len(whole) // 2])  # truncated, but far over the 2 KB size test
    assert f.stat().st_size > 2000 and mb_crawl.fetch("https://x/a") == REAL
    assert sent == ["https://x/a"] and gzip.decompress(f.read_bytes()).decode() == REAL


def test_the_checkpoint_is_written_atomically(monkeypatch, tmp_path):
    f = tmp_path / "mb_projects.json"
    mb_crawl.write_atomic(f, json.dumps([{"mb_id": "1"}]))
    assert json.loads(f.read_text()) == [{"mb_id": "1"}] and list(tmp_path.glob("*.tmp")) == []

    def boom(self, data):
        raise KeyboardInterrupt  # a kill in the middle of writing the new checkpoint

    monkeypatch.setattr(pathlib.Path, "write_bytes", boom)
    with pytest.raises(KeyboardInterrupt):
        mb_crawl.write_atomic(f, json.dumps([{"mb_id": "2"}]))
    assert json.loads(f.read_text()) == [{"mb_id": "1"}]  # the previous checkpoint is still whole


def test_resume_skips_parsed_projects_and_keeps_rows_from_another_source(tmp_path):
    index = [{"url": "https://m/a"}, {"url": "https://m/b"}]
    seed = {"url": "https://www.openstreetmap.org/way/1", "mb_id": "seed-abc", "name": "My Home Bhooja"}
    rows = [{"url": "https://m/a", "name": "A", "lat": 17.4}, {"url": "https://m/b", "name": "B"}, seed]
    f = tmp_path / "mb_projects.json"
    f.write_text(json.dumps(rows))

    done, foreign = mb_crawl.resume(f, index)
    assert list(done) == ["https://m/a"]  # b has no lat, so its page was never parsed: fetch it again
    assert foreign == [seed]  # a seeded society survives a crawl restart instead of being clobbered

    mb_crawl.save(f, index, done, foreign)
    out = json.loads(f.read_text())
    assert [r["url"] for r in out] == ["https://m/a", seed["url"]]  # index order, foreign rows last


def test_resume_from_a_truncated_checkpoint_starts_over_instead_of_crashing(tmp_path):
    f = tmp_path / "mb_projects.json"
    f.write_text("")  # the 0-byte file the old non-atomic write could leave behind
    assert mb_crawl.resume(f, [{"url": "https://m/a"}]) == ({}, [])
