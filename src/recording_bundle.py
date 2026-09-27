"""Offline reports and review-only contributor intake. Never edits curated definitions."""
# Reports are disposable views of raw takes; a missing report is recoverable, a missing take is not.
# Boss names/descriptions travel with evidence but do not prove who executed any captured action ID.
from collections import Counter
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import zipfile

from encounter_recording import (atomic_json, load_annotations,
                                 parse_annotations, reconstruct_capture, sampled_time, validate_annotation,
                                 validate_boss_id)


def session_summary(folder):
    # Give a reviewer counts and possible strings without deleting player or unidentified actor observations.
    # Reconstruct raw takes and use session-relative references so evidence survives transfer to another PC.
    # Counts are discovery aids; use the raw ending and description to identify the actual requested move.
    folder = Path(folder)
    manifest = json.loads((folder/'encounter.json').read_text(encoding='utf8'))
    takes, counts, repeats = [], {}, Counter()
    for path in sorted(folder.glob('take-*/events.jsonl')):
        result = reconstruct_capture(path, manifest['boss_id'])
        relative = path.relative_to(folder).as_posix()
        # Export evidence references relative to the session, never local filesystem paths.
        def portable(value):
            # Remove machine-specific paths from nested reconstruction evidence.
            # Walk dictionaries/lists and replace each path field with this take's relative JSONL path.
            # Other values retain their original types and meaning for later intake comparison.
            if isinstance(value, dict):
                return {key: relative if key == 'path' else portable(item) for key,item in value.items()}
            if isinstance(value, list):
                return [portable(item) for item in value]
            return value
        result = portable(result)
        # A source number is meaningful together with role, animation and timing, not by number alone.
        by_id = {}
        for action in result['actions']:
            source = action['source']
            key = json.dumps([action['role'], source['action_id'], source['motion_id'],
                              source['timing_id'], source['observed_word0_u16']], separators=(',', ':'))
            by_id[action['id']] = key
            row = counts.setdefault(key, dict(identity=json.loads(key), source=source,
                confidence='attributed_source_identity' if action['role'] == 'boss_candidate' and
                    source['action_id'] is not None and source['motion_id'] is not None else 'identity_unverified',
                observed_entries=0, unverified_reentries=0, censored_observations=0, observations=0))
            for field in ('observed_entries', 'unverified_reentries', 'censored_observations', 'observations'):
                row[field] += action[field]
        for sequence in result['strings']:
            actions = [by_id[action] for action in sequence['actions']]
            # Short repeated windows are hints only: sampling cannot prove the game's combo/input rules.
            for length in range(2, min(4, len(actions)) + 1):
                repeats.update(tuple(actions[offset:offset+length]) for offset in range(len(actions)-length+1))
        takes.append(dict(take=path.parent.name, **result))
    sequences = []
    for keys,count in sorted(repeats.items()):
        if count < 2:
            continue
        links = [[row for row in counts[first]['source'].get('transition_links', [])
                  if row['target_action_id'] == counts[second]['source']['action_id']]
                 for first,second in zip(keys, keys[1:])]
        sequences.append(dict(identities=[json.loads(key) for key in keys], count=count, native_links=links,
            confidence='repeated_order_with_native_links' if all(links) else 'repeated_temporal_order'))
    return dict(schema_version=1, kind='recording_summary', boss_id=manifest['boss_id'],
                boss_name=manifest.get('boss_name',manifest['boss_id']),
                recording_id=manifest['recording_id'], actions=list(counts.values()), takes=takes,
                repeated_sequences=sequences,
                annotations=load_annotations(folder), review_status='pending',
                limitations=['Observed entries require a change in sampled action identity; starts after gaps are censored.',
                    'Counter-only changes are unverified re-entries. Polling can miss intervening actions.',
                    'Native links retain conditions and support candidates, not proof of execution or verified combos.',
                    'Human interval boundaries and labels require review; no curated definitions are changed.'])


def descriptions_csv(boss_id, labels):
    # Produce a readable spreadsheet-friendly list of saved sequence descriptions.
    # Include boss context, take, sampled interval, markers and timing uncertainty.
    # Keep raw observations in their separate files; this CSV is a review aid rather than primary evidence.
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['Boss', 'Take', 'Start seconds', 'End seconds', 'Description', 'Markers', 'Timing confidence'])
    def literal(value):
        # Prevent a contributor's description from becoming a spreadsheet formula.
        # Prefix text beginning with formula/control characters with an apostrophe.
        # CSV quoting still handles commas and newlines; the original annotation text remains unchanged.
        text = str(value)
        return "'"+text if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')) else text
    for label in labels:
        writer.writerow(map(literal, [boss_id, label.get('take', ''), label.get('start_t', ''),
            label.get('end_t', ''), label['label'], ', '.join(label['markers']), 'User interval; boundary unverified']))
    return output.getvalue().encode('utf-8-sig')


