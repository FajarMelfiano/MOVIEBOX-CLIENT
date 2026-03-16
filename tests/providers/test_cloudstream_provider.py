import base64
from urllib.parse import parse_qs

import httpx
import pytest

from moviebox_api.constants import SubjectType
from moviebox_api.providers import cloudstream_core as cloudstream_core_module
from moviebox_api.providers.cloudstream_provider import CloudstreamProvider
from moviebox_api.providers.models import ProviderSearchResult


def _build_client(handler) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(
        transport=transport,
        headers={'User-Agent': 'pytest'},
        follow_redirects=True,
        timeout=10.0,
    )


def _search_page(*articles: str) -> str:
    return '<html><body>{}</body></html>'.format(''.join(articles))


def _article(
    title: str,
    href: str,
    *,
    rating: str = '8.4',
    quality: str = '',
    episode_badge: str = '',
) -> str:
    quality_html = f'<div class="gmr-qual">{quality}</div>' if quality else ''
    episode_html = f'<div class="gmr-numbeps"><span>{episode_badge}</span></div>' if episode_badge else ''
    return f'''        <article class="item">
            <a href="{href}"><img src="https://img.example/{title.replace(' ', '-').lower()}.jpg"></a>
            <h2 class="entry-title"><a href="{href}">{title}</a></h2>
            <div class="gmr-rating-item">{rating}</div>
            {quality_html}
            {episode_html}
        </article>
    '''


def _movie_page(*, title: str, post_id: str, year: int = 2020, genres: tuple[str, ...] = ('Action',)) -> str:
    genre_links = ''.join(f'<a href="/genre/{genre.lower()}/">{genre}</a>' for genre in genres)
    return f'''        <html>
            <h1 class="entry-title">{title} ({year})</h1>
            <div class="gmr-moviedata">Year: <a>{year}</a> Genre: {genre_links}</div>
            <figure class="pull-left">
                <img src="https://img.example/{title.replace(' ', '-').lower()}.jpg">
            </figure>
            <div itemprop="description"><p>{title} synopsis.</p></div>
            <div id="muvipro_player_content_id" data-id="{post_id}"></div>
            <ul class="muvipro-player-tabs">
                <li><a href="#p1">Server 1</a></li>
            </ul>
            <div id="p1" class="tab-content-ajax"></div>
        </html>
    '''


def _series_page(*, title: str, episode_links: list[tuple[int, str]], year: int = 2021) -> str:
    links_html = ''.join(
        f'<a href="{href}">Episode {episode}</a>'
        for episode, href in episode_links
    )
    return f'''        <html>
            <h1 class="entry-title">{title}</h1>
            <div class="gmr-moviedata">Year: <a>{year}</a></div>
            <div class="gmr-listseries">{links_html}</div>
        </html>
    '''


def _master_playlist(*, include_subtitles: bool = False, qualities: tuple[int, ...] = (1080, 720)) -> str:
    lines = ['#EXTM3U']
    if include_subtitles:
        lines.append(
            '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English",LANGUAGE="en",URI="subs/en.vtt"'
        )
    for quality in qualities:
        width = 1920 if quality >= 1080 else 1280 if quality >= 720 else 854
        lines.append(f'#EXT-X-STREAM-INF:BANDWIDTH=2800000,RESOLUTION={width}x{quality}')
        lines.append(f'{quality}.m3u8')
    return '\n'.join(lines) + '\n'


@pytest.mark.asyncio
async def test_search_best_match_revalidates_ambiguous_series_results():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == 'filmkita.cloud' and request.url.path == '/':
            html = _search_page(_article('Arcane Season 1', '/arcane-season-1/'))
            return httpx.Response(200, text=html, headers={'Content-Type': 'text/html'})
        if request.url.host == 'filmkita.cloud' and request.url.path == '/arcane-season-1/':
            html = _series_page(
                title='Arcane Season 1',
                episode_links=[(1, '/arcane-season-1-episode-1/'), (2, '/arcane-season-1-episode-2/')],
            )
            return httpx.Response(200, text=html, headers={'Content-Type': 'text/html'})
        raise AssertionError(f'Unexpected request: {request.method} {request.url}')

    provider = CloudstreamProvider(client=_build_client(handler), base_urls=('https://filmkita.cloud',))

    item = await provider.search_best_match('Arcane', SubjectType.TV_SERIES)

    assert item is not None
    assert item.title == 'Arcane'
    assert item.subject_type == SubjectType.TV_SERIES
    assert item.year == 2021
    assert item.payload['episodes'][0]['episode'] == 1


