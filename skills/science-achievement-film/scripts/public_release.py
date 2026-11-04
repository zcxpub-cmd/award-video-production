#!/usr/bin/env python3
"""Scan and package an explicitly selected public plugin source tree.

Findings are heuristic, not proof that every personal detail has been removed.
Reports use relative paths and rule names, never matched secret values.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

TEXT_EXT={'.py','.md','.json','.yaml','.yml','.toml','.txt','.csv','.js','.css','.html','.xml','.gitignore'}
RULES={
    'personal_unix_home':re.compile(r'/(?:Users|home)/[A-Za-z0-9][A-Za-z0-9_.-]*/'),
    'personal_windows_home':re.compile(r'[A-Za-z]:[\\/]Users[\\/][A-Za-z0-9_.-]+[\\/]'),
    'private_temp_path':re.compile(r'/var/folders/[A-Za-z0-9/_.-]+'),
    'private_notes_dependency':re.compile(r'Knowledge'+'Base|Obsi'+'dian',re.I),
    'bearer_value':re.compile(r'Bearer\s+[A-Za-z0-9._-]{20,}'),
    'private_key':re.compile('-----BEGIN '+'(?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'token_literal':re.compile(r'''(?:api_key|access_token|secret_key)\s*[=:]\s*["'][A-Za-z0-9_./+=-]{20,}["']''',re.I),
    'email':re.compile(r'\b[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'),
}
DENY_NAMES={'.env','.DS_Store','config.toml','auth.json','reviews.json','media-map.json','installation.before.json','marketplace.before.json'}
PRIVATE_PARTS={'local','.local','private','.private','private-config','local-config'}
PRIVATE_FILES={'local-runtime.md','local-manifest.json','runtime-config.json'}
IMAGE_EXT={'.png','.jpg','.jpeg'}
PUBLIC_PATHS = ('README.md', '打开影序.html', 'LICENSE', 'NOTICE.md', '.gitignore', 'edition.json',
                '.codex-plugin', '.agents', 'skills', 'docs')
COVER = Path('skills/science-achievement-film/assets/wall/cover')


def cover_hashes(root):
    manifest = root / COVER.with_name('cover-manifest.json')
    if not manifest.exists():
        return {}
    assets = json.loads(manifest.read_text(encoding='utf-8'))
    if not isinstance(assets, dict) or len(assets) != 36:
        raise ValueError('The cover manifest must list 18 poster/video pairs')
    hashes = {}
    for name, record in assets.items():
        if (not re.fullmatch(r'[a-z]+\.(mp4|webp)', name) or not isinstance(record, dict)
                or not isinstance(record.get('sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', record['sha256'])):
            raise ValueError('Invalid cover manifest entry')
        hashes[COVER / name] = record['sha256']
    videos = {p.stem for p in hashes if p.suffix == '.mp4'}
    posters = {p.stem for p in hashes if p.suffix == '.webp'}
    if videos != posters or len(videos) != 18:
        raise ValueError('Every cover video must have a matching poster')
    return hashes


def edition_status(root):
    """Legacy trees may omit a marker; an explicit local marker always fails closed."""
    marker=root/'edition.json'
    if marker.is_symlink():raise ValueError('Edition marker must not be a symlink')
    if not marker.exists():return None
    try:
        data=json.loads(marker.read_text(encoding='utf-8'))
    except (ValueError,UnicodeError):raise ValueError('Invalid edition marker') from None
    if not isinstance(data,dict) or data.get('edition') not in {'local','public'} or type(data.get('publishable')) is not bool:
        raise ValueError('Invalid edition marker')
    return data


def is_screenshot(relative_path):
    return relative_path.parts[:2]==('docs','screenshots') and relative_path.suffix.lower() in IMAGE_EXT


def file_list(root):
    files=[]
    for relative in PUBLIC_PATHS:
        selected = root / relative
        if selected.is_symlink():raise ValueError('Symlink is not allowed in a public release: '+str(selected.relative_to(root)))
        if not selected.exists():continue
        for p in ([selected] if selected.is_file() else sorted(selected.rglob('*'))):
            if p.is_symlink():raise ValueError('Symlink is not allowed in a public release: '+str(p.relative_to(root)))
            if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc':files.append(p)
    return sorted(set(files))


def scan(root,deny_terms=()):
    root=Path(root).resolve();files=file_list(root);findings=[];screenshots=[]
    edition=edition_status(root)
    cover = cover_hashes(root)
    for path in cover:
        if not (root / path).is_file():
            findings.append({'path':path.as_posix(),'line':None,'rule':'cover_asset_missing'})
    if edition and (edition['edition']=='local' or not edition['publishable']):
        findings.append({'path':'edition.json','line':None,'rule':'not_publishable_edition'})
    for p in files:
        relative=p.relative_to(root);rel=str(relative)
        if relative in cover:
            if hashlib.sha256(p.read_bytes()).hexdigest() != cover[relative]:
                findings.append({'path':rel,'line':None,'rule':'cover_asset_hash_mismatch'})
            continue
        if any(part.casefold() in PRIVATE_PARTS for part in relative.parts) or p.name.casefold() in PRIVATE_FILES:
            findings.append({'path':rel,'line':None,'rule':'local_private_configuration'})
        if p.name in DENY_NAMES or p.name.endswith(('.log','.mp4','.mp3','.wav','.drp','.pem','.key')):
            findings.append({'path':rel,'line':None,'rule':'private_or_runtime_artifact'})
        if p.suffix.lower() in IMAGE_EXT:
            if not is_screenshot(relative):
                findings.append({'path':rel,'line':None,'rule':'image_outside_screenshot_directory'})
            else:
                with p.open('rb') as image:header=image.read(12)
                valid=header.startswith(b'\x89PNG\r\n\x1a\n') if p.suffix.lower()=='.png' else header.startswith(b'\xff\xd8\xff')
                if not valid:findings.append({'path':rel,'line':None,'rule':'invalid_screenshot_signature'})
                screenshots.append(rel)
            continue
        if p.suffix not in TEXT_EXT and p.name not in {'LICENSE','.gitignore'}:
            findings.append({'path':rel,'line':None,'rule':'unapproved_binary_or_file_type'})
            continue
        text=p.read_text(encoding='utf-8-sig')
        for i,line in enumerate(text.splitlines(),1):
            for rule,pattern in RULES.items():
                for match in pattern.finditer(line):
                    if rule=='email' and (match.group().endswith(('.invalid','.example','@example.com'))):continue
                    findings.append({'path':rel,'line':i,'rule':rule})
            for n,term in enumerate(deny_terms):
                if term and term.casefold() in line.casefold():findings.append({'path':rel,'line':i,'rule':f'custom_private_term_{n+1}'})
    return {'files_scanned':len(files),'findings':findings,'heuristic_scan_passed':not findings,'human_privacy_review_required':True,
            'screenshot_visual_review_required':screenshots,'screenshot_pixels_scanned':False,
            'screenshot_check_scope':'Only path and file signature; inspect pixels and metadata before publishing.'}


def build(root,out,deny_terms=()):
    root=Path(root).resolve();out=Path(out)
    if out.exists():raise ValueError('Output exists; choose a new release version')
    if any(out.resolve().is_relative_to(root / path) for path in PUBLIC_PATHS):
        raise ValueError('Choose an output path outside the public source paths')
    edition=edition_status(root)
    if edition and (edition['edition']=='local' or not edition['publishable']):
        raise ValueError('Local or non-publishable edition cannot be packaged as a public release')
    report=scan(root,deny_terms)
    if report['findings']:raise ValueError('Privacy scan has findings; inspect scan report before packaging')
    required=['README.md','LICENSE','.codex-plugin/plugin.json','skills/science-achievement-film/SKILL.md']
    if any(not (root/p).is_file() for p in required):raise ValueError('Required release files missing')
    out.parent.mkdir(parents=True,exist_ok=True);prefix='award-video-production'
    with zipfile.ZipFile(out,'x',zipfile.ZIP_DEFLATED) as z:
        for p in file_list(root):z.write(p,prefix+'/'+str(p.relative_to(root)))
    with zipfile.ZipFile(out) as z:
        if z.testzip():raise ValueError('ZIP integrity failed')
    return {**report,'zip_filename':out.name,'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'scope':'Only allowlisted public sources, documentation and synthetic tests. No git history, development files, generated reports or production assets.'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['scan','build']);parser.add_argument('root');parser.add_argument('--out');parser.add_argument('--deny-term',action='append',default=[])
    args=parser.parse_args(argv)
    try:
        if args.command=='build':
            if not args.out:raise ValueError('build requires --out')
            report=build(args.root,args.out,args.deny_term)
        else:report=scan(args.root,args.deny_term)
        print(json.dumps(report,ensure_ascii=False,indent=2));return 2 if report['findings'] else 0
    except (ValueError,OSError) as e:print(json.dumps({'error':str(e)},ensure_ascii=False),file=sys.stderr);return 1


if __name__=='__main__':sys.exit(main())