def export_capture(folder, destination):
    # Package one complete session while excluding unrelated local files and drafts.
    # Snapshot raw takes and saved revision history, derive reports from those exact bytes, and hash every member.
    # Publish by renaming only after the ZIP closes; existing destinations and partial failures cannot overwrite evidence.
    folder, destination = Path(folder), Path(destination)
    manifest = json.loads((folder/'encounter.json').read_text(encoding='utf8'))
    files = {path.relative_to(folder).as_posix(): path.read_bytes()
             for path in sorted(folder.glob('take-*/events.jsonl'))}
    if not files:
        raise ValueError('No recorded data is available to export.')
    if (folder/'labels.jsonl').exists():
        files['labels.jsonl'] = (folder/'labels.jsonl').read_bytes()
    export = dict(schema_version=1, kind='tanto_recording', boss_id=manifest['boss_id'],
                  boss_name=manifest.get('boss_name',manifest['boss_id']),
                  recording_id=manifest['recording_id'], created_at=manifest['created_at'], files=[])
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Derive reports from the exact exported bytes, even if another UI edits labels.
    # Publish only a fully closed archive; failed writes leave no shareable ZIP.
    with tempfile.TemporaryDirectory(prefix='.tanto-export-',dir=destination.parent) as temporary:
        snapshot=Path(temporary)
        for name,data in files.items():
            path=snapshot/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        (snapshot/'encounter.json').write_text(json.dumps(manifest),encoding='utf8')
        summary=session_summary(snapshot)
        files['Summary.json']=json.dumps(summary,indent=2,allow_nan=False).encode('utf8')
        files['Descriptions.csv']=descriptions_csv(export['boss_name'],summary['annotations'])
        archive_path=snapshot/'share.zip'
        with zipfile.ZipFile(archive_path,'x',compression=zipfile.ZIP_DEFLATED) as archive:
            for name,data in files.items():
                archive.writestr(name,data)
                export['files'].append(dict(path=name,sha256=hashlib.sha256(data).hexdigest(),size=len(data)))
            archive.writestr('manifest.json',json.dumps(export,indent=2,allow_nan=False))
        # Windows rename refuses to overwrite an existing destination.
        archive_path.rename(destination)
    return destination


def export_sessions(folders, destination):
    # Package selected sessions from one or several bosses into a single shareable ZIP.
    # Keep each session in a numbered inner ZIP so identical folder names and take numbers cannot collide.
    # Validate the whole collection before publication, preserving old single-session intake compatibility.
    """Keep each session's names and history isolated inside one shareable collection."""
    folders=list(dict.fromkeys(Path(folder).resolve() for folder in folders))
    if not folders or len(folders)>100:raise ValueError('Select 1–100 saved session folders.')
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.tanto-export-',dir=destination.parent) as temporary:
        temporary=Path(temporary);manifest=dict(schema_version=1,kind='tanto_recording_collection',sessions=[])
        with zipfile.ZipFile(temporary/'collection.zip','x',compression=zipfile.ZIP_STORED) as archive:
            for index,folder in enumerate(folders,1):
                if not (folder/'encounter.json').is_file():
                    raise ValueError(f'{folder.name} is not a saved session. Select its individual session folders.')
                name=f'session-{index:04d}.zip';session=export_capture(folder,temporary/name)
                source=json.loads((folder/'encounter.json').read_text(encoding='utf8'))
                manifest['sessions'].append(dict(path=name,size=session.stat().st_size,
                    sha256=hashlib.sha256(session.read_bytes()).hexdigest(),boss_name=source.get('boss_name',source['boss_id']),
                    recording_id=source['recording_id']))
                archive.write(session,name)
            archive.writestr('manifest.json',json.dumps(manifest,indent=2))
        # Validate all sessions together, including expanded size, before publishing.
        intake_bundle(temporary/'collection.zip',temporary/'validation',validate_only=True)
        (temporary/'collection.zip').rename(destination)
    return destination


