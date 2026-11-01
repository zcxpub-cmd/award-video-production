#!/usr/bin/env python3
"""Explicit dependency archives, SHA-256 verification and reversible cleanup.

Never infers authorization from age or a filename. No private paths or services.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import zipfile
import xml.etree.ElementTree as ET

PATH_KEYS = {'source', 'source_path', 'preview_path', 'thumbnail_path', 'voice_path', 'path', 'media_path', 'file_path', 'project_path', 'subtitle_path', 'subtitles', 'bgm_path', 'font_path', 'script_path', 'config_path'}


def load(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def write(p, obj):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(obj,f,ensure_ascii=False,indent=2);f.write('\n')


def journal_write(p,obj):
    """Persist recoverable intent before any file leaves its original location."""
    p=Path(p)
    if p.is_symlink():raise ValueError('Journal must not be a symbolic link')
    fd,name=tempfile.mkstemp(prefix='.journal-',dir=p.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(obj,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        os.replace(name,p)
    finally:
        if os.path.exists(name):os.unlink(name)


def original_path(value):
    """Stored mutation paths must remain canonical; reject replaced parent links."""
    p=Path(value)
    if not p.is_absolute() or p!=p.resolve() or p.is_symlink():
        raise ValueError('Original path changed or contains a symbolic link: '+str(p))
    return p


def same_original(p,row):
    if blocked(p):return False
    s=p.stat()
    return (s.st_dev,s.st_ino)==(row['device'],row['inode']) and sha(p)==row['sha256']


def move_exclusive(source,dest):
    """Same-filesystem move without rename's silent replacement behavior."""
    if dest.exists() or dest.is_symlink():raise ValueError('Move destination already exists: '+str(dest))
    os.link(source,dest,follow_symlinks=False)
    # A crash between link/unlink leaves two recoverable names for the same inode.
    if source.is_symlink() or dest.is_symlink() or not os.path.samefile(source,dest):
        dest.unlink();raise ValueError('Move source changed')
    source.unlink()


def sha(p):
    p=Path(p);a=p.stat();h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    b=p.stat()
    if (a.st_ino,a.st_size,a.st_mtime_ns)!=(b.st_ino,b.st_size,b.st_mtime_ns):raise ValueError('File changed while hashing: '+str(p))
    return h.hexdigest()


def local(s,base):
    if not isinstance(s,str) or not s.strip():raise ValueError('Expected a nonempty local path')
    if '://' in s or s.startswith('~'):raise ValueError('Use resolved local paths, not URLs or tilde paths')
    p=Path(s);return (p if p.is_absolute() else base/p).absolute()


def under(p,root):
    try:p.resolve().relative_to(root.resolve());return True
    except ValueError:return False


def blocked(p):
    if p.is_symlink():return 'symlink requires explicit target selection'
    try:
        s=p.stat()
        if getattr(s,'st_flags',0)&0x40000000:return 'cloud placeholder'
        if not p.is_file():return 'not a regular file'
    except OSError:return 'missing or unreadable'
    return None


def manifest_path(root,rel):
    p=Path(rel)
    if p.is_absolute() or '..' in p.parts:raise ValueError('Unsafe archive member path')
    dest=root/p
    if not under(dest,root):raise ValueError('Archive path escapes root')
    for q in [dest,*dest.parents]:
        if q==root.parent:break
        if q.is_symlink():raise ValueError('Archive contains a symbolic link')
    return dest


