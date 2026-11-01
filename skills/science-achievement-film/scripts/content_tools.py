#!/usr/bin/env python3
"""Portable document ingestion, editable narration export and shot/claim handoff.

Only reads explicitly supplied files. No network, model, account, or private paths.
"""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
P = '{http://schemas.openxmlformats.org/presentationml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def safe_id(s):
    if not isinstance(s, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', s):
        raise ValueError('IDs must use 1–80 ASCII letters, digits, underscore or hyphen')
    return s


def read_office_xml(z, name):
    info = z.getinfo(name)
    if info.file_size > 32 * 1024 * 1024:
        raise ValueError('XML member exceeds 32 MiB; split the source document first')
    return ET.fromstring(z.read(name))


def ingest(source, out, document_id, pdftotext='pdftotext'):
    source = Path(source).resolve(strict=True)
    safe_id(document_id)
    before = source.stat()
    blocks = []
    warnings = []
    suffix = source.suffix.lower()
    if suffix == '.docx':
        with zipfile.ZipFile(source) as z:
            tree = read_office_xml(z, 'word/document.xml')
            body = tree.find(W + 'body')
            if body is None:
                raise ValueError('DOCX has no document body')
            index = 0
            for child in body:
                if child.tag == W + 'p':
                    text = ''.join(n.text or '' for n in child.iter(W + 't'))
                    if text.strip():
                        index += 1
                        blocks.append({'locator': f'body-p-{index}', 'kind': 'paragraph', 'text': text})
                elif child.tag == W + 'tbl':
                    for rownum, row in enumerate(child.findall(W + 'tr'), 1):
                        cells = ['\n'.join(''.join(n.text or '' for n in p.iter(W + 't')) for p in cell.findall(W + 'p')) for cell in row.findall(W + 'tc')]
                        index += 1
                        blocks.append({'locator': f'body-table-row-{index}', 'kind': 'table_row', 'cells': cells, 'text': ' | '.join(cells)})
        warnings.append('Text and table order extracted; headers, drawings, formulas and visual layout still require source review.')
    elif suffix == '.pptx':
        import posixpath
        with zipfile.ZipFile(source) as z:
            pres = read_office_xml(z, 'ppt/presentation.xml')
            rels = read_office_xml(z, 'ppt/_rels/presentation.xml.rels')
            mapping = {x.attrib['Id']: x.attrib.get('Target', '') for x in rels if x.attrib.get('TargetMode') != 'External'}
            for i, slideid in enumerate(pres.findall('.//' + P + 'sldId'), 1):
                target = mapping.get(slideid.attrib.get(R + 'id'))
                if not target:
                    raise ValueError(f'Slide {i} relationship missing')
                name = posixpath.normpath(posixpath.join('ppt', target)) if not target.startswith('/') else target.lstrip('/')
                if not name.startswith('ppt/'):
                    raise ValueError('Unexpected slide member path')
                slide = read_office_xml(z, name)
                paragraphs = [''.join(n.text or '' for n in x.iter(A + 't')) for x in slide.iter(A + 'p')]
                blocks.append({'locator': f'slide-{i}', 'kind': 'slide', 'text': '\n'.join(paragraphs), 'animation_present': slide.find(P + 'timing') is not None, 'transition_present': slide.find(P + 'transition') is not None})
        warnings.append('Slide text is not slide playback. Watch all relevant animations in presentation mode.')
    elif suffix == '.pdf':
        exe = shutil.which(pdftotext)
        if not exe:
            raise ValueError('PDF text extraction requires pdftotext; OCR is a separate explicit workflow')
        result = subprocess.run([exe, '-layout', str(source), '-'], capture_output=True, timeout=120)
        if result.returncode:
            raise ValueError('pdftotext failed: ' + result.stderr.decode(errors='replace')[-1000:])
        for i, text in enumerate(result.stdout.decode('utf-8', errors='replace').split('\f'), 1):
            if text.strip():
                blocks.append({'locator': f'page-{i}', 'kind': 'page', 'text': text.strip()})
        warnings.append('Text extraction does not validate layout, image-only text, formulas or reading order.')
    elif suffix in {'.txt', '.md', '.csv'}:
        text = source.read_text(encoding='utf-8-sig')
        if suffix == '.csv':
            for i, row in enumerate(csv.reader(text.splitlines()), 1):
                blocks.append({'locator': f'row-{i}', 'kind': 'table_row', 'cells': row, 'text': ' | '.join(row)})
        else:
            for i, paragraph in enumerate(re.split(r'\n\s*\n', text), 1):
                if paragraph.strip():
                    blocks.append({'locator': f'block-{i}', 'kind': 'paragraph', 'text': paragraph.strip()})
    else:
        raise ValueError('Supported: DOCX, PPTX, PDF, TXT, MD, CSV')
    if not blocks or not any(x.get('text', '').strip() for x in blocks):
        raise ValueError('No text extracted; do not treat an empty extraction as a completed analysis')
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('Source changed during extraction')
    result = {'schema_version': 1, 'document_id': document_id, 'source_filename': source.name, 'source_sha256': digest(source), 'blocks': blocks, 'warnings': warnings, 'facts_verified': False}
    save_new(out, result)
    return {'output': str(out), 'blocks': len(blocks), 'facts_verified': False}


def docx_write(path, paragraphs):
    """Minimal editable OOXML; no creator name or personal metadata."""
    contents = []
    for style, text in paragraphs:
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ''
        runs = '<w:br/>'.join(f'<w:t xml:space="preserve">{escape(line)}</w:t>' for line in text.split('\n'))
        contents.append(f'<w:p>{ppr}<w:r>{runs}</w:r></w:p>')
    document = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="' + W[1:-1] + '"><w:body>' + ''.join(contents) + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>'
    types = '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>'
    rels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
    docrels = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'
    styles = '<w:styles xmlns:w="' + W[1:-1] + '"><w:docDefaults><w:rPrDefault><w:rPr><w:sz w:val="24"/></w:rPr></w:rPrDefault></w:docDefaults><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style></w:styles>'
    with zipfile.ZipFile(path, 'x', zipfile.ZIP_DEFLATED) as z:
        for name, data in {'[Content_Types].xml': types, '_rels/.rels': rels, 'word/document.xml': document, 'word/_rels/document.xml.rels': docrels, 'word/styles.xml': styles}.items():
            z.writestr(name, data)


def export_manuscript(path, out):
    data = load(path)
    out = Path(out)
    if out.exists():
        raise ValueError('Output directory already exists; choose a new version')
    title = data.get('project_title', '颁奖视频旁白稿')
    chapters = data.get('chapters')
    if not isinstance(chapters, list) or not chapters:
        raise ValueError('chapters must be a nonempty list')
    rows, seen, prepared = [], set(), []
    allparas = [('Heading1', str(title))]
    for boundary in ['opening']:
        if data.get(boundary):
            allparas += [('Heading1', '片头'), ('', str(data[boundary]))]
    for c in chapters:
        cid = safe_id(c['chapter_id'])
        if cid in seen: raise ValueError('Duplicate chapter ID')
        seen.add(cid)
        if not isinstance(c.get('title'), str) or not c['title'].strip(): raise ValueError('Chapter title is required')
        units = c.get('units', [])
        if not isinstance(units, list) or not all(isinstance(u, str) and u.strip() for u in units): raise ValueError('units must be a list of names')
        sentences = c.get('sentences', [])
        if not sentences: raise ValueError('Each chapter needs sentences with stable IDs')
        paras = [('Heading1', c['title'])]
        if units: paras.append(('', '参与单位：' + '、'.join(units)))
        for s in sentences:
            sid = safe_id(s['id'])
            if sid in seen: raise ValueError('Duplicate sentence ID')
            seen.add(sid)
            if not isinstance(s.get('text'), str) or not s['text'].strip(): raise ValueError('Sentence text is required')
            paras.append(('', s['text']))
            rows.append({'chapter_id': cid, 'sentence_id': sid, 'fact_text': s.get('fact_text', ''), 'narration': s['text'], 'tts_text': s.get('tts_text', s['text']), 'subtitle_text': s.get('subtitle_text', s['text']), 'source_refs': s.get('source_refs', []), 'facts_review_status': s.get('facts_review_status', 'pending')})
        prepared.append((cid, paras))
        allparas.extend(paras)
    if data.get('ending'): allparas += [('Heading1', '片尾'), ('', str(data['ending']))]
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix='manuscript-', dir=out.parent))
    try:
        docx_write(temp/'narration.docx', allparas)
        (temp/'narration.md').write_text('\n\n'.join(('# ' if s else '') + t for s, t in allparas) + '\n', encoding='utf-8')
        for cid, paras in prepared: docx_write(temp/(cid+'.docx'), paras)
        save_new(temp/'text-layers.json', {'project_title': title, 'sentences': rows, 'pronunciations': data.get('pronunciations', [])})
        save_new(temp/'source-manuscript.json', data)
        temp.rename(out)
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return {'output': str(out), 'chapter_documents': len(prepared), 'sentences': len(rows), 'facts_verified': False}


