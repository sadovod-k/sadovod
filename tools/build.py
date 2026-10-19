#!/usr/bin/env python3
"""Сборка сайта: проверка данных -> dist/site (для публикации) и dist/single (один файл) -> zip."""
import json, os, re, shutil, sys, hashlib, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validate import validate, load_all, ROOT

LOADER = """let VARIETIES = [];
const DATA_FILES = ['data/apple.json', 'data/pear.json', 'data/ornamental.json'];
async function loadVarieties(){
  try {
    const parts = await Promise.all(DATA_FILES.map(f => fetch(f, {cache:'no-cache'}).then(r => { if(!r.ok) throw new Error(f); return r.json(); })));
    VARIETIES = parts.flat();
    try { localStorage.setItem('sad-data', JSON.stringify(VARIETIES)); } catch(e) {}
  } catch(err) {
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem('sad-data') || 'null'); } catch(e) {}
    if(saved && saved.length) VARIETIES = saved; else throw err;
  }
}"""
START_LOADER = """loadVarieties().then(() => render()).catch(() => {
  document.getElementById('app').innerHTML = '<div class="view"><p class="empty">Не удалось загрузить данные. Проверьте интернет и откройте приложение снова.</p></div>';
});"""


def _b64(data, mime='image/webp'):
    import base64
    return 'data:' + mime + ';base64,' + base64.b64encode(data).decode()

def tiny_blur(path):
    """Крошечная картинка (24 пикселя): растянутая на экран, она даёт мягкий размытый фон без тяжёлого фильтра."""
    from PIL import Image
    import io
    im = Image.open(path).convert('RGB'); w = 24; h = max(1, round(im.size[1] * w / im.size[0]))
    buf = io.BytesIO(); im.resize((w, h), Image.LANCZOS).save(buf, 'WEBP', quality=40, method=6)
    return _b64(buf.getvalue())

def shrink(path, width, quality):
    """Уменьшенная копия фото для предпросмотра в чате (быстрее открывается)."""
    from PIL import Image
    import io
    im = Image.open(path).convert('RGB')
    if im.size[0] > width: im = im.resize((width, round(im.size[1] * width / im.size[0])), Image.LANCZOS)
    buf = io.BytesIO(); im.save(buf, 'WEBP', quality=quality, method=6)
    return _b64(buf.getvalue())

def add_blur(items):
    for v in items:
        img = v.get('image', '')
        path = os.path.join(ROOT, img) if img and not img.startswith(('http', 'data:')) else ''
        if path and os.path.exists(path): v['imageBlur'] = tiny_blur(path)