def discover(config,out):
    config=Path(config).resolve();data=load(config);base=config.parent
    selected={};unresolved=[];candidates=[]
    def add(s,role,origin):
        try:p=local(s,base)
        except ValueError as e:unresolved.append({'origin':origin,'value':s,'reason':str(e)});return
        why=blocked(p)
        if why:unresolved.append({'origin':origin,'path':str(p),'reason':why});return
        selected[str(p.resolve())]={'path':str(p.resolve()),'role':role,'origin':origin}
    for entry in data.get('files',[]):
        if not isinstance(entry,dict):raise ValueError('files entries must contain path and role')
        add(entry['path'],entry.get('role','input'),'explicit')
    for reference in data.get('references',[]):
        p=local(reference,base)
        add(str(p),'reference','explicit-reference')
        if blocked(p):continue
        if p.suffix.lower()=='.json':
            def walk(x,key='',loc='$'):
                if isinstance(x,dict):
                    for k,v in x.items():walk(v,k,loc+'.'+k)
                elif isinstance(x,list):
                    for i,v in enumerate(x):walk(v,key,loc+f'[{i}]')
                elif key in PATH_KEYS and isinstance(x,str) and x:
                    try:target=local(x,p.parent)
                    except ValueError:candidates.append({'document':str(p),'locator':loc,'value':x,'status':'external_or_unresolved'});return
                    candidates.append({'document':str(p),'locator':loc,'path':str(target),'exists':target.is_file(),'status':'needs_review'})
            walk(load(p))
        elif p.suffix.lower()=='.py':
            tree=ast.parse(p.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node,ast.Call) and ((isinstance(node.func,ast.Name) and node.func.id in {'open','Path'}) or (isinstance(node.func,ast.Attribute) and node.func.attr in {'read_text','read_bytes','load','loadtxt','read_csv'})):
                    if node.args and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str):
                        v=node.args[0].value
                        candidates.append({'document':str(p),'line':node.lineno,'value':v,'status':'needs_review','note':'Relative path may depend on runtime cwd; this is not a resolved dependency.'})
                    else:unresolved.append({'document':str(p),'line':node.lineno,'reason':'dynamic program input needs review'})
        elif p.suffix.lower()=='.drp':
            if not zipfile.is_zipfile(p):
                unresolved.append({'document':str(p),'reason':'DRP is not readable ZIP; export a media manifest from the editor'})
            else:
                with zipfile.ZipFile(p) as z:
                    for member in z.infolist():
                        if member.file_size>32*1024*1024 or not member.filename.lower().endswith('.xml'):continue
                        try:tree=ET.fromstring(z.read(member))
                        except ET.ParseError:continue
                        for node in tree.iter():
                            tag=node.tag.rsplit('}',1)[-1].lower()
                            if 'path' in tag and node.text and node.text.strip():
                                candidates.append({'document':str(p),'member':member.filename,'field':tag,'value':node.text.strip(),'status':'needs_review'})
        else:unresolved.append({'document':str(p),'reason':'No automatic reference parser; inspect runtime inputs manually'})
    result={'schema_version':1,'files':list(selected.values()),'candidates':candidates,'unresolved':unresolved,'dependency_review_complete':False,'note':'Review all actual media/program inputs, explicitly add adopted candidates to files, then set dependency_review_complete true. Reference string scanning cannot prove completeness.'}
    write(out,result);return {'output':str(out),'files':len(selected),'candidates':len(candidates),'unresolved':len(unresolved),'dependency_review_complete':False}


