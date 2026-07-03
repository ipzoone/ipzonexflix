from flask import Flask, send_from_directory, jsonify, request
import requests
from bs4 import BeautifulSoup
import json
import re
import concurrent.futures
app = Flask(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ══════════════════════════════════════════════════════════════
#  HELPER
# ══════════════════════════════════════════════════════════════
def get(url, timeout=12, **kwargs):
    """GET dengan retry 1x"""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, **kwargs)
        r.raise_for_status()
        return r
    except Exception:
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout+5, **kwargs)
            return r
        except Exception as e:
            raise e


# ══════════════════════════════════════════════════════════════
#  1. YOUTUBE
# ══════════════════════════════════════════════════════════════
def scrape_youtube(query):
    url  = f"https://www.youtube.com/results?search_query={requests.utils.quote(query)}"
    results = []
    try:
        soup = BeautifulSoup(get(url).text, 'html.parser')
        for script in soup.find_all('script'):
            if 'ytInitialData' not in script.text:
                continue
            m = re.search(r'var ytInitialData\s*=\s*(\{.*?\})(?:;|\s*</script>)', script.text, re.DOTALL)
            if not m:
                m = re.search(r'var ytInitialData\s*=\s*(\{.*)', script.text, re.DOTALL)
            if not m:
                break
            data = json.loads(m.group(1).rstrip(';'))
            contents = (
                data['contents']['twoColumnSearchResultsRenderer']
                    ['primaryContents']['sectionListRenderer']
                    ['contents'][0]['itemSectionRenderer']['contents']
            )
            for item in contents:
                if 'videoRenderer' not in item:
                    continue
                vd   = item['videoRenderer']
                vid  = vd.get('videoId', '')
                title = vd.get('title', {}).get('runs', [{}])[0].get('text', '')
                thumbs = vd.get('thumbnail', {}).get('thumbnails', [])
                thumb  = thumbs[-1]['url'] if thumbs else f'https://i.ytimg.com/vi/{vid}/mqdefault.jpg'
                dur    = vd.get('lengthText', {}).get('simpleText', '')
                results.append({
                    'id': vid, 'title': title, 'thumbnail': thumb,
                    'duration': dur, 'source': 'youtube', 'type': 'video',
                    'embed_url': f'https://www.youtube.com/embed/{vid}?autoplay=1&rel=0',
                    'page_url': f'https://www.youtube.com/watch?v={vid}',
                    'rating': '', 'genre': '', 'year': '',
                })
            break
    except Exception as e:
        print(f"[YouTube] {e}")
    return results


# ══════════════════════════════════════════════════════════════
#  2. DAILYMOTION
# ══════════════════════════════════════════════════════════════
def scrape_dailymotion(query):
    api = (
        "https://api.dailymotion.com/videos"
        f"?search={requests.utils.quote(query)}"
        "&fields=id,title,thumbnail_480_url,duration,embed_url,url"
        "&limit=20&flags=no_live"
    )
    results = []
    try:
        data = get(api).json()
        for item in data.get('list', []):
            vid  = item.get('id', '')
            mins, secs = divmod(int(item.get('duration', 0)), 60)
            dur = f"{mins}:{secs:02d}" if item.get('duration') else ''
            results.append({
                'id': vid, 'title': item.get('title', ''),
                'thumbnail': item.get('thumbnail_480_url', ''),
                'duration': dur, 'source': 'dailymotion', 'type': 'video',
                'embed_url': (item.get('embed_url') or f'https://www.dailymotion.com/embed/video/{vid}') + '?autoplay=1',
                'page_url': item.get('url', f'https://www.dailymotion.com/video/{vid}'),
                'rating': '', 'genre': '', 'year': '',
            })
    except Exception as e:
        print(f"[Dailymotion] {e}")
    return results


