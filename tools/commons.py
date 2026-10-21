"""Фото с Викисклада: при сборке скачиваются, сжимаются и кладутся в сайт, чтобы работали без интернета.

В карточке достаточно указать поле commons: {file, author, license}. Если скачать не удалось
(нет сети, сбой Викисклада), сборка не ломается: карточка по-прежнему покажет фото через интернет.
Файл можно положить и вручную в папку commons-src/ (имя файла как на Викискладе).
"""
import html, io, json, os, re, time, urllib.error, urllib.parse, urllib.request

UA = 'SadovodApp/1.0 (https://github.com/sadovod-k/sadovod; student project)'   # только латиница: заголовки HTTP не принимают русские буквы
W, H = 1080, 810


def prepare(data):
    """Обрезка по центру до 4:3, размер 1080x810, WebP (обычно 60–140 КБ)."""
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert('RGB')
    w, h = im.size
    if w * 3 > h * 4:
        nw = round(h * 4 / 3); x0 = (w - nw) // 2; im = im.crop((x0, 0, x0 + nw, h))
    elif w * 3 < h * 4:
        nh = round(w * 3 / 4); y0 = (h - nh) // 2; im = im.crop((0, y0, w, y0 + nh))
    im = im.resize((W, H), Image.LANCZOS)
    out = b''
    for q in (80, 74, 68, 60):
        buf = io.BytesIO(); im.save(buf, 'WEBP', quality=q, method=6); out = buf.getvalue()
        if len(out) <= 140 * 1024: break
    return out


def download(name, local_dir=None):
    if local_dir:
        p = os.path.join(local_dir, name)
        if os.path.exists(p):
            with open(p, 'rb') as f: return f.read()
    if os.environ.get('SADOVOD_OFFLINE') == '1':
        raise OSError('режим без сети')
    problems = []
    # Викисклад отдаёт уменьшенные копии только стандартных ширин (иначе ответ 429), поэтому 1280, а при неудаче 960
    for width in (1280, 960):
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


def _plain(s):
    """Текст без тегов: имя автора на Викискладе приходит как HTML-ссылка."""
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', s or ''))).strip()


def license_ok(lic):
    """Подходят CC BY, CC BY-SA, CC0, общественное достояние и OGL; NC, ND и «только GFDL» не подходят."""
    u = str(lic).upper().replace('-', ' ').replace('_', ' ')
    words = u.split()
    if 'NC' in words or 'ND' in words:
        return False
    return u.startswith(('CC BY', 'CC0', 'PUBLIC DOMAIN', 'PD', 'OGL', 'OPEN GOVERNMENT'))


def _get(url, what):
    problems = []
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            problems.append('ответ %s' % e.code)
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(3 * (attempt + 1)); continue
            break
        except Exception as e:
            problems.append(str(e)); time.sleep(2 * (attempt + 1))
    raise OSError(what + ': ' + ('; '.join(problems[-3:]) or 'нет ответа'))


def metadata(name):
    """Автор и лицензия файла, как они записаны на Викискладе."""
    if os.environ.get('SADOVOD_OFFLINE') == '1':
        raise OSError('режим без сети')
    url = ('https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo&iiprop=extmetadata&titles='
           + urllib.parse.quote('File:' + name))
    data = json.loads(_get(url, 'запрос к Викискладу').decode('utf-8'))
    for page in ((data.get('query') or {}).get('pages') or {}).values():
        meta = ((page.get('imageinfo') or [{}])[0]).get('extmetadata') or {}
        a = re.sub(r'^\S+\.(?:jpe?g|png|webp|tiff?|gif)\s*:\s*', '', _plain((meta.get('Artist') or {}).get('value')), flags=re.I)
        guess = re.match(r'No machine-readable author provided\.\s*(.+?)\s+assumed\b', a, flags=re.I)   # заглушка Викисклада: «автор не указан, предположительно X»
        if guess:
            a = guess.group(1)
        l = _plain((meta.get('LicenseShortName') or {}).get('value'))
        if a and l:
            return {'author': a, 'license': l}
    raise OSError('в ответе нет автора или лицензии')


def _lic_key(lic):
    u = str(lic).upper()
    if u.startswith(('OGL', 'OPEN GOVERNMENT')):
        return 'OGL'
    return re.sub(r'[^A-Z0-9.]', '', u)