def create(plan,out):
    plan=Path(plan).resolve();data=load(plan);base=plan.parent;out=Path(out).absolute()
    if out.exists() or out.is_symlink():raise ValueError('Archive destination already exists')
    if data.get('dependency_review_complete') is not True:raise ValueError('Complete dependency review before creating a final archive')
    if data.get('unresolved'):raise ValueError('Resolve or explicitly disposition unresolved dependencies before archiving')
    rows=data.get('files',[])
    if not rows:raise ValueError('Archive needs an explicit nonempty file list')
    seen=set();prepared=[]
    for row in rows:
        p=local(row['path'],base)
        if blocked(p):raise ValueError(str(p)+': '+str(blocked(p)))
        p=p.resolve()
        if p in seen:continue
        seen.add(p)
        if under(p,out):raise ValueError('Archive cannot contain its own destination')
        h=sha(p);rel='files/'+h[:16]+'/'+p.name
        prepared.append({'original_path':str(p),'archive_path':rel,'sha256':h,'bytes':p.stat().st_size,'role':row.get('role','input')})
    out.parent.mkdir(parents=True,exist_ok=True)
    temp=Path(tempfile.mkdtemp(prefix='.archive-stage-',dir=out.parent))
    try:
        for entry in prepared:
            dest=manifest_path(temp,entry['archive_path']);dest.parent.mkdir(parents=True,exist_ok=True)
            if not dest.exists():shutil.copy2(entry['original_path'],dest)
            if sha(dest)!=entry['sha256'] or sha(entry['original_path'])!=entry['sha256']:raise ValueError('Copy/source verification failed')
        manifest={'schema_version':1,'dependency_review_complete':True,'plan_sha256':sha(plan),'files':prepared,'path_mapping':{x['original_path']:x['archive_path'] for x in prepared},'editor_reopen_status':'not_verified','playback_status':'not_verified','relocation_status':'requires_editor_relink_or_config_rewrite','created_at_unix':time.time()}
        write(temp/'archive-manifest.json',manifest)
        (temp/'RESTORE.md').write_text('# Restore\n\nRun archive_tools.py verify on this directory. Use path_mapping from archive-manifest.json to relink editor media. rewrite-json can rewrite explicit JSON paths; it does not modify DRP or arbitrary programs. Open the restored native project and play outputs before declaring it rebuildable. This archive uses independent copies, not hard links.\n',encoding='utf-8')
        temp.rename(out)
    except BaseException:shutil.rmtree(temp,ignore_errors=True);raise
    return {'archive':str(out),'file_entries':len(prepared),'hashes_verified':True,'editor_reopen_status':'not_verified'}


def verify(root):
    root=Path(root).resolve();data=load(manifest_path(root,'archive-manifest.json'));errors=[]
    rows=data.get('files') if isinstance(data,dict) else None
    if not isinstance(rows,list) or any(not isinstance(row,dict) or not isinstance(row.get('original_path'),str) or not isinstance(row.get('archive_path'),str) for row in rows):
        return {'archive':str(root),'file_entries':0,'hashes_verified':False,'errors':['invalid manifest file schema'],'editor_reopen_status':'not_verified','playback_status':'not_verified'}
    for entry in data.get('files',[]):
        try:
            p=manifest_path(root,entry['archive_path'])
            if not p.is_file() or sha(p)!=entry['sha256'] or p.stat().st_size!=entry['bytes']:errors.append(entry['archive_path'])
        except (ValueError,OSError,KeyError,TypeError):errors.append(entry.get('archive_path','invalid'))
    if not data.get('files'):errors.append('empty manifest')
    expected={row.get('original_path'):row.get('archive_path') for row in data.get('files',[])}
    if data.get('path_mapping')!=expected:errors.append('path_mapping differs from verified file entries')
    if data.get('dependency_review_complete') is not True:errors.append('dependency review is incomplete')
    return {'archive':str(root),'file_entries':len(data.get('files',[])),'hashes_verified':not errors,'errors':errors,'editor_reopen_status':'not_verified','playback_status':'not_verified'}