# ══════════════════════════════════════════════════════════════
#  3. VIMEO
# ══════════════════════════════════════════════════════════════
def scrape_vimeo(query):
    url = f"https://vimeo.com/search?q={requests.utils.quote(query)}"
    results = []
    try:
        soup = BeautifulSoup(get(url).text, 'html.parser')
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data  = json.loads(script.string or '{}')
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get('@type') != 'VideoObject':
                        continue
                    m = re.search(r'vimeo\.com/(\d+)', item.get('url', ''))
                    if not m:
                        continue
                    vid   = m.group(1)
                    thumb = item.get('thumbnailUrl', '')
                    if isinstance(thumb, list):
                        thumb = thumb[0] if thumb else ''
                    dur   = ''
                    raw   = item.get('duration', '')
                    if raw:
                        dm = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', raw)
                        if dm:
                            h, mi, s = dm.group(1), dm.group(2), dm.group(3)
                            p = []
                            if h: p.append(h)
                            p += [(mi or '0'), (s or '0').zfill(2)]
                            dur = ':'.join(p)
                    results.append({
                        'id': vid, 'title': item.get('name', ''),
                        'thumbnail': thumb or f'https://vumbnail.com/{vid}.jpg',
                        'duration': dur, 'source': 'vimeo', 'type': 'video',
                        'embed_url': f'https://player.vimeo.com/video/{vid}?autoplay=1',
                        'page_url': f'https://vimeo.com/{vid}',
                        'rating': '', 'genre': '', 'year': '',
                    })
            except Exception:
                pass
        # Fallback HTML parse
        if not results:
            seen = set()
            for a in soup.find_all('a', href=re.compile(r'^/\d{6,}$')):
                vid = a['href'].strip('/')
                if vid in seen: continue
                seen.add(vid)
                results.append({
                    'id': vid, 'title': a.get_text(strip=True) or f'Vimeo {vid}',
                    'thumbnail': f'https://vumbnail.com/{vid}.jpg',
                    'duration': '', 'source': 'vimeo', 'type': 'video',
                    'embed_url': f'https://player.vimeo.com/video/{vid}?autoplay=1',
                    'page_url': f'https://vimeo.com/{vid}',
                    'rating': '', 'genre': '', 'year': '',
                })
                if len(results) >= 15: break
    except Exception as e:
        print(f"[Vimeo] {e}")
    return results


# ══════════════════════════════════════════════════════════════
#  4. KLIKXXI  (flagsio.com)
# ══════════════════════════════════════════════════════════════
def scrape_klikxxi(query):
    """
    KLIKXXI = situs film Indonesia di flagsio.com
    Scrape halaman search/home → ambil listing film.
    Karena search-nya berbasis WordPress, gunakan ?s=query
    """
    base = "https://flagsio.com"
    url  = f"{base}/?s={requests.utils.quote(query)}"
    results = []
    try:
        soup = BeautifulSoup(get(url).text, 'html.parser')

        # Coba berbagai selector card film WordPress/LK21 theme
        cards = (
            soup.select('article.item') or
            soup.select('div.item') or
            soup.select('article') or
            soup.select('.movies-list .ml-item') or
            soup.select('.search-page .result-item')
        )

        # Kalau search kosong, ambil dari homepage listing
        if not cards:
            soup2 = BeautifulSoup(get(base).text, 'html.parser')
            cards = (
                soup2.select('article.item') or
                soup2.select('div.item') or
                soup2.select('article') or
                soup2.select('div.ml-item')
            )

        for card in cards[:25]:
            # Judul
            title_el = card.select_one('h2, h3, .title, .itemTitle a')
            title    = title_el.get_text(strip=True) if title_el else ''
            if not title:
                continue

            # Link halaman film
            link_el  = card.select_one('a[href]')
            page_url = link_el['href'] if link_el else base
            if page_url.startswith('/'):
                page_url = base + page_url

            # Thumbnail
            thumb_el  = card.select_one('img[src], img[data-src]')
            thumbnail = ''
            if thumb_el:
                thumbnail = thumb_el.get('data-src') or thumb_el.get('src') or ''

            # Rating
            rating_el = card.select_one('.rating, .score, span.imdb, .rate')
            rating    = rating_el.get_text(strip=True) if rating_el else ''

            # Genre / quality badge
            genre_el = card.select_one('.genres a, .category a, .genre')
            genre    = genre_el.get_text(strip=True) if genre_el else ''

            # Tahun
            year_el = card.select_one('.year, .date, time')
            year    = year_el.get_text(strip=True)[:4] if year_el else ''

            results.append({
                'id':        re.sub(r'[^a-z0-9]', '-', title.lower())[:40],
                'title':     title,
                'thumbnail': thumbnail,
                'duration':  '',
                'source':    'klikxxi',
                'type':      'film',
                'embed_url': page_url,   # dibuka di iframe/tab
                'page_url':  page_url,
                'rating':    rating,
                'genre':     genre,
                'year':      year,
            })

    except Exception as e:
        print(f"[KLIKXXI] {e}")
    return results


