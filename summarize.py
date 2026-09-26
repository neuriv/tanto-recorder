"""Rebuild the common capture report without changing raw evidence or curated labels."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT/'src'), str(ROOT.parent/'tanto-engine/runtime')]
from encounter_recording import reconstruct_capture
def iter_moves(catalogue):
    # Keep the curated string hierarchy while joining per-action source identities.
    # Aliases are deduplicated by the report's source key.
    # Recording statistics never change playable definitions.
    for move in catalogue['moves']:
        yield move
        yield from iter_moves({'moves':move.get('steps',[])})



def capture_report(index, catalogue):
    # Count observed entries for known sword identities, scoped to boss and source bank.
    # Deduplicate raw hashes and keep uncertain starts separate from measured entries.
    # Preserve descriptions verbatim; temporal adjacency never proves a native combo.
    known = {}
    for move in iter_moves(catalogue):
        source = move.get('source', {})
        key = (move['boss_id'], source.get('action_id'), source.get('motion_id'), source.get('timing_id'))
        known.setdefault(key, []).append(move['name'])
    counts, seen, sources, labels = {}, set(), [], []
    for item in index['sources']:
        path = ROOT/item['path']
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != item['sha256']:
            raise ValueError('Capture changed: '+item['path'])
        if digest in seen:
            continue
        seen.add(digest)
        if item['format'] == 'labels':
            labels.extend(dict(source=item['path'], line=n, annotation=json.loads(line))
                          for n,line in enumerate(path.read_text(encoding='utf8').splitlines(),1) if line.strip())
            continue
        if item['format'] != 'sampled_states':
            sources.append(dict(item, ranking='Excluded: native calls may overlap sampled states; attribution differs.'))
            continue
        capture = reconstruct_capture(path, item['boss_id'])
        accepted = 0
        for action in capture['actions']:
            source = action['source']
            key = (item['boss_id'], source['action_id'], source['motion_id'], source['timing_id'])
            if action['role'] != 'boss_candidate' or key not in known:
                continue
            accepted += action['observations']
            row = counts.setdefault(key, dict(boss_id=key[0], action_id=key[1], motion_id=key[2],
                timing_id=key[3], names=known[key], observed_entries=0, censored_observations=0,
                state_samples=0, captures=[]))
            row['observed_entries'] += action['observed_entries']
            row['censored_observations'] += action['censored_observations']
            row['state_samples'] += action['observations']
            if item['path'] not in row['captures']:
                row['captures'].append(item['path'])
        sources.append(dict(item, matched_sword_samples=accepted, issues=capture['issues'],
                            ranking='Retained sword sample only' if accepted else 'No attributed known sword observations'))
    return dict(schema_version=1, sources=sources, labels=labels,
        occurrences=sorted(counts.values(),key=lambda r:(r['boss_id'],-r['observed_entries'],r['action_id'])),
        limitations=['Targeted recordings are not unbiased boss move probabilities.',
                    'Entries count descriptor or action-counter changes; first observations after gaps are censored.',
                    'State samples are not move occurrences. Polling can miss short actions.',
                    'Aliases share one source identity; native traces and unassigned actors are excluded.',
                    'Human labels preserve notice-time uncertainty and do not prove exact string boundaries.'])


if __name__ == '__main__':
    index = ROOT/'captures/index.json'
    report = capture_report(json.loads(index.read_text()),json.loads((ROOT/'data/catalogue.json').read_text(encoding='utf8')))
    (index.parent/'summary.json').write_text(json.dumps(report,indent=2,ensure_ascii=True)+'\n',encoding='utf8')
    print(f"{len(report['sources'])} captures, {len(report['labels'])} labels, {len(report['occurrences'])} ranked sword identities")