def intake_collection(archive, manifest, destination, digest, validate_only):
    # Open a legacy collection of session ZIPs and check every session before staging evidence.
    # Check byte hashes and total expanded size so damaged or unexpectedly large archives fail explicitly.
    # Keep one level of nesting; each session uses the same identity and description checks as a single ZIP.
    sessions=manifest.get('sessions')
    if manifest.get('schema_version')!=1 or not isinstance(sessions,list) or not 1<=len(sessions)<=100:
        raise ValueError('Invalid recording collection')
    if any(not isinstance(item,dict) or not re.fullmatch(r'session-[0-9]{4}\.zip',str(item.get('path','')))
           or type(item.get('size')) is not int or not isinstance(item.get('sha256'),str) for item in sessions):
        raise ValueError('Invalid collection session entry')
    names=[item['path'] for item in sessions]
    if len(names)!=len(set(names)) or set(archive.namelist())!=set(names)|{'manifest.json'}:
        raise ValueError('Collection does not describe its members')
    with tempfile.TemporaryDirectory(prefix='tanto-collection-') as temporary:
        expanded=0;paths=[]
        for item in sessions:
            data=archive.read(item['path'])
            if len(data)!=item['size'] or hashlib.sha256(data).hexdigest()!=item['sha256']:
                raise ValueError('Collection hash or size mismatch')
            path=Path(temporary)/item['path'];path.write_bytes(data);paths.append(path)
            with zipfile.ZipFile(path) as inner:
                expanded+=sum(info.file_size for info in inner.infolist())
                if expanded>512*1024*1024:raise ValueError('Collection exceeds expanded intake size limit')
                child=json.loads(inner.read('manifest.json'))
                if not isinstance(child,dict) or child.get('kind')!='tanto_recording':
                    raise ValueError('Collections can contain only individual recording bundles')
            intake_bundle(path,destination,validate_only=True)
        if validate_only:return
        report=dict(schema_version=1,kind='tanto_recording_collection',bundle_sha256=digest,
                    review_status='pending',curated_changes=False,
                    sessions=[intake_bundle(path,destination) for path in paths])
        target=destination/'collections'/f'{digest}.json';target.parent.mkdir(parents=True,exist_ok=True)
        atomic_json(target,report)
        return report