# ══════════════════════════════════════════════════════════════
#  5. REBAHIN  (139.59.196.140)
# ══════════════════════════════════════════════════════════════
def scrape_rebahin(query):
    base = "http://139.59.196.140"
    url  = f"{base}/?s={requests.utils.quote(query)}"
    results = []
    try:
        soup = BeautifulSoup(get(url).text, 'html.parser')

        cards = (
            soup.select('article.item') or
            soup.select('.movies-list .ml-item') or
            soup.select('.result-item article') or
            soup.select('article') or
            soup.select('div.item')
        )

        # Kalau search kosong → ambil trending/homepage
        if not cards:
            soup2 = BeautifulSoup(get(base).text, 'html.parser')
            # Rebahin homepage pakai card dengan gambar & judul
            cards = (
                soup2.select('article.item') or
                soup2.select('div.ml-item') or
                soup2.select('.TPost') or
                soup2.select('article')
            )

        for card in cards[:25]:
            title_el = card.select_one('h2, h3, .Title, .title, a')
            title    = title_el.get_text(strip=True) if title_el else ''
            if not title or len(title) < 2:
                continue

            link_el  = card.select_one('a[href]')
            page_url = link_el['href'] if link_el else base
            if page_url.startswith('/'):
                page_url = base + page_url

            thumb_el  = card.select_one('img[src], img[data-src], img[data-lazy-src]')
            thumbnail = ''
            if thumb_el:
                thumbnail = (thumb_el.get('data-lazy-src') or
                             thumb_el.get('data-src') or
                             thumb_el.get('src') or '')

            rating_el = card.select_one('.Qlty, .rating, .score, .imdb, span[class*="rat"]')
            rating    = rating_el.get_text(strip=True) if rating_el else ''

            genre_el  = card.select_one('.genres a, .category, .Genre')
            genre     = genre_el.get_text(strip=True) if genre_el else ''

            year_el   = card.select_one('.year, .Year, time, .date')
            year      = year_el.get_text(strip=True)[:4] if year_el else ''

            results.append({
                'id':        re.sub(r'[^a-z0-9]', '-', title.lower())[:40],
                'title':     title,
                'thumbnail': thumbnail,
                'duration':  '',
                'source':    'rebahin',
                'type':      'film',
                'embed_url': page_url,
                'page_url':  page_url,
                'rating':    rating,
                'genre':     genre,
                'year':      year,
            })

    except Exception as e:
        print(f"[REBAHIN] {e}")
    return results