def rewrite_json(root,source,out):
    root=Path(root).resolve()
    if not verify(root)['hashes_verified']:raise ValueError('Archive verification failed')
    data=load(root/'archive-manifest.json');mapping=data['path_mapping'];source=Path(source).resolve();count=0;unmapped=[]
    output=Path(out).absolute()
    if output.exists() or output.is_symlink():raise ValueError('Rewrite output already exists')
    output=output.resolve()
    source_base=source.parent
    for row in data['files']:
        if output.resolve()==manifest_path(root,row['archive_path']).resolve():raise ValueError('Do not replace archived source files')
        if source==manifest_path(root,row['archive_path']).resolve():
            source_base=Path(row['original_path']).parent
    def walk(x,key=''):
        nonlocal count
        if isinstance(x,dict):return {k:walk(v,k) for k,v in x.items()}
        if isinstance(x,list):return [walk(v,key) for v in x]
        if isinstance(x,str) and key in PATH_KEYS:
            try:
                raw=local(x,source_base);p=os.path.normpath(str(raw))
                if p not in mapping:p=str(raw.resolve())
            except ValueError as exc:
                if x:unmapped.append({'field':key,'value':x,'reason':str(exc)})
                return x
            if p in mapping:
                count+=1
                return os.path.relpath(manifest_path(root,mapping[p]),output.parent)
            if x:unmapped.append({'field':key,'value':x,'resolved_path':p})
        return x
    result=walk(load(source));write(output,result)
    return {'output':str(output),'rewritten_paths':count,'unmapped_paths':unmapped,'explicit_paths_relocated':not unmapped,'dynamic_program_inputs_verified':False}


def cleanup_plan(config,out):
    config=Path(config).resolve();data=load(config);base=config.parent
    archives=[local(x,base) for x in data.get('verified_archives',[])]
    if not archives or not all(verify(x)['hashes_verified'] for x in archives):raise ValueError('At least one currently verified archive is required')
    protected=[local(x,base).resolve() for x in data.get('protect',[])]+[x.resolve() for x in archives]+[config]
    inode_protected=set()
    for p in protected:
        protected_files=[p] if p.is_file() else p.rglob('*') if p.is_dir() else []
        for item in protected_files:
            if item.is_file() and not item.is_symlink():
                s=item.stat();inode_protected.add((s.st_dev,s.st_ino))
    candidates=[];skipped=[];seen=set();unique_inodes={}
    targets=data.get('targets',[])
    if not targets:raise ValueError('Explicit cleanup targets are required')
    for item in targets:
        target=local(item,base)
        if target.is_symlink():skipped.append({'path':str(target),'reason':'symlink'});continue
        paths=[target] if target.is_file() else sorted(target.rglob('*')) if target.is_dir() else [target]
        for p in paths:
            if p.is_dir() and not p.is_symlink():continue
            why=blocked(p)
            if not why and any(p.resolve()==k or under(p,k) for k in protected):why='protected path'
            if not why:
                s=p.stat()
                if (s.st_dev,s.st_ino) in inode_protected:why='hard link to protected file'
            if why:skipped.append({'path':str(p),'reason':why});continue
            p=p.resolve()
            if p in seen:continue
            seen.add(p);s=p.stat()
            candidates.append({'path':str(p),'sha256':sha(p),'bytes':s.st_size,'device':s.st_dev,'inode':s.st_ino,'nlink':s.st_nlink})
            key=(s.st_dev,s.st_ino);unique_inodes.setdefault(key,{'bytes':s.st_size,'nlink':s.st_nlink,'selected':0})['selected']+=1
    reclaim=sum(v['bytes'] for v in unique_inodes.values() if v['selected']>=v['nlink'])
    result={'schema_version':1,'kind':'cleanup_plan','archives':[str(x) for x in archives],'archive_manifest_hashes':{str(x):sha(x/'archive-manifest.json') for x in archives},'protect':[str(x) for x in protected],'candidates':candidates,'skipped':skipped,'logical_bytes':sum(x['bytes'] for x in candidates),'unique_reclaim_upper_bound_bytes':reclaim,'note':'A plan is not authorization. Moving to quarantine frees no disk space. Shared links, compression and snapshots affect real recovered capacity.'}
    write(out,result);return {'output':str(out),'candidates':len(candidates),'skipped':len(skipped),'reclaim_upper_bound_bytes':reclaim,'plan_sha256':sha(out)}


