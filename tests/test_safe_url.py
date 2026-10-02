import pytest

from core import web


@pytest.mark.parametrize("url", ["file:///C:/Windows/System32/calc.exe", "ms-settings:privacy", "search-ms:query=x",
                                 "javascript:alert(1)"])
def test_system_protocols_are_refused(url):
    with pytest.raises(web.WebError):
        web.safe_url(url)


def test_plain_sites_pass_and_get_https():
    assert web.safe_url("youtube.com/watch?v=1") == "https://youtube.com/watch?v=1"
    assert web.safe_url("http://example.com") == "http://example.com"


@pytest.mark.parametrize("url", ["http://127.0.0.1:11434/api/tags", "http://192.168.1.1", "http://localhost"])
def test_model_cannot_read_local_network(url):
    with pytest.raises(web.WebError):
        web.safe_url(url, allow_local=False)