# ══════════════════════════════════════════════════════════════
#  6. LK21  (pieandmightymsp.com)
# ══════════════════════════════════════════════════════════════
def scrape_lk21(query):
    base = "https://pieandmightymsp.com"
    url  = f"{base}/?s={requests.utils.quote(query)}"
    results = []
    try:
        soup = BeautifulSoup(get(url).text, 'html.parser')

        cards = (
            soup.select('article.item') or
            soup.select('div.item') or
            soup.select('article') or
            soup.select('.movies-list .ml-item')
        )

        if not cards:
            soup2 = BeautifulSoup(get(base).text, 'html.parser')
            cards = (
                soup2.select('article.item') or
                soup2.select('article') or
                soup2.select('div.item') or
                soup2.select('div.ml-item')
            )

        for card in cards[:25]:
            title_el = card.select_one('h2, h3, .title, .itemTitle a')
            title    = title_el.get_text(strip=True) if title_el else ''
            if not title or len(title) < 2:
                continue

            link_el  = card.select_one('a[href]')
            page_url = link_el['href'] if link_el else base
            if page_url.startswith('/'):
                page_url = base + page_url

            thumb_el  = card.select_one('img[src], img[data-src]')
            thumbnail = ''
            if thumb_el:
                thumbnail = (thumb_el.get('data-src') or
                             thumb_el.get('src') or '')

            rating_el = card.select_one('.rating, .score, .imdb, span.imdb')
            rating    = rating_el.get_text(strip=True) if rating_el else ''

            genre_el  = card.select_one('.genres a, .category a')
            genre     = genre_el.get_text(strip=True) if genre_el else ''

            year_el   = card.select_one('.year, time, .date')
            year      = year_el.get_text(strip=True)[:4] if year_el else ''

            results.append({
                'id':        re.sub(r'[^a-z0-9]', '-', title.lower())[:40],
                'title':     title,
                'thumbnail': thumbnail,
                'duration':  '',
                'source':    'lk21',
                'type':      'film',
                'embed_url': page_url,
                'page_url':  page_url,
                'rating':    rating,
                'genre':     genre,
                'year':      year,
            })

    except Exception as e:
        print(f"[LK21] {e}")
    return results


# ══════════════════════════════════════════════════════════════
#  7. ARCHIVE.ORG  (Internet Archive — film public domain gratis)
# ══════════════════════════════════════════════════════════════
def scrape_archive(query):
    """
    Scrape Internet Archive via Search API.
    Hanya ambil mediatype:movies yang bisa di-embed langsung.
    """
    results = []
    try:
        api = (
            "https://archive.org/advancedsearch.php"
            f"?q=mediatype:movies+title:({requests.utils.quote(query)})"
            "&fl=identifier,title,description,year,subject,downloads"
            "&rows=20&output=json&sort=downloads+desc"
        )
        data = get(api).json()
        docs = data.get('response', {}).get('docs', [])

        for doc in docs:
            iid   = doc.get('identifier', '')
            title = doc.get('title', '')
            if not iid or not title:
                continue

            year  = str(doc.get('year', ''))[:4]
            desc  = doc.get('description', '')
            if isinstance(desc, list):
                desc = desc[0] if desc else ''
            subject = doc.get('subject', '')
            if isinstance(subject, list):
                subject = ', '.join(subject[:3])

            thumbnail = f'https://archive.org/services/img/{iid}'
            page_url  = f'https://archive.org/details/{iid}'
            embed_url = f'https://archive.org/embed/{iid}?autoplay=1'

            results.append({
                'id':        iid,
                'title':     title,
                'thumbnail': thumbnail,
                'duration':  '',
                'source':    'archive',
                'type':      'video',
                'embed_url': embed_url,
                'page_url':  page_url,
                'rating':    '',
                'genre':     subject[:40] if subject else 'Public Domain',
                'year':      year,
            })

    except Exception as e:
        print(f"[Archive.org] {e}")
    return results