def quarantine(plan,out,confirm):
    plan=Path(plan).resolve();out=Path(out).absolute();data=load(plan)
    if confirm!=sha(plan) or data.get('kind')!='cleanup_plan':raise ValueError('Exact reviewed plan hash is required')
    if out.exists() or out.is_symlink():raise ValueError('Quarantine output already exists')
    if not data.get('archive_manifest_hashes'):raise ValueError('Protected archive evidence is required')
    protected=[Path(x).resolve() for x in data['protect']]+[Path(x).resolve() for x in data['archive_manifest_hashes']]+[plan]
    if any(under(out,p) for p in protected):raise ValueError('Quarantine cannot be inside a protected path')
    for archive,h in data['archive_manifest_hashes'].items():
        root=Path(archive)
        if sha(root/'archive-manifest.json')!=h or not verify(root)['hashes_verified']:raise ValueError('Protected archive changed or failed verification')
    rows=[];seen=set()
    for row in data['candidates']:
        p=original_path(row['path'])
        if p in seen:raise ValueError('Duplicate cleanup candidate')
        seen.add(p)
        if not same_original(p,row):raise ValueError('Cleanup candidate changed')
        if any(p==q or under(p,q) for q in protected):raise ValueError('Candidate overlaps protected set')
        rows.append({**row,'quarantine_path':f'files/{len(rows):06d}_{p.name}'})
    out.parent.mkdir(parents=True,exist_ok=True)
    if any(row['device']!=out.parent.stat().st_dev for row in data['candidates']):raise ValueError('Use a same-filesystem quarantine directory')
    out.mkdir()
    journal=out/'quarantine-manifest.json'
    record={'schema_version':1,'kind':'quarantine','plan_sha256':confirm,'archive_manifest_hashes':data['archive_manifest_hashes'],'files':rows,'operation_status':'prepared'}
    journal_write(journal,record)
    try:
        for row in rows:
            source=original_path(row['path']);dest=manifest_path(out,row['quarantine_path']);dest.parent.mkdir(exist_ok=True)
            if not same_original(source,row):raise ValueError('Cleanup candidate changed before move')
            move_exclusive(source,dest)
        record['operation_status']='complete';journal_write(journal,record)
    except BaseException:
        failures=[]
        for row in reversed(rows):
            try:
                src=manifest_path(out,row['quarantine_path']);dest=original_path(row['path'])
                if src.exists():
                    if not same_original(src,row):raise ValueError('Quarantine file changed during rollback')
                    if dest.exists():
                        if not os.path.samefile(src,dest):raise ValueError('Rollback target exists')
                        src.unlink()
                    else:move_exclusive(src,dest)
            except (OSError,ValueError) as exc:failures.append({'path':row['path'],'error':str(exc)})
        record.update(operation_status='rollback_incomplete' if failures else 'rolled_back',rollback_errors=failures)
        try:journal_write(journal,record)
        except OSError:pass  # The prepared journal still contains every recovery path.
        raise
    return {'quarantine':str(out),'moved_files':len(rows),'manifest_sha256':sha(journal),'bytes_freed':0}


def restore(root):
    root=Path(root).resolve();data=load(manifest_path(root,'quarantine-manifest.json'))
    if data.get('kind')!='quarantine':raise ValueError('Not a quarantine manifest')
    pending=[];seen=set()
    for row in data['files']:
        p=manifest_path(root,row['quarantine_path']);dest=original_path(row['path'])
        if p in seen:raise ValueError('Duplicate quarantine member')
        seen.add(p)
        if p.exists():
            if not same_original(p,row):raise ValueError('Quarantine changed')
            if dest.exists() and not os.path.samefile(p,dest):raise ValueError('Restore target exists')
            pending.append((p,dest,row))
        elif not same_original(dest,row):raise ValueError('Original and quarantine copy are both missing or changed')
    receipt=manifest_path(root,'restore-receipt.json')
    for source,dest,row in pending:
        original_path(str(dest))
        if not same_original(source,row):raise ValueError('Quarantine changed before restore')
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists():
            if not os.path.samefile(source,dest):raise ValueError('Restore target appeared')
            source.unlink()  # Recover an interrupted exclusive link/unlink move.
        else:move_exclusive(source,dest)
    journal_write(receipt,{'restored_files':len(data['files']),'time':time.time()})
    return {'restored_files':len(data['files'])}