def resolve(c, owner):
    """Карточке достаточно file: автор и лицензия берутся с Викисклада. Если они вписаны вручную, лицензия сверяется с Викискладом.
    Возвращает полные данные или None, если фото показывать нельзя (нет данных или лицензия не подходит)."""
    c = dict(c)
    try:
        m = metadata(c['file'])
    except Exception as e:
        m = None
        if not (c.get('author') and c.get('license')):
            print(f"  предупреждение: у фото «{c['file']}» не указаны автор и лицензия, получить их не удалось ({e}); фото не показывается")
            return None
    if m:
        if not (c.get('author') and c.get('license')):
            c['author'] = c.get('author') or m['author']; c['license'] = c.get('license') or m['license']
            print(f"  фото «{c['file']}»: автор и лицензия получены с Викисклада: {c['author']}, {c['license']}")
        elif _lic_key(m['license']) != _lic_key(c['license']):
            words = str(m['license']).upper().replace('-', ' ').split()
            if 'NC' in words or 'ND' in words:
                print(f"  предупреждение: у фото «{c['file']}» на Викискладе лицензия «{m['license']}» (только некоммерческое или без изменений); фото не показывается")
                return None
            if license_ok(m['license']):
                print(f"  внимание: у фото «{c['file']}» в данных лицензия «{c['license']}», на Викискладе «{m['license']}»; использую «{m['license']}»")
                c['license'] = m['license']
            else:
                print(f"  внимание: у фото «{c['file']}» на Викискладе указано «{m['license']}» (возможно, несколько лицензий); оставлена лицензия из данных «{c['license']}»")
    if not license_ok(c['license']):
        print(f"  предупреждение: лицензия «{c['license']}» у фото «{c['file']}» не подходит; фото не показывается")
        return None
    return c


def _save(site, rel, data):
    os.makedirs(os.path.join(site, 'photos'), exist_ok=True)
    with open(os.path.join(site, rel), 'wb') as f: f.write(data)


def _credit(c):
    s = f"{c['author']}, {c['license']}, Wikimedia Commons"
    if str(c['license']).upper().startswith('CC') and 'BY' in str(c['license']).upper():      # лицензии CC BY требуют указать, что изображение изменено
        s += ' (обрезано и сжато)'
    return s


def _source(c):
    return 'https://commons.wikimedia.org/wiki/File:' + urllib.parse.quote(c['file'].replace(' ', '_'))


def localize(items, site, root):
    """Для карточек с commons (главное фото) и gallery (дополнительные): скачать, положить в site/photos и подписать автора."""
    local_dir = os.environ.get('SADOVOD_COMMONS_DIR') or os.path.join(root, 'commons-src')
    done = failed = rejected = 0

    def prepare_one(c, owner):
        """-> (данные картинки или None, полные сведения или None)"""
        nonlocal failed, rejected
        rc = resolve(c, owner)
        if rc is None:
            rejected += 1
            return None, None
        try:
            return prepare(download(rc['file'], local_dir)), rc
        except Exception as e:
            print(f"  предупреждение: фото «{rc['file']}» не скачалось ({e}); карточка {owner} покажет его только при интернете")
            failed += 1
            return None, rc

    for v in items:
        c = v.get('commons')
        if c and not v.get('image'):
            data, rc = prepare_one(c, v['id'])
            if data:
                rel = f"photos/c-{v['id']}.webp"
                _save(site, rel, data)
                v['image'] = rel; v['imageCredit'] = _credit(rc); v['imageSource'] = _source(rc)
                del v['commons']; done += 1
            elif rc:
                v['commons'] = rc            # не скачалось: останется ссылка на фото в интернете, уже с автором
            else:
                del v['commons']             # нельзя показывать: нет автора или лицензия не подходит
        gal = v.get('gallery')
        if isinstance(gal, list):
            out = []
            for n, g in enumerate(gal, 1):
                if not (isinstance(g, dict) and g.get('file') and not g.get('src')):
                    out.append(g); continue
                data, rc = prepare_one(g, v['id'])
                if data:
                    rel = f"photos/c-{v['id']}-{n}.webp"
                    _save(site, rel, data)
                    out.append({'src': rel, 'credit': _credit(rc), 'source': _source(rc), 'caption': g.get('caption') or 'Плод'}); done += 1
                elif rc:
                    out.append(dict(g, **{k: rc[k] for k in ('author', 'license')}))
            v['gallery'] = out
    if done or failed or rejected:
        print(f'  фото с Викисклада: сохранено для работы без интернета {done}, не скачалось {failed}, не подошло {rejected}')
    return done, failed