# ══════════════════════════════════════════════════════════════
#  8. PLEX  (Plex Free Movies — pakai embed player publik)
# ══════════════════════════════════════════════════════════════
def scrape_plex(query):
    """
    Plex menyediakan film gratis tanpa login via app.plex.tv.
    Gunakan Plex metadata API publik untuk search.
    Embed via player.plex.tv yang bisa diakses tanpa akun.
    """
    results = []
    try:
        # Plex Search API publik (metadata provider)
        api = (
            "https://metadata.provider.plex.tv/library/search"
            f"?query={requests.utils.quote(query)}"
            "&limit=20&searchTypes=movie,show"
        )
        headers = {
            "User-Agent": HEADERS["User-Agent"],
            "Accept": "application/json",
            "X-Plex-Client-Identifier": "streamflix-app",
            "X-Plex-Language": "en",
        }
        r = requests.get(api, headers=headers, timeout=12)
        data = r.json()

        items = (
            data.get('MediaContainer', {}).get('SearchResult', []) or
            data.get('MediaContainer', {}).get('Metadata', [])
        )

        for item in items[:20]:
            guid  = item.get('guid', '')
            title = item.get('title', '')
            if not title:
                continue

            year  = str(item.get('year', ''))
            thumb = item.get('thumb', '') or item.get('art', '')
            if thumb and thumb.startswith('/'):
                thumb = 'https://metadata.provider.plex.tv' + thumb

            # Extract plex ID from guid (plex://movie/5d776b...)
            m = re.search(r'plex://[^/]+/([a-f0-9]+)', guid)
            pid = m.group(1) if m else re.sub(r'[^a-z0-9]', '-', title.lower())[:30]

            genre  = item.get('type', 'movie').capitalize()
            rating = str(item.get('rating', '') or item.get('audienceRating', '') or '')

            page_url  = f'https://watch.plex.tv/movie/{pid}'
            embed_url = f'https://watch.plex.tv/movie/{pid}'

            results.append({
                'id':        pid,
                'title':     title,
                'thumbnail': thumb,
                'duration':  '',
                'source':    'plex',
                'type':      'film',
                'embed_url': embed_url,
                'page_url':  page_url,
                'rating':    rating[:5] if rating else '',
                'genre':     genre,
                'year':      year,
            })

    except Exception as e:
        print(f"[Plex] {e}")
    return results


# ══════════════════════════════════════════════════════════════
#  SCRAPER MAP
# ══════════════════════════════════════════════════════════════
SCRAPERS = {
    'youtube':     scrape_youtube,
    'dailymotion': scrape_dailymotion,
    'vimeo':       scrape_vimeo,
    'klikxxi':     scrape_klikxxi,
    'rebahin':     scrape_rebahin,
    'lk21':        scrape_lk21,
    'archive':     scrape_archive,
}


# ══════════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════════
@app.route('/')
def home():
    return send_from_directory('.', 'index.html')


@app.route('/api/videos')
def api_videos():
    query   = request.args.get('q', 'doraemon sub indo')
    src_raw = request.args.get('sources', ','.join(SCRAPERS.keys()))
    sources = [s.strip() for s in src_raw.split(',') if s.strip() in SCRAPERS]

    all_results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(SCRAPERS[s], query): s for s in sources}
        for fut in concurrent.futures.as_completed(futs):
            try:
                all_results.extend(fut.result())
            except Exception as e:
                print(f"[{futs[fut]}] thread error: {e}")

    # Overwrite videos.json dengan hasil scraping terbaru (hapus data lama)
    # Hanya di local — di cloud (Railway dll) filesystem tidak persistent
    try:
        with open('videos.json', 'w', encoding='utf-8') as f:
            json.dump({"query": query, "videos": all_results}, f,
                      ensure_ascii=False, indent=2)
    except Exception:
        pass  # Tidak masalah kalau gagal (misal di environment read-only)

    return jsonify(all_results)


@app.route('/api/sources')
def api_sources():
    """Info semua sumber yang tersedia"""
    return jsonify(list(SCRAPERS.keys()))


@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('.', filename)


if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    print("\n🎬  StreamFlix Multi-Source  →  http://127.0.0.1:" + str(port))
    print("    Sumber:", ' · '.join(f'[{k}]' for k in SCRAPERS))
    print()
    app.run(debug=False, host='0.0.0.0', port=port)
