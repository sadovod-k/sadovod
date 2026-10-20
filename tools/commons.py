"""Фото с Викисклада: при сборке скачиваются, сжимаются и кладутся в сайт, чтобы работали без интернета.

В карточке достаточно указать поле commons: {file, author, license}. Если скачать не удалось
(нет сети, сбой Викисклада), сборка не ломается: карточка по-прежнему покажет фото через интернет.
Файл можно положить и вручную в папку commons-src/ (имя файла как на Викискладе).
"""
import io, os, time, urllib.error, urllib.parse, urllib.request

UA = 'SadovodApp/1.0 (https://github.com/sadovod-k/sadovod; student project)'   # только латиница: заголовки HTTP не принимают русские буквы
W, H = 720, 540


def prepare(data):
    """Обрезка по центру до 4:3, размер 720x540, WebP (обычно 20–60 КБ)."""
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert('RGB')
    w, h = im.size
    if w * 3 > h * 4:
        nw = round(h * 4 / 3); x0 = (w - nw) // 2; im = im.crop((x0, 0, x0 + nw, h))
    elif w * 3 < h * 4:
        nh = round(w * 3 / 4); y0 = (h - nh) // 2; im = im.crop((0, y0, w, y0 + nh))
    im = im.resize((W, H), Image.LANCZOS)
    out = b''
    for q in (60, 54, 48, 42):
        buf = io.BytesIO(); im.save(buf, 'WEBP', quality=q, method=6); out = buf.getvalue()
        if len(out) <= 60 * 1024: break
    return out


def download(name, local_dir=None):
    if local_dir:
        p = os.path.join(local_dir, name)
        if os.path.exists(p):
            with open(p, 'rb') as f: return f.read()
    if os.environ.get('SADOVOD_OFFLINE') == '1':
        raise OSError('режим без сети')
    problems = []
    # Викисклад отдаёт уменьшенные копии только стандартных ширин (иначе ответ 429), поэтому 960, а при неудаче 1280
    for width in (960, 1280):
        url = 'https://commons.wikimedia.org/wiki/Special:FilePath/' + urllib.parse.quote(name) + '?width=%d' % width
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={'User-Agent': UA})
                with urllib.request.urlopen(req, timeout=40) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                problems.append('ширина %d: ответ %s' % (width, e.code))
                if e.code in (429, 500, 502, 503, 504):
                    time.sleep(3 * (attempt + 1)); continue
                break                       # 403, 404 и т. п. повторять нет смысла
            except Exception as e:
                problems.append('ширина %d: %s' % (width, e)); time.sleep(2 * (attempt + 1))
    raise OSError('; '.join(problems[-3:]) or 'нет ответа')


def _save(site, rel, data):
    os.makedirs(os.path.join(site, 'photos'), exist_ok=True)
    with open(os.path.join(site, rel), 'wb') as f: f.write(data)


def _credit(c):
    return f"{c['author']}, {c['license']}, Wikimedia Commons"


def _source(c):
    return 'https://commons.wikimedia.org/wiki/File:' + urllib.parse.quote(c['file'].replace(' ', '_'))


def localize(items, site, root):
    """Для карточек с commons (главное фото) и gallery (дополнительные): скачать, положить в site/photos и подписать автора."""
    local_dir = os.environ.get('SADOVOD_COMMONS_DIR') or os.path.join(root, 'commons-src')
    done = failed = 0

    def fetch(c, owner):
        nonlocal failed
        try:
            return prepare(download(c['file'], local_dir))
        except Exception as e:
            print(f"  предупреждение: фото «{c['file']}» не скачалось ({e}); карточка {owner} покажет его только при интернете")
            failed += 1
            return None

    for v in items:
        c = v.get('commons')
        if c and not v.get('image'):
            data = fetch(c, v['id'])
            if data:
                rel = f"photos/c-{v['id']}.webp"
                _save(site, rel, data)
                v['image'] = rel; v['imageCredit'] = _credit(c); v['imageSource'] = _source(c)
                del v['commons']; done += 1
        gal = v.get('gallery')
        if isinstance(gal, list):
            for n, g in enumerate(gal, 1):
                if not (isinstance(g, dict) and g.get('file') and not g.get('src')):
                    continue
                data = fetch(g, v['id'])
                if data:
                    rel = f"photos/c-{v['id']}-{n}.webp"
                    _save(site, rel, data)
                    gal[n - 1] = {'src': rel, 'credit': _credit(g), 'source': _source(g), 'caption': g.get('caption') or 'Плод'}
                    done += 1
    if done or failed:
        print(f'  фото с Викисклада: сохранено для работы без интернета {done}, не скачалось {failed}')
    return done, failed