def handoff(manuscript, shots_path, out):
    data = load(manuscript)
    shotdata = load(shots_path)
    shots = shotdata.get('shots', [])
    ids = {s['id'] for c in data['chapters'] for s in c['sentences']}
    if len(ids) != sum(len(c['sentences']) for c in data['chapters']): raise ValueError('Duplicate sentence IDs')
    assets, errors, covered, shotids = [], [], set(), set()
    base = Path(shots_path).resolve().parent
    for s in shots:
        aid = safe_id(s['asset_id'])
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', aid):
            raise ValueError('Asset ID must start with a letter or digit for material wall compatibility')
        if aid in shotids: raise ValueError('Duplicate asset ID')
        shotids.add(aid)
        refs = s.get('sentence_ids', [])
        if not isinstance(refs, list): raise ValueError('sentence_ids must be a list')
        bad = set(refs)-ids
        if bad:errors.append({'asset_id': aid, 'unknown_sentence_ids': sorted(bad)})
        if not refs:errors.append({'asset_id': aid, 'error': 'No sentence references; identify an explicit non-narration purpose'})
        covered.update(set(refs)&ids)
        source = Path(s['source_path'])
        if not source.is_absolute(): source = base/source
        if not source.is_file():errors.append({'asset_id': aid, 'error': 'Missing local source'})
        start, end = s.get('source_in_s', 0), s.get('source_out_s')
        if not isinstance(start, (int, float)) or not math.isfinite(start) or start < 0 or (end is not None and (not isinstance(end,(int,float)) or not math.isfinite(end) or end <= start)):
            raise ValueError('Invalid source range')
        local = s.get('local_codex_generated', False)
        if not isinstance(local, bool): raise ValueError('local_codex_generated must be Boolean')
        if not s.get('semantic_reason'): errors.append({'asset_id': aid, 'error': 'Missing semantic reason'})
        a = dict(s)
        a.update(source_path=str(source.resolve()), display_ai_badge=local, review_status=s.get('review_status','pending'))
        for key in ['preview_path', 'thumbnail_path']:
            if a.get(key):
                linked = Path(a[key])
                if not linked.is_absolute(): linked = base/linked
                a[key] = str(linked.resolve())
                if not linked.is_file(): errors.append({'asset_id': aid, 'error': 'Missing ' + key})
        assets.append(a)
    missing = sorted(ids-covered)
    report = {'schema_version': 1, 'title': data.get('project_title','素材审核墙'), 'assets': assets, 'mapping_check': {'errors': errors, 'uncovered_sentence_ids': missing, 'reference_structure_valid': not errors and not missing, 'semantic_review_status': 'pending', 'note': 'ID coverage is not semantic or scientific verification.'}}
    save_new(out, report)
    return {'output': str(out), 'assets': len(assets), **report['mapping_check']}


