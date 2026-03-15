import base64

import httpx
import pytest

from moviebox_api.constants import SubjectType
from moviebox_api.providers.anime_common import (
    ResolvedMediaCandidate,
    extract_acefile_redirect_urls,
    extract_filedon_media_candidates,
    extract_filedon_media_urls,
    extract_hls_variant_candidates,
    parse_blogger_batchexecute_response,
    pixeldrain_direct_url,
    resolve_wrapped_stream_candidates,
    validate_media_candidates,
)
from moviebox_api.providers.models import ProviderStream
from moviebox_api.providers.oplovers_provider import OploversProvider
from moviebox_api.providers.otakudesu_provider import OtakudesuProvider
from moviebox_api.providers.samehadaku_provider import SamehadakuProvider


@pytest.mark.asyncio
async def test_samehadaku_search_and_resolve_streams(monkeypatch: pytest.MonkeyPatch):
    provider = SamehadakuProvider()
    encoded_iframe = base64.b64encode(
        b'<iframe src="https://cdn.example/alt-stream.mp4"></iframe>'
    ).decode()

    search_html = """
    <div class="listupd">
      <article><div class="bs"><a href="https://samehadaku.ac/anime/one-piece/"></a></div></article>
    </div>
    """
    detail_html = """
    <div class="infox">
      <h1 class="entry-title">One Piece</h1>
      <div class="alter">OP, ONE PIECE</div>
      <div class="spe">
        <span><b>Released:</b> 1999</span>
        <span><b>Status:</b> Ongoing</span>
        <span><b>Type:</b> TV</span>
        <span><b>Studio:</b> Toei</span>
        <span><b>Season:</b> Summer 1999</span>
        <span><b>Duration:</b> 24 min</span>
      </div>
    </div>
    <div class="genxed"><a>Action</a><a>Adventure</a></div>
    <div class="entry-content">Pirate adventure.</div>
    <div class="thumb"><img src="https://img.example/poster.jpg"></div>
    <div class="eplister">
      <ul><li><a href="https://samehadaku.ac/one-piece-episode-1-subtitle-indonesia/">Episode 1</a></li></ul>
    </div>
    """
    episode_html = f"""
    <div class="player-embed"><iframe src="https://cdn.example/master.m3u8"></iframe></div>
    <select class="mobius"><option value="{encoded_iframe}">720p</option></select>
    <a href="https://cdn.example/subs/one-piece.ass">subtitle</a>
    """

    async def _fake_request_text(path_or_url: str, *, referer: str | None = None):
        if '?s=' in path_or_url:
            return search_html, 'https://samehadaku.ac'
        if 'anime/one-piece' in path_or_url:
            return detail_html, 'https://samehadaku.ac'
        return episode_html, 'https://samehadaku.ac'

    monkeypatch.setattr(provider, '_request_text', _fake_request_text)

    results = await provider.search('One Piece', SubjectType.ANIME)

    assert len(results) == 1
    assert results[0].title == 'One Piece'
    assert results[0].payload['episode_count'] == 1
    assert results[0].payload['genres'] == ['Action', 'Adventure']

    streams = await provider.resolve_streams(results[0], episode=1)
    subtitles = await provider.resolve_subtitles(results[0], episode=1)

    assert [stream.url for stream in streams] == [
        'https://cdn.example/master.m3u8',
        'https://cdn.example/alt-stream.mp4',
    ]
    assert subtitles[0].url == 'https://cdn.example/subs/one-piece.ass'