def main():
    errors, warnings = validate()
    for w in warnings: print('  предупреждение:', w)
    if errors:
        for e in errors: print('  ОШИБКА:', e)
        print('Сборка остановлена: исправьте ошибки.'); sys.exit(1)

    items = [v for _, v in load_all()]
    template = open(os.path.join(ROOT, 'app/template.html'), encoding='utf-8').read()
    hasher = hashlib.sha1((json.dumps(items, ensure_ascii=False, sort_keys=True) + template + open(os.path.join(ROOT, 'static/sw.template.js'), encoding='utf-8').read()).encode())
    pdir = os.path.join(ROOT, 'photos')
    if os.path.isdir(pdir):          # новое или заменённое фото меняет версию, и телефоны скачают его при следующем открытии
        for fname in sorted(os.listdir(pdir)):
            hasher.update(fname.encode()); hasher.update(open(os.path.join(pdir, fname), 'rb').read())
    data_hash = hasher.hexdigest()[:8]

    dist = os.path.join(ROOT, 'dist')
    shutil.rmtree(dist, ignore_errors=True)
    site, single = os.path.join(dist, 'site'), os.path.join(dist, 'single')
    for d in (site, single): os.makedirs(d)

    # 1) сайт: данные отдельными файлами
    html = template.replace('/*@@VARIETIES@@*/', LOADER).replace('/*@@START@@*/', START_LOADER)
    open(os.path.join(site, 'index.html'), 'w', encoding='utf-8').write(html)
    shutil.copytree(os.path.join(ROOT, 'data'), os.path.join(site, 'data'))
    for fname in os.listdir(os.path.join(site, 'data')):
        fpath = os.path.join(site, 'data', fname); arr = json.load(open(fpath, encoding='utf-8')); add_blur(arr)
        json.dump(arr, open(fpath, 'w', encoding='utf-8'), ensure_ascii=False)
    if os.path.isdir(os.path.join(ROOT, 'photos')):
        shutil.copytree(os.path.join(ROOT, 'photos'), os.path.join(site, 'photos'))
    shutil.copytree(os.path.join(ROOT, 'static/icons'), os.path.join(site, 'icons'))
    shutil.copy(os.path.join(ROOT, 'static/apple-touch-icon.png'), os.path.join(site, 'apple-touch-icon.png'))
    for f in ('manifest.webmanifest', '_headers'):
        shutil.copy(os.path.join(ROOT, 'static', f), os.path.join(site, f))
    app_files = ['./', 'index.html', 'manifest.webmanifest', 'apple-touch-icon.png']
    for sub in ('icons', 'data', 'photos'):
        d = os.path.join(site, sub)
        if os.path.isdir(d): app_files += [sub + '/' + f for f in sorted(os.listdir(d))]
    sw = open(os.path.join(ROOT, 'static/sw.template.js'), encoding='utf-8').read().replace('@@VERSION@@', data_hash).replace('@@APP_FILES@@', json.dumps(app_files, ensure_ascii=False))
    open(os.path.join(site, 'sw.js'), 'w', encoding='utf-8').write(sw)

    # 2) один файл: данные внутри (для проверки и работы без сервера); фото из папки не вшиваются
    import base64, copy
    items_single = copy.deepcopy(items)
    with_photos = os.environ.get('SADOVOD_PREVIEW_PHOTOS') == '1'
    if with_photos:
        add_blur(items_single)
        for v in items_single:       # предпросмотр с фото (нужен для проверок): фото уменьшены и вшиты в файл
            img = v.get('image', '')
            path = os.path.join(ROOT, img) if img and not img.startswith(('http', 'data:')) else ''
            if path and os.path.exists(path):
                v['image'] = shrink(path, 480, 45)
    else:
        for v in items_single:       # лёгкий предпросмотр в чате: без фото
            for k in ('image', 'imageCredit', 'imageSource', 'commons', 'gallery'): v.pop(k, None)
    single_tpl = template
    if with_photos:
        for fname in os.listdir(os.path.join(ROOT, 'photos')):
            if fname.startswith('cat-'):
                single_tpl = single_tpl.replace('photos/' + fname, shrink(os.path.join(ROOT, 'photos', fname), 400, 45))
    else:
        single_tpl = re.sub(r"const CAT_PHOTOS = \{.*?\};", "const CAT_PHOTOS = {};", single_tpl, count=1, flags=re.S)
    inline = 'const VARIETIES = ' + json.dumps(items_single, ensure_ascii=False) + ';'
    open(os.path.join(single, 'index.html'), 'w', encoding='utf-8').write(
        single_tpl.replace('/*@@VARIETIES@@*/', inline).replace('/*@@START@@*/', 'render();'))

    if os.environ.get('SADOVOD_PREVIEW_PHOTOS') == '1' and os.path.isdir(os.path.join(ROOT, 'photos')):
        shutil.copytree(os.path.join(ROOT, 'photos'), os.path.join(single, 'photos'))

    # 3) архив для Netlify
    zpath = os.path.join(dist, 'sadovod-site.zip')
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(site):
            for f in files:
                p = os.path.join(root, f); z.write(p, os.path.relpath(p, site))
    print(f'Готово: {len(items)} сортов, версия данных {data_hash}, архив {os.path.getsize(zpath)//1024} КБ.')

if __name__ == '__main__':
    main()