def file_sha256(path):
    # Identify exact evidence bytes without loading a long recording or ZIP into RAM.
    # Read fixed-size chunks; filenames and folder names do not affect the result.
    # The hash names immutable submissions and detects changed archive members.
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def intake_session_archive(archive, manifest, destination, digest, validate_only):
    # Retain every selected session, including draft-only sessions with no captured IDs.
    # Validate paths/hashes, then stream files into a temporary folder on the destination disk.
    # Publish the whole folder only after all checks pass; reports never edit playable MWM data.
    sessions, entries = manifest.get('sessions'), manifest.get('files')
    if manifest.get('schema_version') != 2 or not isinstance(sessions, list) or not sessions:
        raise ValueError('Invalid session archive manifest')
    if not isinstance(entries, list) or not entries or len(entries) > 99999 or len(sessions) > len(entries):
        raise ValueError('Invalid session archive file list')

    def safe_path(name):
        # Accept portable relative ZIP names whose Windows extraction has one unambiguous meaning.
        # Reject traversal, alternate streams, reserved devices and aliases caused by trailing dots/spaces.
        # Paths are checked before any payload is opened or written to the staging directory.
        if not isinstance(name, str) or any(c in name for c in '\\<>:"|?*') or any(ord(c) < 32 for c in name):
            raise ValueError('Unsafe archive path')
        parts = name.split('/')
        if any(not part or part in ('.', '..') or part.endswith((' ', '.')) or
               re.fullmatch(r'(?i:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])', part.split('.')[0]) for part in parts):
            raise ValueError('Unsafe archive path: ' + name)
        return parts

    roots, recording_ids = {}, set()
    for session in sessions:
        if not isinstance(session, dict):
            raise ValueError('Invalid session entry')
        parts = safe_path(session.get('path'))
        identity = session.get('recording_id')
        if len(parts) != 2 or parts[0] != 'sessions' or not isinstance(identity, str) or not identity:
            raise ValueError('Invalid session path or recording identity')
        key = session['path'].casefold()
        if key in roots or identity in recording_ids or not isinstance(session.get('boss_name'), str):
            raise ValueError('Duplicate session or invalid boss label')
        roots[key] = session
        recording_ids.add(identity)
    listed = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Invalid archive file entry')
        parts = safe_path(entry.get('path'))
        key = entry['path'].casefold()
        if len(parts) < 3 or '/'.join(parts[:2]).casefold() not in roots or key in listed:
            raise ValueError('Duplicate file or file outside selected sessions')
        if type(entry.get('size')) is not int or entry['size'] < 0 or not re.fullmatch('[0-9a-f]{64}', str(entry.get('sha256'))):
            raise ValueError('Invalid archive file size or hash')
        listed[key] = entry
    members = archive.infolist()
    if len(members) != len(entries) + 1:
        raise ValueError('Manifest does not describe every archive member')
    seen = set()
    for info in members:
        parts = safe_path(info.filename)
        key = info.filename.casefold()
        mode = stat.S_IFMT(info.external_attr >> 16)
        if key in seen or mode not in (0, stat.S_IFREG) or info.is_dir() or info.flag_bits & 1:
            raise ValueError('Duplicate, encrypted or non-regular archive member')
        seen.add(key)
        if info.filename == 'manifest.json':
            continue
        entry = listed.get(key)
        if entry is None or info.filename != entry['path'] or info.file_size != entry['size']:
            raise ValueError('Manifest path or size mismatch: ' + info.filename)
        if any('/'.join(parts[:end]).casefold() in listed for end in range(1, len(parts))):
            raise ValueError('Archive file also used as a directory')
    if seen != set(listed) | {'manifest.json'}:
        raise ValueError('Manifest does not describe every archive member')

    def small_json(path):
        # Read bounded session metadata, not the potentially multi-gigabyte action journal.
        # A malformed metadata document fails intake while the original ZIP remains untouched.
        # Raw payload extraction itself has no arbitrary session-size ceiling.
        with path.open('rb') as stream:
            data = stream.read(16 * 1024 * 1024 + 1)
        if len(data) > 16 * 1024 * 1024:
            raise ValueError('Session metadata exceeds 16 MiB: ' + path.name)
        return json.loads(data)

    def count_records(path, kind):
        # Count usable action or saved-description rows; damaged lines remain visible as review warnings.
        # Bound each parser read so a damaged line cannot consume memory proportional to the take.
        # All actor roles count; description revisions count as history rows, not distinct verified moves.
        count = damaged = 0
        with path.open('rb') as stream:
            while line := stream.readline(1024 * 1024):
                if not line.endswith(b'\n') and len(line) == 1024 * 1024:
                    while line and not line.endswith(b'\n'):
                        line = stream.readline(1024 * 1024)
                    damaged += 1
                    continue
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict) or not isinstance(event.get('kind'), str):
                        raise ValueError('Invalid event')
                    count += event['kind'] == kind
                except (ValueError, UnicodeError):
                    damaged += 1
        return count, damaged

    submissions = destination / 'submissions'
    if not validate_only:
        submissions.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.tanto-intake-', dir=submissions if not validate_only else None) as temporary:
        stage = Path(temporary) / 'archive'
        stage.mkdir()
        if sum(info.file_size for info in members) > shutil.disk_usage(stage).free:
            raise ValueError('Not enough free disk space to retain the expanded recording archive')
        # Extraction computes hashes from exactly the bytes written; it never calls extractall.
        for info in members:
            target = stage.joinpath(*info.filename.split('/'))
            target.parent.mkdir(parents=True, exist_ok=True)
            checksum, size = hashlib.sha256(), 0
            with archive.open(info) as source, target.open('xb') as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
                    checksum.update(chunk)
                    size += len(chunk)
                output.flush()
                os.fsync(output.fileno())
            if info.filename != 'manifest.json':
                entry = listed[info.filename.casefold()]
                if size != entry['size'] or checksum.hexdigest() != entry['sha256']:
                    raise ValueError('Archive file hash or size mismatch: ' + info.filename)
        report = dict(schema_version=2, kind='tanto_session_archive', bundle_sha256=digest,
                      review_status='pending', curated_changes=False, sessions=[])
        for session in sessions:
            folder = stage / session['path']
            encounter = small_json(folder / 'encounter.json')
            if not isinstance(encounter, dict) or encounter.get('schema_version') not in (1, 2) or encounter.get('recording_id') != session['recording_id'] or encounter.get('boss_name', encounter.get('boss_id')) != session['boss_name']:
                raise ValueError('Session identity disagrees with archive manifest')
            annotations = encounter.get('annotations', [])
            if not isinstance(annotations, list):
                raise ValueError('Invalid saved description list')
            draft = encounter.get('draft', {})
            if encounter.get('schema_version') != 2 and (folder / 'draft.json').is_file():
                draft = small_json(folder / 'draft.json')
            annotation_count, damaged_labels = len(annotations), 0
            if encounter.get('schema_version') != 2 and (folder / 'labels.jsonl').is_file():
                annotation_count, damaged_labels = count_records(folder / 'labels.jsonl', 'user_label')
            action_rows = damaged = 0
            for path in [folder / 'events.jsonl', *folder.glob('take-*/events.jsonl')]:
                if path.is_file():
                    count, issues = count_records(path, 'action_state')
                    action_rows += count
                    damaged += issues
            report['sessions'].append(dict(path=session['path'], recording_id=session['recording_id'],
                boss_name=session['boss_name'], action_rows=action_rows, annotation_count=annotation_count,
                has_draft=bool(draft.get('text')) if isinstance(draft, dict) else bool(draft),
                malformed_event_lines=damaged, malformed_description_lines=damaged_labels,
                no_raw_evidence=action_rows == 0))
        if validate_only:
            return report
        atomic_json(stage / 'review.json', report)
        # Same-volume rename publishes complete evidence once; it cannot overwrite an existing submission.
        stage.rename(submissions / digest)
    return report