@pytest.mark.asyncio
async def test_oplovers_search_and_resolve_streams(monkeypatch: pytest.MonkeyPatch):
    provider = OploversProvider()

    async def _fake_search_via_index(query: str, *, year: int | None, limit: int):
        assert query == 'Solo Leveling'
        assert year is None
        assert limit == 20
        return [
            provider._result_from_api_entry(
                {
                    'id': 'op-1',
                    'slug': 'solo-leveling',
                    'title': 'Solo Leveling',
                    'japaneseTitle': 'Ore dake Level Up na Ken',
                    'description': 'Hunter story.',
                    'releaseDate': '2024-01-01',
                    'status': 'Completed',
                    'poster': 'https://img.example/solo.jpg',
                    'duration': '24 min',
                    'releaseType': 'TV',
                    'score': 8.9,
                    'genres': [{'name': 'Action'}, {'name': 'Fantasy'}],
                    'studio': {'name': 'A-1 Pictures'},
                    'season': {'name': 'Winter'},
                    'totalEpisodes': 12,
                }
            )
        ]

    async def _fake_content_payload(content_kind: str, slug: str):
        assert content_kind == 'series'
        assert slug == 'solo-leveling'
        return {
            'episodes': [
                {
                    'episodeNumber': 1,
                    'streamUrl': [
                        {'url': 'https://stream.example/embed/solo-1', 'source': 'desu'}
                    ],
                    'downloadUrl': [
                        {
                            'format': 'mp4',
                            'resolutions': [
                                {
                                    'quality': '720p',
                                    'download_links': [
                                        {'url': 'https://cdn.example/solo-1.mp4', 'host': 'kraken'}
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(provider, '_search_via_index', _fake_search_via_index)
    monkeypatch.setattr(provider, '_content_payload', _fake_content_payload)

    results = await provider.search('Solo Leveling', SubjectType.ANIME)
    assert len(results) == 1
    assert results[0].title == 'Solo Leveling'
    assert results[0].payload['episode_count'] == 12

    streams = await provider.resolve_streams(results[0], episode=1)

    assert len(streams) == 2
    assert streams[0].quality == '720p'
    assert streams[0].url == 'https://cdn.example/solo-1.mp4'
    assert streams[1].url == 'https://stream.example/embed/solo-1'


@pytest.mark.asyncio
async def test_base_anime_provider_request_falls_back_to_sync_client(monkeypatch: pytest.MonkeyPatch):
    provider = OtakudesuProvider()

    class _FailingAsyncClient:
        def __init__(self, *args, **kwargs):
            self.headers = kwargs.get('headers', {})

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str):
            raise httpx.ReadTimeout('async timeout', request=httpx.Request('GET', url))

    class _SyncClient:
        def __init__(self, *args, **kwargs):
            self.headers = kwargs.get('headers', {})

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url: str):
            assert self.headers.get('Referer') == 'https://otakudesu.pl'
            return httpx.Response(
                200,
                text='<html>ok</html>',
                request=httpx.Request('GET', url),
            )

    monkeypatch.setattr('moviebox_api.providers.anime_common.httpx.AsyncClient', _FailingAsyncClient)
    monkeypatch.setattr('moviebox_api.providers.anime_common.httpx.Client', _SyncClient)

    html, base_url = await provider._request_text('https://otakudesu.pl/episode/test/', referer='https://otakudesu.pl')

    assert html == '<html>ok</html>'
    assert base_url == 'https://otakudesu.blog'


@pytest.mark.asyncio
async def test_resolve_wrapped_stream_candidates_follows_desustream_blogger(
    monkeypatch: pytest.MonkeyPatch,
):
    provider = OtakudesuProvider()
    desustream_html = (
        '<iframe src="https://www.blogger.com/video.g?token=demo-token&amp;origin=desu.example"></iframe>'
    )
    blogger_html = 'ignored'

    async def _fake_request_text(path_or_url: str, *, referer: str | None = None):
        if 'desustream.info' in path_or_url:
            return desustream_html, 'https://desustream.info'
        if 'blogger.com/video.g' in path_or_url:
            return blogger_html, 'https://www.blogger.com'
        raise AssertionError(path_or_url)

    async def _fake_extract_blogger(provider_obj, url: str, html: str, *, referer: str | None = None):
        return [
            parse_blogger_batchexecute_response(
                r""")]}'

2589
[["wrb.fr","WcwnYd","[1,null,[[\"https://rr1---sn.example.googlevideo.com/videoplayback?itag\u003d18\u0026source\u003dblogger\",[18]],[\"https://rr1---sn.example.googlevideo.com/videoplayback?itag\u003d22\u0026source\u003dblogger\",[22]]],\"thumb\",\"BLOGGER-video-demo\",\"demo\"]",null,null,null,"generic"]]
26
[["e",4,null,null,0]]"""
            )
        ][0]

    async def _fake_validate(candidates, *, referer: str | None = None):
        return candidates

    monkeypatch.setattr(provider, '_request_text', _fake_request_text)
    monkeypatch.setattr(
        'moviebox_api.providers.anime_common.extract_blogger_media_candidates',
        _fake_extract_blogger,
    )
    monkeypatch.setattr('moviebox_api.providers.anime_common.validate_media_candidates', _fake_validate)

    candidates = await resolve_wrapped_stream_candidates(
        provider,
        'https://desustream.info/dstream/ondesu/v5/index.php?id=demo',
        referer='https://otakudesu.blog/episode/demo/',
    )

    assert [candidate.quality for candidate in candidates] == ['360p', '720p']
    assert candidates[0].url.startswith('https://rr1---sn.example.googlevideo.com/videoplayback')


@pytest.mark.asyncio
async def test_otakudesu_search_supports_blog_layout(monkeypatch: pytest.MonkeyPatch):
    provider = OtakudesuProvider()

    search_html = """
    <div class="chivsrc">
      <li>
        <h2>
          <a href="https://otakudesu.blog/anime/jjk-s3-sub-indo/">
            Jujutsu Kaisen Season 3 Subtitle Indonesia
          </a>
        </h2>
      </li>
    </div>
    """
    detail_html = """
    <title>Jujutsu Kaisen Season 3 Subtitle Indonesia | Otaku Desu</title>
    <meta name="description" content="Jujutsu Kaisen Season 3 summary." />
    <img class="wp-post-image" src="https://img.example/jjk-s3.jpg" />
    <div class="infozingle">
      <p><span><b>Judul</b>: Jujutsu Kaisen Season 3</span></p>
      <p><span><b>Japanese</b>: ???? ????? ???</span></p>
      <p><span><b>Skor</b>: 7.57</span></p>
      <p><span><b>Tipe</b>: TV</span></p>
      <p><span><b>Status</b>: Ongoing</span></p>
      <p><span><b>Tanggal Rilis</b>: Jan 09, 2026</span></p>
      <p><span><b>Studio</b>: MAPPA</span></p>
      <p><span><b>Genre</b>: <a rel="tag">Action</a>, <a rel="tag">Supernatural</a></span></p>
    </div>
    <a href="https://otakudesu.blog/episode/jjtsu-ksn-s3-episode-1-sub-indo/">Episode 1</a>
    """
    episode_html = """
    <div class="download"><ul>
      <li>
        <strong>Mp4 1080p</strong>
        <a href="https://pixeldrain.com/u/jjk1080">Pdrain</a>
      </li>
      <li>
        <strong>Mp4 720p</strong>
        <a href="https://acefile.co/f/jjk720">Acefile</a>
      </li>
    </ul></div>
    <iframe src="https://cdn.example/master.m3u8"></iframe>
    <a href="https://cdn.example/subs/jjk-s3.vtt">subtitle</a>
    """

    async def _fake_request_text(path_or_url: str, *, referer: str | None = None):
        if '?s=' in path_or_url:
            return search_html, 'https://otakudesu.blog'
        if '/anime/jjk-s3-sub-indo/' in path_or_url:
            return detail_html, 'https://otakudesu.blog'
        return episode_html, 'https://otakudesu.blog'

    async def _fake_expand_streams(
        *,
        url: str,
        source: str,
        quality: str | None = None,
        referer: str | None = None,
        subtitles=None,
    ):
        return [
            provider.make_stream(
                url=url,
                source=source,
                quality=quality,
                headers={'Referer': referer or url},
                subtitles=subtitles,
            )
        ]

    monkeypatch.setattr(provider, '_request_text', _fake_request_text)
    monkeypatch.setattr(provider, 'expand_streams', _fake_expand_streams)

    results = await provider.search('Jujutsu Kaisen Season 3', SubjectType.ANIME)

    assert len(results) == 1
    assert results[0].title == 'Jujutsu Kaisen Season 3'
    assert results[0].year == 2026
    assert results[0].payload['genres'] == ['Action', 'Supernatural']
    assert results[0].payload['rating'] == 7.57

    streams = await provider.resolve_streams(results[0], episode=1)
    subtitles = await provider.resolve_subtitles(results[0], episode=1)

    assert [stream.quality for stream in streams[:3]] == ['1080p', '720p', None]
    assert streams[0].url == 'https://pixeldrain.com/u/jjk1080'
    assert streams[1].url == 'https://acefile.co/f/jjk720'
    assert streams[2].url == 'https://cdn.example/master.m3u8'
    assert subtitles[0].url == 'https://cdn.example/subs/jjk-s3.vtt'


@pytest.mark.asyncio
async def test_otakudesu_search_and_resolve_streams(monkeypatch: pytest.MonkeyPatch):
    provider = OtakudesuProvider()

    search_html = """
    <article><a href="https://otakudesu.pl/series/blue-lock/"></a></article>
    """
    detail_html = """
    <title>Blue Lock - Otakudesu</title>
    <div class="spe">
      <span>Released: 2022</span>
      <span>Status: Completed</span>
      <span>Type: TV</span>
      <span>Studio: Eight Bit</span>
      <span>Season: Fall 2022</span>
      <span>Duration: 24 min</span>
    </div>
    <div class="genxed"><a>Sports</a><a>Drama</a></div>
    <div class="entry-content">Striker project.</div>
    <div class="thumb"><img src="https://img.example/blue-lock.jpg"></div>
    <a href="https://otakudesu.pl/episode/blue-lock-episode-1/">Blue Lock Episode 1</a>
    """
    episode_html = """
    <iframe src="https://video.example/blue-lock-1"></iframe>
    <a href="https://cdn.example/subs/blue-lock.vtt">subtitle</a>
    """

    async def _fake_request_text(path_or_url: str, *, referer: str | None = None):
        if '?s=' in path_or_url:
            return search_html, 'https://otakudesu.pl'
        if 'series/blue-lock' in path_or_url:
            return detail_html, 'https://otakudesu.pl'
        return episode_html, 'https://otakudesu.pl'

    monkeypatch.setattr(provider, '_request_text', _fake_request_text)

    results = await provider.search('Blue Lock', SubjectType.ANIME)
    assert len(results) == 1
    assert results[0].title == 'Blue Lock'
    assert results[0].payload['genres'] == ['Sports', 'Drama']

    streams = await provider.resolve_streams(results[0], episode=1)
    subtitles = await provider.resolve_subtitles(results[0], episode=1)

    assert len(streams) == 1
    assert streams[0].url == 'https://video.example/blue-lock-1'
    assert subtitles[0].url == 'https://cdn.example/subs/blue-lock.vtt'


def test_pixeldrain_direct_url():
    assert pixeldrain_direct_url('https://pixeldrain.com/u/PG935d7E') == 'https://pixeldrain.com/api/file/PG935d7E'


def test_extract_filedon_media_urls():
    html = (
        '&quot;url&quot;:&quot;https://filedon.example/video.mp4?token=123&quot; '
        '&quot;url&quot;:&quot;https://filedon.example/preview.jpg&quot;'
    )
    assert extract_filedon_media_urls(html) == ['https://filedon.example/video.mp4?token=123']


@pytest.mark.asyncio
async def test_extract_filedon_media_candidates_resolves_signed_r2_url(monkeypatch: pytest.MonkeyPatch):
    share_html = (
        '<div id="app" '
        'data-page="{&quot;props&quot;:{&quot;sharing&quot;:{&quot;slug&quot;:&quot;WxKYXcqGU3&quot;}}}"></div>'
    )
    redirect_html = (
        '<div id="app" data-page="{&quot;props&quot;:{&quot;flash&quot;:{&quot;download_url&quot;:&quot;'
        'https://filedon.r2.example/video.mp4?token=123&quot;}}}"></div>'
    )

    class _FakeResponse:
        def __init__(
            self,
            *,
            status_code: int,
            text: str = '',
            headers: dict[str, str] | None = None,
            url: str,
        ):
            self.status_code = status_code
            self.text = text
            self.headers = headers or {}
            self.url = url

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            self.cookies = {'XSRF-TOKEN': 'token%20value'}
            self._view_requests = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str, headers: dict[str, str] | None = None):
            if url.endswith('/sanctum/csrf-cookie'):
                return _FakeResponse(status_code=204, url=url)
            if url.endswith('/view/WxKYXcqGU3'):
                self._view_requests += 1
                return _FakeResponse(
                    status_code=200,
                    text=share_html if self._view_requests == 1 else redirect_html,
                    url=url,
                )
            raise AssertionError(f'unexpected GET {url}')

        async def post(self, url: str, headers: dict[str, str] | None = None):
            assert url.endswith('/download/WxKYXcqGU3')
            assert headers is not None
            assert headers.get('X-XSRF-TOKEN') == 'token value'
            return _FakeResponse(
                status_code=302,
                headers={'location': 'https://filedon.co/view/WxKYXcqGU3'},
                url=url,
            )

    monkeypatch.setattr('moviebox_api.providers.anime_common.httpx.AsyncClient', _FakeClient)

    candidates = await extract_filedon_media_candidates(
        'https://filedon.co/view/WxKYXcqGU3',
        share_html,
        referer='https://coba.oploverz.ltd/',
    )

    assert [candidate.url for candidate in candidates] == [
        'https://filedon.r2.example/video.mp4?token=123'
    ]


def test_extract_acefile_redirect_urls(monkeypatch: pytest.MonkeyPatch):
    html = (
        "<script>eval(function(p,a,c,k,e,d){return p}("
        "'payload',1,1,'direct'.split('|'),0,{}))</script>"
    )

    monkeypatch.setattr(
        'moviebox_api.providers.anime_common._unpack_packer_script',
        lambda _script: 'var DUAR={"AceFile":[{"direct":"/service/redirect/111/222/hash"}]};',
    )

    assert extract_acefile_redirect_urls(html, base_url='https://acefile.co') == [
        'https://acefile.co/service/redirect/111/222/hash'
    ]


def test_oplovers_prefers_non_gdrive_streams_when_same_quality_exists():
    provider = OploversProvider()
    streams = [
        ProviderStream(
            url='https://drive.google.com/uc?export=download&id=abc123',
            source='oplovers:gd:direct',
            quality='720p',
        ),
        ProviderStream(
            url='https://filedon.example/video-720.mp4',
            source='oplovers:filedon:direct',
            quality='720p',
        ),
        ProviderStream(
            url='https://drive.google.com/uc?export=download&id=def456',
            source='oplovers:gd:direct',
            quality='480p',
        ),
    ]

    filtered = provider._prefer_non_gdrive_streams(streams)

    assert [stream.url for stream in filtered] == [
        'https://filedon.example/video-720.mp4',
        'https://drive.google.com/uc?export=download&id=def456',
    ]


def test_oplovers_episode_entries_use_numeric_episode_numbers():
    provider = OploversProvider()

    entries = provider._episode_entries_from_payload(
        {
            'series': {'title': 'Solo Leveling'},
            'episodes': [
                {'episodeNumber': 1, 'title': 'Episode 1'},
                {'episodeNumber': 2, 'title': 'Episode 2'},
            ],
        },
        slug='solo-leveling',
        content_kind='series',
    )

    assert [entry['number'] for entry in entries] == [1, 2]
    assert entries[1]['url'].endswith('/series/solo-leveling/episode/2')


@pytest.mark.asyncio
async def test_validate_media_candidates_drops_audio_only_responses(monkeypatch: pytest.MonkeyPatch):
    class _FakeResponse:
        def __init__(self, status_code: int, content_type: str):
            self.status_code = status_code
            self.headers = {'content-type': content_type}

    class _FakeStreamContext:
        def __init__(self, response: _FakeResponse):
            self._response = response

        async def __aenter__(self):
            return self._response

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method: str, url: str, headers: dict[str, str] | None = None):
            content_type = 'audio/mp4' if 'audio-only' in url else 'application/vnd.apple.mpegurl'
            return _FakeStreamContext(_FakeResponse(200, content_type))

    monkeypatch.setattr('moviebox_api.providers.anime_common.httpx.AsyncClient', _FakeClient)

    candidates = await validate_media_candidates(
        [
            ResolvedMediaCandidate(url='https://cdn.example/audio-only'),
            ResolvedMediaCandidate(url='https://cdn.example/playlist'),
        ],
        referer='https://provider.example/episode-1',
    )

    assert [candidate.url for candidate in candidates] == ['https://cdn.example/playlist']
    assert candidates[0].stream_type == 'hls'


def test_extract_hls_variant_candidates():
    playlist_text = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=1443142,RESOLUTION=1280x720
index-v1-a1.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=533142,RESOLUTION=854x480
index-v2-a1.m3u8
"""

    candidates = extract_hls_variant_candidates(
        playlist_text,
        base_url='https://cdn.example/master.m3u8',
        headers={'Referer': 'https://provider.example/episode-1'},
    )

    assert [candidate.quality for candidate in candidates] == ['720p', '480p']
    assert [candidate.url for candidate in candidates] == [
        'https://cdn.example/index-v1-a1.m3u8',
        'https://cdn.example/index-v2-a1.m3u8',
    ]


def test_parse_blogger_batchexecute_response_returns_direct_googlevideo_urls():
    response_text = r""")]}'

2589
[["wrb.fr","WcwnYd","[1,null,[[\"https://rr1---sn.example.googlevideo.com/videoplayback?itag\u003d18\u0026source\u003dblogger\",[18]],[\"https://rr1---sn.example.googlevideo.com/videoplayback?itag\u003d22\u0026source\u003dblogger\",[22]]],\"thumb\",\"BLOGGER-video-demo\",\"demo\"]",null,null,null,"generic"]]
26
[["e",4,null,null,0]]"""

    candidates = parse_blogger_batchexecute_response(response_text)

    assert [candidate.quality for candidate in candidates] == ['360p', '720p']
    assert candidates[0].url.startswith('https://rr1---sn.example.googlevideo.com/videoplayback')