@pytest.mark.asyncio
async def test_resolve_movie_streams_uses_earnvids_and_manifest_subtitles():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == 'filmkita.cloud' and request.url.path == '/greyhound/':
            return httpx.Response(
                200,
                text=_movie_page(title='Greyhound', post_id='74464'),
                headers={'Content-Type': 'text/html'},
            )
        if request.url.host == 'filmkita.cloud' and request.url.path == '/wp-admin/admin-ajax.php':
            payload = parse_qs(request.content.decode())
            assert payload == {'action': ['muvipro_player_content'], 'tab': ['p1'], 'post_id': ['74464']}
            html = '<div class="gmr-embed-responsive"><iframe src="https://bingezove.com/d/abc123"></iframe></div>'
            return httpx.Response(200, text=html, headers={'Content-Type': 'text/html'})
        if request.url.host == 'bingezove.com' and request.url.path == '/v/abc123':
            html = '<script>var sources=[{file:"https://media.example/playlist/master.m3u8"}]</script>'
            return httpx.Response(200, text=html, headers={'Content-Type': 'text/html'})
        if request.url.host == 'media.example' and request.url.path == '/playlist/master.m3u8':
            return httpx.Response(
                200,
                text=_master_playlist(include_subtitles=True, qualities=(1080, 720)),
                headers={'Content-Type': 'application/vnd.apple.mpegurl'},
            )
        raise AssertionError(f'Unexpected request: {request.method} {request.url}')

    provider = CloudstreamProvider(client=_build_client(handler), base_urls=('https://filmkita.cloud',))
    item = ProviderSearchResult(
        id='https://filmkita.cloud/greyhound/',
        title='Greyhound',
        page_url='https://filmkita.cloud/greyhound/',
        subject_type=SubjectType.MOVIES,
        year=2020,
    )

    streams = await provider.resolve_streams(item)
    subtitles = await provider.resolve_subtitles(item)

    assert [stream.quality for stream in streams] == ['1080p', '720p']
    assert streams[0].source == 'cloudstream:bingezove'
    assert streams[0].url == 'https://media.example/playlist/1080.m3u8'
    assert streams[0].headers['Referer'] == 'https://bingezove.com/v/abc123'
    assert [subtitle.url for subtitle in subtitles] == ['https://media.example/playlist/subs/en.vtt']


@pytest.mark.asyncio
async def test_resolve_series_streams_selects_requested_episode_and_layarwibu_order():
    encoded_target = base64.b64encode(b'https://cdn.example/series/master.m3u8').decode()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == 'filmkita.cloud' and request.url.path == '/reacher-season-2/':
            return httpx.Response(
                200,
                text=_series_page(
                    title='Reacher Season 2',
                    episode_links=[
                        (1, '/reacher-season-2-episode-1/'),
                        (2, '/reacher-season-2-episode-2/'),
                    ],
                    year=2022,
                ),
                headers={'Content-Type': 'text/html'},
            )
        if request.url.host == 'filmkita.cloud' and request.url.path == '/reacher-season-2-episode-2/':
            return httpx.Response(
                200,
                text=_movie_page(title='Reacher Episode 2', post_id='2002', year=2022),
                headers={'Content-Type': 'text/html'},
            )
        if request.url.host == 'filmkita.cloud' and request.url.path == '/wp-admin/admin-ajax.php':
            payload = parse_qs(request.content.decode())
            if payload.get('post_id') == ['2002']:
                html = (
                    '<div class="gmr-embed-responsive"><iframe '
                    f'src="https://hls-bekop.layarwibu.com/player2/{encoded_target}"></iframe></div>'
                )
                return httpx.Response(200, text=html, headers={'Content-Type': 'text/html'})
        if request.url.host == 'cdn.example' and request.url.path == '/series/master.m3u8':
            return httpx.Response(
                200,
                text=_master_playlist(qualities=(1080, 720, 480)),
                headers={'Content-Type': 'application/vnd.apple.mpegurl'},
            )
        raise AssertionError(f'Unexpected request: {request.method} {request.url}')

    provider = CloudstreamProvider(client=_build_client(handler), base_urls=('https://filmkita.cloud',))
    item = ProviderSearchResult(
        id='https://filmkita.cloud/reacher-season-2/',
        title='Reacher Season 2',
        page_url='https://filmkita.cloud/reacher-season-2/',
        subject_type=SubjectType.TV_SERIES,
        year=2022,
        payload={'subject_type_inferred': False},
    )

    streams = await provider.resolve_streams(item, season=2, episode=2)

    assert [stream.source for stream in streams] == [
        'cloudstream:alkhalifitv-1',
        'cloudstream:alkhalifitv-1',
        'cloudstream:alkhalifitv-1',
    ]
    assert [stream.quality for stream in streams] == ['720p', '480p', '1080p']
    assert item.payload['episodes'][1]['episode'] == 2

