#!/usr/bin/env python3
"""Проверка файлов данных (data/*.json). Ошибки останавливают сборку, предупреждения только показываются."""
import json, re, sys, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = {'apple': 'data/apple.json', 'pear': 'data/pear.json', 'orn': 'data/ornamental.json'}
PREFIX = {'a': 'apple', 'p': 'pear', 'o': 'orn'}
REQUIRED_ORN = ['id', 'cat', 'name', 'latin', 'kind', 'y', 'season', 'origin', 'height', 'crown', 'bloom', 'light', 'soil', 'water', 'hardy', 'src', 'status']
REQUIRED_TEXT = ['id', 'cat', 'name', 'y', 'year', 'origin', 'season', 'hardy', 'keep', 'taste', 'src']
KNOWN = set(REQUIRED_TEXT) | {'yearNote', 'parents', 'facts', 'care', 'fun', 'scab', 'image', 'imageCredit',
                              'imageSource', 'imageFull', 'imageCaption', 'commons', 'gallery', 'photo', 'photoCredit', 'status',
                              'latin', 'kind', 'height', 'crown', 'bloom', 'light', 'soil', 'water', 'autumn', 'use', 'checked'}

def load_all():
    out = []
    for cat, rel in FILES.items():
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            continue
        with open(path, encoding='utf-8') as f:
            for v in json.load(f):
                out.append((rel, v))
    return out

def validate(items=None):
    items = items if items is not None else load_all()
    errors, warnings = [], []
    ids, names = {}, {}
    for rel, v in items:
        vid = v.get('id', '?')
        where = f'{vid} ({v.get("name", "без названия")})'
        err = lambda m: errors.append(f'{where}: {m}')
        warn = lambda m: warnings.append(f'{where}: {m}')

        is_orn = v.get('cat') == 'orn'
        for k in (REQUIRED_ORN if is_orn else REQUIRED_TEXT):
            if not isinstance(v.get(k), str) or not v.get(k).strip():
                err(f'нет обязательного поля «{k}»')
        if is_orn and v.get('kind') not in ('Дерево', 'Кустарник'):
            err('«kind» должно быть «Дерево» или «Кустарник»')
        if v.get('id') and not re.fullmatch(r'[apo]\d+', v['id']):
            err('id должен быть вида a12 (яблоня), p3 (груша) или o2 (декоративные)')
        elif v.get('id'):
            if PREFIX.get(v['id'][0]) != v.get('cat'):
                err(f'id «{v["id"]}» не соответствует культуре «{v.get("cat")}»')
            if v['id'] in ids: err(f'id повторяется (также у {ids[v["id"]]})')
            ids[v['id']] = v.get('name')
        if rel and v.get('cat') and FILES.get(v['cat']) != rel:
            err(f'сорт лежит в файле {rel}, но его культура «{v["cat"]}»')
        key = (v.get('cat'), (v.get('name') or '').strip().lower())
        if key[1] and key in names: err('название повторяется в этой культуре')
        names[key] = True

        season = (v.get('season') or '').lower()
        if season and not is_orn and not any(w in season for w in ('лет', 'осен', 'зим')):
            err('в «season» должно быть слово «лет…», «осен…» или «зим…» (по нему работает фильтр)')

        facts = v.get('facts')
        if not isinstance(facts, list) or len([x for x in facts if isinstance(x, str) and x.strip()]) < 2:
            err('нужно минимум 2 пункта в «facts»')
        for fld in ('facts', 'care'):
            val = v.get(fld, [])
            if not isinstance(val, list) or any(not isinstance(x, str) or not x.strip() for x in val):
                err(f'«{fld}» должно быть списком непустых строк')
            else:
                for x in val:
                    if len(x) > 260: warn(f'слишком длинный пункт в «{fld}» ({len(x)} знаков)')
        if v.get('status') not in ('verified', 'draft'):
            err('«status» должен быть "verified" (проверено по источникам) или "draft" (черновик)')
        if v.get('status') == 'verified' and re.search(r'не проверен|черновик', v.get('src', ''), re.I):
            err('сорт помечен как проверенный, но в источниках написано, что он не проверен')
        if v.get('status') == 'verified' and not re.fullmatch(r'20\d\d-(0[1-9]|1[0-2])', str(v.get('checked', ''))):
            err('у проверенного сорта нужна дата проверки «checked» в формате ГГГГ-ММ, например 2026-10')
        if v.get('scab', '') not in ('', 'res'):
            err('«scab» может быть только пустым или "res"')
        if not v.get('fun'): warn('нет интересного факта («fun»)')
        if not v.get('care'): warn('нет раздела «Выращивание» («care»)')
        if len(v.get('src', '')) < 12: warn('источники указаны слишком кратко')

        for k in v:
            if k not in KNOWN: warn(f'неизвестное поле «{k}»')

        img = v.get('image', '')
        if img.startswith('http'):
            if not v.get('imageCredit') or not v.get('imageSource'):
                err('у онлайн-фото должны быть «imageCredit» и «imageSource»')
        elif img and not os.path.exists(os.path.join(ROOT, img)):
            err(f'файл фото {img} не найден')
        c = v.get('commons')
        if c is not None and (not isinstance(c, dict) or not c.get('file')):
            err('«commons» должен содержать имя файла file (автор и лицензия подставятся при сборке; можно указать author и license вручную)')

        for k in ('name', 'y', 'year', 'origin', 'season', 'hardy', 'keep', 'taste', 'src', 'fun', 'yearNote', 'parents'):
            if re.search(r'<\s*script', str(v.get(k, '')), re.I): err(f'в «{k}» запрещён тег script')

        pending = [k for k in (('origin', 'hardy', 'autumn', 'height', 'crown', 'bloom') if is_orn else ('year', 'origin', 'hardy', 'keep', 'taste')) if 'уточн' in str(v.get(k, '')).lower()]
        if pending: warn('нужно уточнить: ' + ', '.join(pending))
    return errors, warnings

if __name__ == '__main__':
    errors, warnings = validate()
    total = len(load_all())
    for w in warnings: print('  предупреждение:', w)
    for e in errors: print('  ОШИБКА:', e)
    print(f'Сортов: {total}. Ошибок: {len(errors)}. Предупреждений: {len(warnings)}.')
    sys.exit(1 if errors else 0)