def intake_bundle(bundle, destination, *, validate_only=False):
    # Check a submitted ZIP, then retain its evidence in the developer's pending-review store.
    # Permit only declared paths and verify exact byte hashes before trusting descriptions or reconstructing data.
    # Reuse identical take bytes by SHA-256; conflicting descriptions are reported, never silently resolved.
    # Successful intake means readable evidence, not a tested move or permission to change MWM's definitions.
    """Validate all members, deduplicate raw evidence and stage a pending review report."""
    bundle, destination = Path(bundle), Path(destination)
    digest = file_sha256(bundle)
    report_path = destination/'submissions'/f'{digest}.json'
    for cached in (report_path,destination/'collections'/f'{digest}.json', destination/'submissions'/digest/'review.json'):
        if cached.exists() and not validate_only:return json.loads(cached.read_text(encoding='utf8'))
    with zipfile.ZipFile(bundle) as archive:
        members = archive.infolist()
        names = [item.filename for item in members]
        if len(names) != len(set(names)) or len(names) > 100000:
            raise ValueError('Bundle has duplicate members or exceeds intake limits')
        if 'manifest.json' in names and archive.getinfo('manifest.json').file_size > 32 * 1024 * 1024:
            raise ValueError('Archive manifest exceeds 32 MiB')
        manifest=json.loads(archive.read('manifest.json')) if 'manifest.json' in names else None
        if isinstance(manifest,dict) and manifest.get('kind')=='tanto_session_archive':
            return intake_session_archive(archive,manifest,destination,digest,validate_only)
        if len(names) > 1024 or sum(item.file_size for item in members) > 512*1024*1024:
            raise ValueError('Legacy bundle exceeds intake limits')
        if isinstance(manifest,dict) and manifest.get('kind')=='tanto_recording_collection':
            return intake_collection(archive,manifest,destination,digest,validate_only)
        allowed = re.compile(r'(manifest\.json|labels\.jsonl|Descriptions\.csv|Summary\.json|take-[0-9]+/events\.jsonl)')
        if any(not allowed.fullmatch(name) for name in names) or 'manifest.json' not in names:
            raise ValueError('Bundle contains an unsupported path or lacks its manifest')
        if not isinstance(manifest,dict) or manifest.get('kind') != 'tanto_recording' or manifest.get('schema_version') != 1:
            raise ValueError('Unsupported recording bundle')
        boss = validate_boss_id(manifest.get('boss_id'))
        entries = manifest.get('files', [])
        if not isinstance(entries,list) or any(not isinstance(item,dict) or
                not isinstance(item.get('path'),str) or not isinstance(item.get('sha256'),str) or
                type(item.get('size')) is not int or item['size']<0 for item in entries):
            raise ValueError('Invalid manifest file entries')
        listed = [item['path'] for item in entries]
        # Legacy exports did not hash Descriptions.csv; new exports hash every derived file too.
        if len(listed) != len(set(listed)) or set(listed) - (set(names)-{'manifest.json'}) or set(names)-set(listed)-{'manifest.json', 'Descriptions.csv'}:
            raise ValueError('Manifest does not describe the bundle members')
        content = {}
        for item in entries:
            data = archive.read(item['path'])
            if len(data) != item['size'] or hashlib.sha256(data).hexdigest() != item['sha256']:
                raise ValueError('Bundle hash or size mismatch: '+item['path'])
            content[item['path']] = data
    # Derived CSV/JSON reports cannot stand in for missing action observations.
    raw = {name:data for name,data in content.items() if name.endswith('/events.jsonl')}
    if not raw:
        raise ValueError('Bundle contains no raw takes')
    labels = parse_annotations(content.get('labels.jsonl', b'').decode('utf8'))
    # Validate timestamps before staging; corrupt event lines remain reportable capture gaps.
    durations, context_conflicts = {}, []
    for name,data in raw.items():
        times = []
        for line in data.decode('utf8', errors='replace').splitlines():
            try:
                event=json.loads(line)
                context=event.get('encounter_context') if isinstance(event,dict) else None
                if isinstance(context,dict) and context.get('boss_id',boss)!=boss:
                    context_conflicts.append(dict(kind='capture_context',take=name.split('/')[0],
                        recorded_boss_id=context['boss_id'],submitted_boss_id=boss))
                value = sampled_time(event)
                if value is not None:
                    times.append(value)
            except (ValueError, AttributeError):
                continue
        durations[name.split('/')[0]] = max(times, default=0)
    for label in labels:
        validate_annotation(label, durations)
        if label.get('boss_id', boss) != boss:
            raise ValueError('Annotation boss conflicts with bundle identity')
    reconstructions = {}
    with tempfile.TemporaryDirectory(prefix='tanto-intake-') as temporary:
        path = Path(temporary)/'events.jsonl'
        for name,data in raw.items():
            path.write_bytes(data)
            try:
                reconstructions[name] = reconstruct_capture(path, boss)
            except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
                raise ValueError('Unsupported capture structure: '+name) from error
    if validate_only:return
    # Review identity is the raw file hash, not its filename: a renamed resubmission is still the same take.
    previous = [json.loads(path.read_text(encoding='utf8')) for path in sorted((destination/'submissions').glob('*.json'))]
    hashes = {name: hashlib.sha256(data).hexdigest() for name,data in raw.items()}
    known = {take['sha256'] for report in previous for take in report['takes']}
    report = dict(schema_version=1, bundle_sha256=digest, boss_id=boss, recording_id=manifest.get('recording_id'),
                  boss_name=manifest.get('boss_name',boss),
                  review_status='pending', curated_changes=False, takes=[], annotations=labels, conflicts=context_conflicts)
    for name,data in raw.items():
        sha = hashes[name]
        blob = destination/'captures'/f'{sha}.jsonl'
        blob.parent.mkdir(parents=True, exist_ok=True)
        if not blob.exists():
            with blob.open('xb') as handle:
                handle.write(data)
        elif hashlib.sha256(blob.read_bytes()).hexdigest() != sha:
            raise ValueError('Stored intake evidence failed its hash check')
        reconstruction = reconstructions[name]
        for gap in reconstruction['gaps']:
            gap['evidence']['path'] = blob.relative_to(destination).as_posix()
        report['takes'].append(dict(take=name.split('/')[0], sha256=sha, duplicate=sha in known,
            complete=reconstruction['complete'], issues=reconstruction['issues'], gaps=reconstruction['gaps']))
        known.add(sha)
        for old in previous:
            if old['boss_id'] != boss and any(take['sha256'] == sha for take in old['takes']):
                report['conflicts'].append(dict(kind='boss_identity', sha256=sha, other_boss_id=old['boss_id']))
    def source_hash(label, take_hashes):
        # Find the raw-take fingerprint underlying one description.
        # Translate its take name into the corresponding events.jsonl entry in the supplied hash map.
        # Conflict checks use byte identity so renamed submissions cannot hide contradictory descriptions.
        return take_hashes[label['take']+'/events.jsonl']
    for label in labels:
        sha = source_hash(label, hashes)
        candidates = [(other, hashes) for other in labels if other['label_id'] != label['label_id']]
        for old in previous:
            candidates.extend((other, {take['take']+'/events.jsonl':take['sha256'] for take in old['takes']})
                              for other in old['annotations'])
        for other, other_hashes in candidates:
            if (source_hash(other, other_hashes) == sha and max(label['start_t'], other['start_t']) <= min(label['end_t'], other['end_t'])
                    and label['label'].strip().casefold() != other['label'].strip().casefold()):
                report['conflicts'].append(dict(kind='overlapping_labels', sha256=sha,
                    label=label['label'], other_label=other['label'], start_t=label['start_t'], end_t=label['end_t']))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(report_path, report)
    return report