@pytest.mark.asyncio
async def test_resolve_movie_streams_uses_gdriveplayer_sources(monkeypatch):
    original_extract_packer_scripts = cloudstream_core_module._extract_packer_scripts
    original_unpack_packer_script = cloudstream_core_module._unpack_packer_script

    def fake_extract_packer_scripts(html: str) -> list[str]:
        if 'gdrive-shell' in html:
            return ['gdrive-stub']
        return original_extract_packer_scripts(html)

    def fake_unpack_packer_script(script: str) -> str:
        if script == 'gdrive-stub':
            return (
                'var data=\'{"ct":"abc","iv":"00","s":"00"}\';'
                'null,"118_97_114_32_112_97_115_115_32_61_32_34_115_101_99_114_101_116_34";'
            )
        if script == 'packed-second':
            return (
                'player.setup({sources:[{file:"https://video.example/master.m3u8",label:"720p"}],'
                'tracks:[{file:"https://subs.example/en.vtt",label:"English",kind:"captions"}]});'
            )
        return original_unpack_packer_script(script)

    def fake_eval(fragment: str, _referrer: str) -> list[dict[str, object]]:
        if 'master.m3u8' in fragment:
            return [{'file': 'https://video.example/master.m3u8', 'label': '720p'}]
        return [{'file': 'https://subs.example/en.vtt', 'label': 'English', 'kind': 'captions'}]

    monkeypatch.setattr(cloudstream_core_module, '_extract_packer_scripts', fake_extract_packer_scripts)
    monkeypatch.setattr(cloudstream_core_module, '_unpack_packer_script', fake_unpack_packer_script)
    def decrypt_payload(_data: str, _password: str) -> str:
        return '"packed-second"'

    monkeypatch.setattr(
        cloudstream_core_module,
        '_decrypt_gdriveplayer_payload',
        decrypt_payload,
    )
    monkeypatch.setattr(cloudstream_core_module, '_evaluate_javascript_array', fake_eval)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == 'filmkita.cloud' and request.url.path == '/home-alone/':
            return httpx.Response(
                200,
                text=_movie_page(title='Home Alone', post_id='76921', year=1990, genres=('Comedy',)),
                headers={'Content-Type': 'text/html'},
            )
        if request.url.host == 'filmkita.cloud' and request.url.path == '/wp-admin/admin-ajax.php':
            html = '<div class="gmr-embed-responsive"><iframe src="https://gdriveplayer.io/embed2.php?link=test"></iframe></div>'
            return httpx.Response(200, text=html, headers={'Content-Type': 'text/html'})
        if request.url.host == 'gdriveplayer.io' and request.url.path == '/embed2.php':
            return httpx.Response(
                200,
                text='<div class="gdrive-shell"></div>',
                headers={'Content-Type': 'text/html'},
            )
        if request.url.host == 'video.example' and request.url.path == '/master.m3u8':
            return httpx.Response(
                200,
                text=_master_playlist(qualities=(720,)),
                headers={'Content-Type': 'application/vnd.apple.mpegurl'},
            )
        raise AssertionError(f'Unexpected request: {request.method} {request.url}')

    provider = CloudstreamProvider(client=_build_client(handler), base_urls=('https://filmkita.cloud',))
    item = ProviderSearchResult(
        id='https://filmkita.cloud/home-alone/',
        title='Home Alone',
        page_url='https://filmkita.cloud/home-alone/',
        subject_type=SubjectType.MOVIES,
        year=1990,
    )

    streams = await provider.resolve_streams(item)

    assert len(streams) == 1
    assert streams[0].source == 'cloudstream:gdriveplayer'
    assert streams[0].quality == '720p'
    assert streams[0].url == 'https://video.example/720.m3u8'
    assert [subtitle.url for subtitle in streams[0].subtitles] == ['https://subs.example/en.vtt']