def to_project(source, out, fps=25, max_seconds=600):
    """One-way, non-overwriting bridge to filmkit's production-check schema."""
    data=load(source);chapters=[];base=Path(source).resolve().parent
    for c in data['chapters']:
        cid=safe_id(c['chapter_id']);units=c.get('units',[]);narration=[]
        items=[]
        if c.get('speak_title',True):items.append({'id':cid+'-TITLE','text':c['title'],'role':'title'})
        if c.get('speak_units',True) and units:items.append({'id':cid+'-UNITS','text':'、'.join(units),'role':'units'})
        items.extend(c['sentences'])
        for s in items:
            voice=s.get('voice_path')
            if voice:voice=str((base/voice).resolve()) if not Path(voice).is_absolute() else voice
            narration.append({'id':s['id'],'role':s.get('role','body'),'narration_display':s['text'],'narration_tts':s.get('tts_text',s['text']),'voice_duration_s':s.get('voice_duration_s'),'voice_duration_basis':s.get('voice_duration_basis','unmeasured'),'voice_path':voice,'playback_rate':1,'tts_segments':s.get('tts_segments',[]),'subtitle_cues':s.get('subtitle_cues',[])})
        chapters.append({'id':cid,'title':c['title'],'units':units,'protected_terms':c.get('protected_terms',[]),'speak_title':c.get('speak_title',True),'speak_units':c.get('speak_units',True),'protect_title_as_phrase':True,'narration':narration,'transition_duration_s':None,'transition_overlap_s':None,'picture_extension_s':None,'wait_s':None,'picture_plan':[]})
    result={'schema_version':'1.0','title':data.get('project_title',''),'fps':fps,'max_seconds':max_seconds,'runtime':{'definition':'sequential_nonoverlapping_blocks','opening_s':None,'intro_music_standalone_s':None,'ending_s':None,'global_wait_s':None},'chapters':chapters,'approved':[],'revision_queue':[],'notes':['Converted from manuscript. Fill measured audio/timeline durations and picture_plan. Unknowns stay null; no completion is inferred.','This is a one-way snapshot, not automatic synchronization. Reconcile later manuscript changes by stable sentence ID; do not overwrite confirmed measurements.']}
    save_new(out,result);return {'output':str(out),'chapters':len(chapters),'measurements_complete':False}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('ingest'); a.add_argument('source'); a.add_argument('--out',required=True); a.add_argument('--document-id',required=True); a.add_argument('--pdftotext',default='pdftotext')
    a = sub.add_parser('manuscript'); a.add_argument('input'); a.add_argument('--out-dir',required=True)
    a = sub.add_parser('handoff'); a.add_argument('manuscript'); a.add_argument('shots'); a.add_argument('--out',required=True)
    a = sub.add_parser('to-project'); a.add_argument('manuscript'); a.add_argument('--out',required=True); a.add_argument('--fps',type=float,default=25); a.add_argument('--max-seconds',type=float,default=600)
    args=p.parse_args(argv)
    try:
        if args.cmd=='ingest': result=ingest(args.source,args.out,args.document_id,args.pdftotext)
        elif args.cmd=='manuscript': result=export_manuscript(args.input,args.out_dir)
        elif args.cmd=='handoff': result=handoff(args.manuscript,args.shots,args.out)
        else:
            if not math.isfinite(args.fps) or args.fps<=0 or not math.isfinite(args.max_seconds) or args.max_seconds<=0: raise ValueError('fps and max-seconds must be positive and finite')
            result=to_project(args.manuscript,args.out,args.fps,args.max_seconds)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 2 if args.cmd=='handoff' and not result['reference_structure_valid'] else 0
    except (ValueError, OSError, KeyError, ET.ParseError, zipfile.BadZipFile, subprocess.SubprocessError) as e:
        print(json.dumps({'error':str(e)},ensure_ascii=False),file=sys.stderr); return 1


if __name__=='__main__':sys.exit(main())