def purge(root,confirm):
    root=Path(root).resolve();manifest=manifest_path(root,'quarantine-manifest.json')
    if sha(manifest)!=confirm:raise ValueError('Exact reviewed quarantine manifest hash required')
    data=load(manifest)
    if data.get('kind')!='quarantine':raise ValueError('Not a quarantine manifest')
    if data.get('operation_status','complete')!='complete':raise ValueError('Incomplete quarantine must be restored, not purged')
    if not data.get('archive_manifest_hashes'):raise ValueError('Protected archive evidence is required')
    for a,h in data['archive_manifest_hashes'].items():
        if sha(Path(a)/'archive-manifest.json')!=h or not verify(a)['hashes_verified']:raise ValueError('Archive no longer verifies')
    progress=manifest_path(root,'purge-progress.json');receipt=manifest_path(root,'purge-receipt.json')
    state=load(progress) if progress.exists() else {'manifest_sha256':confirm,'deleted':[],'pending':None}
    if state.get('manifest_sha256')!=confirm:raise ValueError('Purge progress belongs to a different manifest')
    paths=[];seen=set()
    for row in data['files']:
        p=manifest_path(root,row['quarantine_path'])
        rel=row['quarantine_path']
        if rel in seen:raise ValueError('Duplicate quarantine member')
        seen.add(rel)
        if not p.exists() and (rel in state['deleted'] or rel==state.get('pending')):
            if rel not in state['deleted']:state['deleted'].append(rel)
            continue
        if blocked(p) or not same_original(p,row):raise ValueError('Quarantine changed')
        paths.append((p,row))
    for p,row in paths:
        state['pending']=row['quarantine_path'];journal_write(progress,state)
        if not same_original(p,row):raise ValueError('Quarantine changed before deletion')
        p.unlink();state['deleted'].append(row['quarantine_path']);state['pending']=None;journal_write(progress,state)
    state['pending']=None;journal_write(progress,state)
    result={'deleted_files':len(data['files']),'time':time.time(),'actual_free_space_measurement_required':True}
    journal_write(receipt,result)
    return {'deleted_files':len(data['files']),'actual_free_space_measurement_required':True}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='cmd',required=True)
    for name in ['discover','create','cleanup-plan']:
        a=sub.add_parser(name);a.add_argument('input');a.add_argument('--out',required=True)
    for name in ['verify','restore']:
        a=sub.add_parser(name);a.add_argument('root')
    a=sub.add_parser('rewrite-json');a.add_argument('root');a.add_argument('source');a.add_argument('--out',required=True)
    a=sub.add_parser('quarantine');a.add_argument('plan');a.add_argument('--out',required=True);a.add_argument('--confirm-plan-sha256',required=True)
    a=sub.add_parser('purge');a.add_argument('root');a.add_argument('--confirm-manifest-sha256',required=True)
    args=p.parse_args(argv)
    try:
        if args.cmd=='discover':result=discover(args.input,args.out)
        elif args.cmd=='create':result=create(args.input,args.out)
        elif args.cmd=='verify':result=verify(args.root)
        elif args.cmd=='rewrite-json':result=rewrite_json(args.root,args.source,args.out)
        elif args.cmd=='cleanup-plan':result=cleanup_plan(args.input,args.out)
        elif args.cmd=='quarantine':result=quarantine(args.plan,args.out,args.confirm_plan_sha256)
        elif args.cmd=='restore':result=restore(args.root)
        else:result=purge(args.root,args.confirm_manifest_sha256)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 2 if args.cmd=='verify' and not result['hashes_verified'] else 0
    except (ValueError,OSError,KeyError,SyntaxError,zipfile.BadZipFile) as e:
        print(json.dumps({'error':str(e)},ensure_ascii=False),file=sys.stderr);return 1


if __name__=='__main__':sys.exit(main())
