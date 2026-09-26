"""Offline reports and review-only contributor intake. Never edits curated definitions."""
from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import tempfile
import zipfile

from encounter_recording import (atomic_json, load_annotations,
                                 parse_annotations, reconstruct_capture, sampled_time, validate_annotation,
                                 validate_boss_id)


def session_summary(folder):
    folder = Path(folder)
    manifest = json.loads((folder/'encounter.json').read_text(encoding='utf8'))
    takes, counts, repeats = [], {}, Counter()
    for path in sorted(folder.glob('take-*/events.jsonl')):
        result = reconstruct_capture(path, manifest['boss_id'])
        relative = path.relative_to(folder).as_posix()
        # Export evidence references relative to the session, never local filesystem paths.
        def portable(value):
            if isinstance(value, dict):
                return {key: relative if key == 'path' else portable(item) for key,item in value.items()}
            if isinstance(value, list):
                return [portable(item) for item in value]
            return value
        result = portable(result)
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
                recording_id=manifest['recording_id'], actions=list(counts.values()), takes=takes,
                repeated_sequences=sequences,
                annotations=load_annotations(folder), review_status='pending',
                limitations=['Observed entries require a change in sampled action identity; starts after gaps are censored.',
                    'Counter-only changes are unverified re-entries. Polling can miss intervening actions.',
                    'Native links retain conditions and support candidates, not proof of execution or verified combos.',
                    'Human interval boundaries and labels require review; no curated definitions are changed.'])


def descriptions_csv(boss_id, labels):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['Boss', 'Take', 'Start seconds', 'End seconds', 'Description', 'Markers', 'Timing confidence'])
    def literal(value):
        text = str(value)
        return "'"+text if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')) else text
    for label in labels:
        writer.writerow(map(literal, [boss_id, label.get('take', ''), label.get('start_t', ''),
            label.get('end_t', ''), label['label'], ', '.join(label['markers']), 'User interval; boundary unverified']))
    return output.getvalue().encode('utf-8-sig')


def export_capture(folder, destination):
    folder, destination = Path(folder), Path(destination)
    manifest = json.loads((folder/'encounter.json').read_text(encoding='utf8'))
    files = {path.relative_to(folder).as_posix(): path.read_bytes()
             for path in sorted(folder.glob('take-*/events.jsonl'))}
    if not files:
        raise ValueError('No recorded data is available to export.')
    if (folder/'labels.jsonl').exists():
        files['labels.jsonl'] = (folder/'labels.jsonl').read_bytes()
    summary = session_summary(folder)
    files['Summary.json'] = json.dumps(summary, indent=2, allow_nan=False).encode('utf8')
    files['Descriptions.csv'] = descriptions_csv(manifest['boss_id'], summary['annotations'])
    export = dict(schema_version=1, kind='tanto_recording', boss_id=manifest['boss_id'],
                  recording_id=manifest['recording_id'], created_at=manifest['created_at'], files=[])
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
            export['files'].append(dict(path=name, sha256=hashlib.sha256(data).hexdigest(), size=len(data)))
        archive.writestr('manifest.json', json.dumps(export, indent=2, allow_nan=False))
    return destination


def intake_bundle(bundle, destination):
    """Validate all members, deduplicate raw evidence and stage a pending review report."""
    bundle, destination = Path(bundle), Path(destination)
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    report_path = destination/'submissions'/f'{digest}.json'
    if report_path.exists():
        return json.loads(report_path.read_text(encoding='utf8'))
    with zipfile.ZipFile(bundle) as archive:
        members = archive.infolist()
        names = [item.filename for item in members]
        if len(names) != len(set(names)) or len(names) > 1024 or sum(item.file_size for item in members) > 512*1024*1024:
            raise ValueError('Bundle has duplicate members or exceeds intake limits')
        allowed = re.compile(r'(manifest\.json|labels\.jsonl|Descriptions\.csv|Summary\.json|take-[0-9]+/events\.jsonl)')
        if any(not allowed.fullmatch(name) for name in names) or 'manifest.json' not in names:
            raise ValueError('Bundle contains an unsupported path or lacks its manifest')
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('kind') != 'tanto_recording' or manifest.get('schema_version') != 1:
            raise ValueError('Unsupported recording bundle')
        boss = validate_boss_id(manifest['boss_id'])
        entries = manifest.get('files', [])
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
    raw = {name:data for name,data in content.items() if name.endswith('/events.jsonl')}
    if not raw:
        raise ValueError('Bundle contains no raw takes')
    labels = parse_annotations(content.get('labels.jsonl', b'').decode('utf8'))
    # Validate timestamps before staging; corrupt event lines remain reportable capture gaps.
    durations = {}
    for name,data in raw.items():
        times = []
        for line in data.decode('utf8', errors='replace').splitlines():
            try:
                value = sampled_time(json.loads(line))
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
    previous = [json.loads(path.read_text(encoding='utf8')) for path in sorted((destination/'submissions').glob('*.json'))]
    hashes = {name: hashlib.sha256(data).hexdigest() for name,data in raw.items()}
    known = {take['sha256'] for report in previous for take in report['takes']}
    report = dict(schema_version=1, bundle_sha256=digest, boss_id=boss, recording_id=manifest.get('recording_id'),
                  review_status='pending', curated_changes=False, takes=[], annotations=labels, conflicts=[])
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