@pytest.mark.asyncio
async def test_resolve_movie_streams_filters_gdriveplayer_dummy_error_video(monkeypatch):
    original_extract_packer_scripts = cloudstream_core_module._extract_packer_scripts
    original_unpack_packer_script = cloudstream_core_module._unpack_packer_script

    def fake_extract_packer_scripts(html: str) -> list[str]:
        if 'gdrive-shell' in html:
            return ['gdrive-stub']
        return original_extract_packer_scripts(html)

    def fake_unpack_packer_script(script: str) -> str:
        if script == 'gdrive-stub':
            return (
                'var data=\'{"ct":"abc","iv":"00","s":"00"}\';'
                'null,"118_97_114_32_112_97_115_115_32_61_32_34_115_101_99_114_101_116_34";'
            )
        if script == 'packed-second':
            return 'player.setup({sources:[{file:"https://redirect.gdrivecdn.work/drive/error.mp4?reason=folder",label:"720p"}]});'
        return original_unpack_packer_script(script)

    monkeypatch.setattr(cloudstream_core_module, '_extract_packer_scripts', fake_extract_packer_scripts)
    monkeypatch.setattr(cloudstream_core_module, '_unpack_packer_script', fake_unpack_packer_script)
    def decrypt_payload(_data: str, _password: str) -> str:
        return '"packed-second"'

    monkeypatch.setattr(
        cloudstream_core_module,
        '_decrypt_gdriveplayer_payload',
        decrypt_payload,
    )
    def dummy_eval(fragment: str, _referrer: str) -> list[dict[str, object]]:
        if 'error.mp4' in fragment:
            return [
                {
                    'file': 'https://redirect.gdrivecdn.work/drive/error.mp4?reason=folder',
                    'label': '720p',
                }
            ]
        return []

    monkeypatch.setattr(
        cloudstream_core_module,
        '_evaluate_javascript_array',
        dummy_eval,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == 'filmkita.cloud' and request.url.path == '/home-alone/':
            return httpx.Response(
                200,
                text=_movie_page(title='Home Alone', post_id='76921', year=1990, genres=('Comedy',)),
                headers={'Content-Type': 'text/html'},
            )
        if request.url.host == 'filmkita.cloud' and request.url.path == '/wp-admin/admin-ajax.php':
            html = '<div class="gmr-embed-responsive"><iframe src="https://gdriveplayer.io/embed2.php?link=test"></iframe></div>'
            return httpx.Response(200, text=html, headers={'Content-Type': 'text/html'})
        if request.url.host == 'gdriveplayer.io' and request.url.path == '/embed2.php':
            return httpx.Response(
                200,
                text='<div class="gdrive-shell"></div>',
                headers={'Content-Type': 'text/html'},
            )
        if request.url.host == 'redirect.gdrivecdn.work' and request.url.path == '/drive/error.mp4':
            return httpx.Response(206, content=b'dummy', headers={'Content-Type': 'video/mp4'})
        raise AssertionError(f'Unexpected request: {request.method} {request.url}')

    provider = CloudstreamProvider(client=_build_client(handler), base_urls=('https://filmkita.cloud',))
    item = ProviderSearchResult(
        id='https://filmkita.cloud/home-alone/',
        title='Home Alone',
        page_url='https://filmkita.cloud/home-alone/',
        subject_type=SubjectType.MOVIES,
        year=1990,
    )

    streams = await provider.resolve_streams(item)

    assert streams == []
