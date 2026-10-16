"""便携程序草稿目录和最近保存位置；只存路径，不复制用户画作。"""
import json
from pathlib import Path


def draft_folder(base):
    path = Path(base) / '像素画草稿'
    path.mkdir(parents=True, exist_ok=True)
    return path


def remember_draft(base, path):
    folder = draft_folder(base)
    state = folder / '最近草稿.json'
    previous = recent_drafts(base)
    paths = list(dict.fromkeys([str(Path(path).resolve()), *map(str, previous)]))[:100]
    temporary = state.with_suffix('.tmp')
    temporary.write_text(json.dumps(paths, ensure_ascii=False), encoding='utf-8')
    temporary.replace(state)


def recent_drafts(base):
    folder = Path(base) / '像素画草稿'
    try:
        paths = json.loads((folder / '最近草稿.json').read_text(encoding='utf-8'))
        if not isinstance(paths, list):
            return []
        return [Path(p) for p in paths if isinstance(p, str) and Path(p).suffix.lower() == '.tpdraft' and Path(p).is_file()]
    except (OSError, ValueError, TypeError):
        return []


def list_drafts(base):
    """两个入口共用发现规则，兼容旧目录、大小写后缀和外部保存位置。"""
    paths = {p.resolve() for p in recent_drafts(base)}
    for folder in (draft_folder(base), Path(base) / '草稿'):
        try:
            paths.update(p.resolve() for p in folder.iterdir()
                         if p.is_file() and p.suffix.lower() == '.tpdraft')
        except OSError:
            continue
    entries = []
    for path in paths:
        try:
            entries.append((path, path.stat().st_mtime))
        except OSError:
            continue
    return [path for path, _ in sorted(entries, key=lambda entry: entry[1], reverse=True)]


def open_folder(base):
    recent = recent_drafts(base)
    return recent[0].parent if recent else draft_folder(base)
