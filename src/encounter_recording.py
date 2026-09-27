# User-started, read-only encounter recording and interruption-safe reconstruction.
#
# No video, screenshots, hooks, writes to game memory, or calibration. The trainer
# calls main() in its encounter worker, or record_encounter() on a worker thread.
# Importing this module neither attaches to Nioh nor accesses a controller.
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import sys
import threading
import time
import uuid


ROOT = Path(os.environ.get('TANTO_PRODUCT_ROOT', Path(__file__).resolve().parents[1]))
BOSSES = {boss['id']: boss for boss in json.loads((ROOT/'data/bosses.json').read_text(encoding='utf8'))}
DEFAULT_SIGNATURES = {key: boss['capture_signature'] for key,boss in BOSSES.items() if 'capture_signature' in boss}
PLAYER_SIGNATURE = [{'action_id': 0xC64, 'motion_id': 2033}]
GAP_EVENTS = {'object_unreadable', 'snapshot_race', 'tracked_actor_changed',
              'rediscovery_required', 'sampling_gap', 'session', 'end'}


def atomic_json(path, value):
    # Persist one complete manifest or status document through atomic replacement.
    # Flush and sync its unique temporary file before replacing the destination.
    # Retain the previous document if serialization or writing fails.
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf8') as handle:
            json.dump(value, handle, indent=2, allow_nan=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_boss_id(boss_id):
    # Enforce a bounded stable identifier for encounter ownership.
    # Accept lowercase names with only the documented separators.
    # Prevent accidental path-like identifiers in catalogue and capture records.
    if not isinstance(boss_id, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,79}', boss_id):
        raise ValueError('Boss id must use 1..80 lowercase letters, digits, dots, dashes or underscores')
    return boss_id


def capture_events(source, issues):
    # Stream saved JSONL records while retaining line-numbered parse errors.
    # Emit a gap marker for corrupt or malformed observations.
    # Recover later evidence without stitching across damaged data.
    # Preserve valid records after corrupt lines; corruption is a continuity gap.
    with Path(source).open('r', encoding='utf8', errors='replace') as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                if not isinstance(event, dict) or not isinstance(event.get('kind'), str):
                    raise ValueError('Expected an event object with a kind')
                if 't' in event and (not isinstance(event['t'], (int, float))
                                     or not 0 <= event['t'] < float('inf')):
                    raise ValueError('Invalid sampled timestamp')
                yield line_number, event
            except (ValueError, TypeError) as error:
                issues.append({'line': line_number, 'error': str(error)})
                yield line_number, {'kind': 'corrupt_record'}


def decode_action_metadata(event):
    # Decode stable action, motion and timing fields from saved byte prefixes.
    # Preserve native gates and contact rows without promoting temporal adjacency into combos.
    # Keep permanent move identities independent of runtime addresses.
    raw = bytes.fromhex(event.get('descriptor_bytes', ''))
    payload = bytes.fromhex((event.get('payload_prefix') or {}).get('bytes', ''))
    result = {}
    if len(raw) >= 4:
        result['action_id'] = struct.unpack_from('<I', raw)[0]
    if len(payload) >= 0x38:
        motion, override = struct.unpack_from('<i', payload, 0x20)[0], struct.unpack_from('<i', payload, 0x34)[0]
        result.update(motion_id=motion, timing_override=override,
                      timing_id=motion if override < 0 else override,
                      flags=struct.unpack_from('<Q',payload,0x18)[0],
                      ki_cost=struct.unpack_from('<h',payload,0x16)[0],
                      recovery_frame=struct.unpack_from('<h',payload,0x24)[0],
                      cancel_frame=struct.unpack_from('<h',payload,0x26)[0],ki_pulse_percent=payload[0x33])
    if len(payload)>=0x3E:
        result.update(zip(('ki_pulse_start','ki_pulse_fill','ki_pulse_hold'),struct.unpack_from('<hhh',payload,0x38)))
    for name,size in [('transition',48),('combat',128)]:
        if name+'_slice' in event:
            result[name+'_rows_total']=event[name+'_slice']['count']
        omitted='entries_omitted' if name=='transition' else 'combat_entries_omitted'
        if omitted in event:
            result[name+'_rows_omitted']=event[omitted]
        rows=[]; legacy_targets=set()
        for index,row in enumerate(event.get(name+'_entries',[])):
            if 'bytes' not in row:
                # Older target-only observations retain their weaker evidence without guessed gates.
                if name=='transition' and row.get('target_key_0x14_i16',-1)>=0:
                    legacy_targets.add(row['target_key_0x14_i16'])
                continue
            body=bytes.fromhex(row['bytes'])
            if len(body)!=size:
                raise ValueError(f'{name} row {index} has {len(body)} bytes; expected {size}')
            decoded={'row_index':row.get('slice_index',index),'raw_hex':body.hex()}
            if name=='combat':
                decoded.update(flags=f'0x{struct.unpack_from("<Q",body)[0]:016X}',
                    ground_horizontal=body[0x16],ground_vertical=struct.unpack_from('<b',body,0x17)[0],
                    air_horizontal=body[0x1A],air_vertical=struct.unpack_from('<b',body,0x1B)[0])
            else:
                conditions=list(struct.unpack_from('<5H',body)); flags=struct.unpack_from('<I',body,0x1C)[0]
                window=list(struct.unpack_from('<hh',body,0x20)); kind='conditional'
                if body[0x0B]!=255:
                    kind='native_input'
                elif conditions[0]==22:
                    kind='paired_contact'
                elif conditions==[65535]*5 and body[0x0A]==1 and flags&4 and not flags&0x2000040 and window[1]==32767:
                    kind='animation_end'
                decoded.update(target_action_id=struct.unpack_from('<h',body,0x14)[0],kind=kind,
                    conditions=conditions,mode=body[0x0A],input_id=body[0x0B],selectors=list(body[0x0C:0x14]),
                    target_options=list(body[0x16:0x1C]),flags=flags,window_frames=window)
            rows.append(decoded)
        if rows:
            result['transition_links' if name=='transition' else 'combat_rows']=rows
        if legacy_targets:
            result['transition_targets']=sorted(legacy_targets)
    return result


def reconstruct_capture(source, boss_id, destination=None):
    # Turn sampled observations into action identities and candidate sequences for review.
    # Use stable actor/action/motion identities, keeping raw addresses only in the original capture.
    # Split at malformed lines and observation gaps; consecutive samples alone do not prove a combo.
    validate_boss_id(boss_id)
    source = Path(source)
    digest = hashlib.sha256()
    with source.open('rb') as handle:
        for chunk in iter(lambda: (
            # Read the next bounded chunk for a file hash.
            # An empty chunk terminates the sentinel iterator at end of file.
            # Avoid copying the entire executable or capture into memory to fingerprint it.
            handle.read(1024 * 1024)), b''):
            digest.update(chunk)
    issues = []
    # Pair metadata only with its immediately preceding, owner-validated state.
    # Later repeats can reuse it only while the same actor/payload/key remains.
    trusted = {}
    last_state = {}
    cache = {}
    for number, event in capture_events(source, issues):
        kind, obj = event['kind'], event.get('object')
        if kind in GAP_EVENTS or kind == 'corrupt_record':
            if obj:
                last_state.pop(obj, None)
            else:
                last_state.clear()
            if kind in ('session', 'tracked_actor_changed', 'object_unreadable', 'corrupt_record'):
                cache.clear()
        if kind == 'action_state':
            descriptor = event.get('descriptor') or {}
            signature = (obj, event.get('owner_like'), event.get('current'),
                         descriptor.get('payload'), descriptor.get('word0_u16', descriptor.get('word0_hex')))
            last_state[obj] = (number, event, signature)
            if signature in cache:
                trusted[number] = cache[signature]
        if kind == 'metadata' and event.get('matches_preceding_state') is True and obj in last_state:
            state_number, state, signature = last_state[obj]
            if (state.get('current') != event.get('address') or
                    state.get('owner_matches_discovery') is False or
                    (state.get('descriptor') or {}).get('payload') != event.get('payload')):
                continue
            try:
                decoded = decode_action_metadata(event)
            except (ValueError, struct.error) as error:
                issues.append({'line': number, 'error': 'Invalid metadata: ' + str(error)})
                continue
            descriptor = state.get('descriptor') or {}
            observed_word = descriptor.get('word0_u16')
            if (decoded.get('action_id') is not None and
                    ((observed_word is not None and decoded['action_id'] & 0xFFFF != observed_word) or
                     (descriptor.get('action_key_u32') is not None and
                      decoded['action_id'] != descriptor['action_key_u32']))):
                issues.append({'line': number, 'error': 'Metadata action key disagrees with its state'})
                continue
            trusted[state_number] = cache[signature] = decoded

    actions, successors, strings, unclassified, labels, current, identities = {}, {}, [], [], {}, {}, {}
    gaps = []
    generation = 0
    started = ended = False
    def evidence(number, event):
        # Attach a source path, line and sampled time to an observation.
        # Keep references small enough to retain beside each action and edge.
        # Allow labels to be traced back to their original capture.
        return {'path': str(source), 'line': number, 't': event.get('t')}
    def close(label, reason):
        # Finish one actor's current temporal sequence at a named boundary.
        # Retain multi-action strings and discard singleton sequence wrappers.
        # Keep action records themselves even when no relationship was observed.
        string = current.pop(label, None)
        if string and len(string['actions']) > 1:
            string.pop('serial', None)
            strings.append(dict(string, break_reason=reason, relationship='sampled_temporal_order'))
    def close_all(reason):
        # Close every active actor sequence at a shared observation gap.
        # Iterate a snapshot because closing removes entries from the current map.
        # Prevent cross-gap successor relationships for any actor.
        for label in list(current):
            close(label, reason)
    def actor_label(event):
        # Assign capture-local labels to generation, owner and role identities.
        # Split a sequence whenever an address acquires a different identity.
        # Avoid carrying boss attribution through allocator address reuse.
        obj = event.get('object')
        role = event.get('role', 'unassigned')
        identity = (generation, obj, event.get('owner_like'), role)
        if identity not in identities:
            base = 'boss' if role == 'boss_candidate' else 'player' if role == 'player_candidate' else 'unassigned'
            identities[identity] = base + '-' + str(len(identities) + 1)
        if obj in labels and labels[obj] != identities[identity]:
            close(labels[obj], 'actor_identity_changed')
        labels[obj] = identities[identity]
        return labels[obj]

    # Parse errors were collected in pass one; do not duplicate those diagnostics.
    for number, event in capture_events(source, []):
        kind = event['kind']
        if kind == 'session':
            started = True
            ended = False
            generation += 1
        if kind == 'end':
            ended = True
        if kind in GAP_EVENTS or kind == 'corrupt_record':
            if kind not in ('session', 'end'):
                gaps.append(dict(kind=kind, evidence=evidence(number, event),
                                 **{key:event[key] for key in ('start_t','duration_ms') if key in event}))
            if event.get('object') in labels:
                close(labels[event['object']], kind)
            else:
                close_all(kind)
        if kind != 'action_state':
            continue
        label = actor_label(event)
        descriptor = event.get('descriptor') or {}
        observed = descriptor.get('word0_u16', descriptor.get('word0'))
        if observed is None and descriptor.get('word0_hex'):
            try:
                observed = int(descriptor['word0_hex'], 16)
            except ValueError:
                pass
        if not isinstance(observed, int) or not 0 <= observed <= 0xFFFF:
            observed = None
        identity = {'action_id': descriptor.get('action_key_u32'), 'observed_word0_u16': observed,
                    'motion_id': None, 'timing_id': None, 'timing_override': None}
        identity.update(trusted.get(number, {}))
        if not isinstance(identity['action_id'], int) or not 0 <= identity['action_id'] <= 0xFFFFFFFF:
            identity['action_id'] = None
        # Unsafely attributed or descriptor-free observations remain findable.
        if (identity['action_id'] is None and observed is None) or event.get('owner_matches_discovery') is False:
            unclassified.append({'actor_label': label, 'reason': 'No validated descriptor or actor identity',
                                 'evidence': evidence(number, event)})
            close(label, 'unclassified_state')
            continue
        action_id = identity['action_id']
        key = (f'action:{action_id:08X}' if action_id is not None else f'word0:{observed:04X}')
        key += f":motion:{identity['motion_id']}:timing:{identity['timing_id']}"
        qualified = label + '/' + key
        row = actions.setdefault(qualified, {'id': qualified, 'actor_label': label,
            'role': event.get('role', 'unassigned'), 'source': identity, 'observations': 0,
            'observed_entries': 0, 'unverified_reentries': 0, 'censored_observations': 0, 'evidence': []})
        row['observations'] += 1
        if len(row['evidence']) < 32:
            row['evidence'].append(evidence(number, event))
        previous = current.get(label)
        if previous and event.get('t', 0) < previous['end_t']:
            gaps.append(dict(kind='timestamp_regression', evidence=evidence(number, event)))
            close(label, 'timestamp_regression')
            previous = None
        serial = (event.get('current'), event.get('counter'))
        if previous is None:
            row['censored_observations'] += 1
        elif previous['actions'][-1] != qualified:
            row['observed_entries'] += 1
        elif previous['serial'] != serial:
            row['unverified_reentries'] += 1
        if previous and previous['actions'][-1] == qualified:
            previous['end_t'] = event.get('t', 0)
            previous['serial'] = serial
            continue
        if previous:
            pair = (previous['actions'][-1], qualified)
            edge = successors.setdefault(pair, {'actor_label': label, 'from': pair[0], 'to': pair[1],
                'count': 0, 'evidence': [], 'relationship': 'sampled_temporal_order'})
            edge['count'] += 1
            if len(edge['evidence']) < 32:
                edge['evidence'].append(evidence(number, event))
            if len(previous['actions']) == 64:
                close(label, 'bounded_sequence_chunk')
                previous = None
        if previous is None:
            current[label] = {'actor_label': label, 'actions': [], 'start_t': event.get('t', 0), 'end_t': event.get('t', 0)}
        current[label]['actions'].append(qualified)
        current[label]['end_t'] = event.get('t', 0)
        current[label]['serial'] = serial
    close_all('end_of_file')
    for edge in successors.values():
        target = actions[edge['to']]['source']['action_id']
        edge['native_links'] = [link for link in actions[edge['from']]['source'].get('transition_links', [])
                                if target is not None and link['target_action_id'] == target]
        edge['confidence'] = ('native_supported_order' if edge['native_links'] else
                              'repeated_temporal_order' if edge['count'] > 1 else 'temporal_order_only')
    result = {'schema_version': 1, 'kind': 'encounter_reconstruction', 'boss_id': boss_id,
              'boss_name': BOSSES[boss_id]['name'] if boss_id in BOSSES else boss_id.replace('_',' ').title(),
              'source': {'path': str(source), 'sha256': digest.hexdigest()}, 'complete': started and ended and not issues,
              'issues': issues, 'actions': list(actions.values()), 'observed_successors': list(successors.values()),
              'strings': strings, 'gaps': gaps, 'unclassified_observations': unclassified,
              'limitations': ['Sampled wall time is not frame data. Brief states can be missed.',
                              'Temporal strings are not verified combos or cancel windows.',
                              'Counter or pointer changes alone are unverified re-entries, not move occurrences.',
                              'Native links retain conditions; sampled order does not prove those conditions were satisfied.',
                              'Unassigned actors belong to encounter context only; their boss identity is unproven.']}
    if destination is not None:
        atomic_json(destination, result)
    return result


def reconstruct_encounter(folder):
    # Reconstruct each saved take under the encounter manifest's boss identity.
    # Write a compact index while leaving raw takes untouched.
    # Keep retries separate so their boundaries cannot become combo links.
    folder = Path(folder)
    manifest = json.loads((folder / 'encounter.json').read_text(encoding='utf8'))
    segments = []
    for events in sorted(folder.glob('take-*/events.jsonl')):
        summary = reconstruct_capture(events, manifest['boss_id'], events.parent / 'reconstruction.json')
        segments.append({'path': (events.parent / 'reconstruction.json').relative_to(folder).as_posix(), 'complete': summary['complete'],
                         'actions': len(summary['actions']), 'issues': len(summary['issues'])})
    result = {'schema_version': 1, 'kind': 'encounter_index', 'boss_id': manifest['boss_id'],
              'recording_id': manifest['recording_id'], 'segments': segments,
              'note': 'Takes remain separate; no combo relationship crosses retries or observation gaps.'}
    atomic_json(folder / 'reconstruction.json', result)
    return result


def select_actors(game, discovery, signature, stop_requested=lambda: (
    # Provide the no-cancellation default for direct discovery callers.
    # Return false until a caller supplies its own stop predicate.
    # Use the same polling path for interactive and offline invocations.
    False)):
    # Resolve source and player fingerprints through their action banks.
    # Require unique matches and recheck ownership after dependent reads.
    # Avoid assigning a boss from proximity or a session name alone.
    # Reuse native bank lookup; unique fingerprints only, never nearest actor.
    from action_banks import inspect_banks, resolve
    matches, players = [], []
    for candidate in discovery['candidates']:
        if stop_requested():
            raise InterruptedError('Actor selection cancelled')
        try:
            actor = int(candidate['object'], 0)
            banks = inspect_banks(game, actor)
            if banks['owner_like'] != candidate['owner_like']:
                continue
            def matches_signature(wanted):
                # Check every configured action-and-motion pair in one actor's banks.
                # Revalidate descriptor enablement, payload identity and final owner.
                # Reject mixed-lifetime or partially matching fingerprints.
                if not wanted:
                    return False
                for check in wanted:
                    entry = resolve(banks, check['action_id'])
                    if not entry:
                        return False
                    raw = game.bytes(int(entry['descriptor'], 0), 0x44)
                    if struct.unpack_from('<I', raw)[0] != check['action_id'] or not raw[0x40]:
                        return False
                    payload = struct.unpack_from('<Q', raw, 0x20)[0]
                    if hex(payload) != entry['payload']:
                        return False
                    if struct.unpack('<i', game.bytes(payload + 0x20, 4))[0] != check['motion_id']:
                        return False
                _, after = game.snapshot(actor)
                return after['owner_like'] == candidate['owner_like']
            if matches_signature(signature):
                matches.append(actor)
            if matches_signature(PLAYER_SIGNATURE):
                players.append(actor)
        except (OSError, ValueError, struct.error):
            continue
    if signature and len(matches) != 1:
        raise ValueError(f'Waiting for one source boss fingerprint; found {len(matches)}')
    if len(players) > 1:
        raise ValueError('Player fingerprint is ambiguous')
    boss = matches[0] if matches else None
    player = players[0] if players else None
    if boss is not None and boss == player:
        raise ValueError('Boss fingerprint also matches the player; refine source signature')
    return player, boss


def runtime_candidates(game, trace_path, stop_requested=lambda: (
    # Provide the no-cancellation default for direct discovery callers.
    # Return false until a caller supplies its own stop predicate.
    # Use the same polling path for interactive and offline invocations.
    False)):
    # Reuse recent native actor observations as discovery candidates.
    # Check process provenance and current owners before accepting trace pointers.
    # Reduce repeated heap scans without trusting expired actor addresses.
    # The running engine already observes actor setters. Revalidate those recent
    # identities instead of scanning the entire heap after every death/retry.
    if stop_requested(): raise InterruptedError('Actor discovery cancelled')
    with Path(trace_path).open('rb') as stream:
        first = stream.readline()
        if not first.endswith(b'\n'): return None
        header = json.loads(first)
        if any(header.get(key) != value for key,value in game.identity.items()):
            return None
        stream.seek(0,2)
        start = max(0,stream.tell()-2*1024*1024)
        stream.seek(start)
        if start: stream.readline()
        lines = stream.read().split(b'\n')[:-1]
    observed = {}
    # Keep only the latest owner per actor in this bounded tail. Reused actor
    # addresses cannot inherit the older owner's candidacy on revalidation.
    for line in lines:
        event = json.loads(line)
        if event['kind'] == 'action_call' and event['valid_fields'] & 1:
            observed[int(event['actor'],0)] = event['owner']
    candidates = []
    for actor,owner in observed.items():
        if stop_requested(): raise InterruptedError('Actor discovery cancelled')
        try:
            _,state = game.snapshot(actor)
        except (OSError, ValueError):
            continue
        if state['owner_like'] == owner:
            candidates.append(dict(object=hex(actor),role='unassigned',**state))
    if not candidates: return None
    return dict(**game.identity,candidates=candidates,discovery='revalidated_native_observations',
                recorded_at=time.time(),scope='Actor identity still requires source fingerprint')


def discover_encounter(game, stop_requested=lambda: (
    # Provide the no-cancellation default for direct discovery callers.
    # Return false until a caller supplies its own stop predicate.
    # Use the same polling path for interactive and offline invocations.
    False), seed=None, signature=None):
    # Try the running engine's recent actor trace before a heap scan.
    # Use only evidence belonging to the current process.
    # Fall back to read-only discovery when no candidate can be revalidated.
    from boss_probe import discover
    found=None
    if seed and seed.is_file():
        try:
            found=discover(game,seed,stop_requested)
            select_actors(game,found,signature or [],stop_requested)
        except (OSError,ValueError):
            found=None
    if found is None: found=discover(game,stop_requested=stop_requested)
    if seed: atomic_json(seed,found)
    return found


def record_encounter(boss_id, outdir, stop_file=None, signature=None, stop_event=None,
                     retry_seconds=3.0, status_callback=None, backend=None, boss_name=None):
    # Keep one named recording session across stops, process exits and actor replacement.
    # Lock its folder and allocate fresh numbered takes; resume never overwrites earlier raw observations.
    # Retry discovery failures, expose programming errors, and allow an injected backend for offline tests.
    validate_boss_id(boss_id)
    if not 0.05 <= retry_seconds <= 60:
        raise ValueError('Retry interval must be 0.05..60 seconds')
    signature = DEFAULT_SIGNATURES.get(boss_id, []) if signature is None else signature
    if not isinstance(signature, list) or len(signature) > 16 or any(
            not isinstance(row, dict) or not isinstance(row.get('action_id'), int) or
            not 0 <= row['action_id'] <= 0xFFFFFFFF or not isinstance(row.get('motion_id'), int)
            for row in signature):
        raise ValueError('A signature is at most 16 action_id/motion_id pairs')
    outdir = Path(outdir)
    stop_file = Path(stop_file) if stop_file else outdir / 'STOP'
    stop_event = stop_event or threading.Event()
    outdir.mkdir(parents=True, exist_ok=True)
    # Exclusive OS lock, released on crash. An existing lock file is harmless.
    import msvcrt
    lock = (outdir / 'recorder.lock').open('a+b')
    if lock.tell() == 0:
        lock.write(b'0')
        lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock.close()
        raise ValueError('This encounter is already being recorded') from None
    try:
        manifest_path = outdir / 'encounter.json'
        manifest = {'schema_version': 1, 'boss_id': boss_id, 'signature': signature,
                    'boss_name': boss_name or (BOSSES[boss_id]['name'] if boss_id in BOSSES else boss_id.replace('_',' ').title()),
                    'recording_id': uuid.uuid4().hex, 'created_at': time.time(),
                    'mode': 'external_read_only', 'identity_basis': 'source action/motion fingerprint' if signature else 'unassigned encounter context'}
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding='utf8'))
            if manifest.get('boss_id') != boss_id or manifest.get('signature') != signature:
                raise ValueError('Existing encounter has a different boss/signature; choose a new folder')
        else:
            atomic_json(manifest_path, manifest)
        if backend is None:
            from functools import partial
            import boss_probe
            from nioh_memory import current_pid
            backend = {'open': boss_probe.LiveGame, 'pid': current_pid, 'discover': partial(discover_encounter,seed=outdir/'discovery.json',signature=signature),
                       'select': select_actors, 'record': boss_probe.record}
    except BaseException:
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        lock.close()
        raise
    def stopped():
        # Combine the in-process cancellation event with the recorder stop file.
        # Allow both UI workers and direct callers to request the same shutdown.
        # Leave the active take responsible for flushing retained evidence.
        return stop_event.is_set() or stop_file.exists()
    status = {'boss_id': boss_id, 'outdir': str(outdir), 'state': 'starting', 'running': True, 'takes': 0}
    def publish(state, **fields):
        # Update the encounter status document and optional observer callback.
        # Replace the file atomically after adding a fresh update timestamp.
        # Expose retries and errors without changing recorded action evidence.
        status.update(state=state, updated_at=time.time(), **fields)
        atomic_json(outdir / 'status.json', status)
        if status_callback:
            status_callback(dict(status))
    try:
        reconstruct_encounter(outdir)
        while not stopped():
            try:
                publish('waiting_for_encounter', detail='Finding current process and source actor')
                with backend['open'](backend['pid']()) as game:
                    cfg = backend['discover'](game, stop_requested=stopped)
                    player, boss = backend['select'](game, cfg, signature, stopped)
                    if stopped():
                        break
                    existing = [int(p.name[5:]) for p in outdir.glob('take-*') if p.is_dir() and p.name[5:].isdigit()]
                    take = outdir / f'take-{max(existing, default=0) + 1:04d}'
                    publish('recording', take=str(take),
                            detail='Sampling source boss actions; no screen capture' if boss is not None else
                                   'Sampling unassigned encounter actors; boss identity needs a configured signature',
                            actor_identified=boss is not None)
                    final = backend['record'](game, cfg, take, 30 if boss is None else 86400, 10, player, boss, 128,
                        stop_requested=stopped, session_context={'boss_id': boss_id, 'boss_name':manifest.get('boss_name',boss_id), 'recording_id': manifest['recording_id'],
                                                               'identity_basis': manifest['identity_basis']})
                    index = reconstruct_encounter(outdir)
                    publish('recovering', takes=len(index['segments']), detail=final.get('stop_reason'))
            except InterruptedError:
                break
            except (OSError, ValueError, struct.error) as error:
                reconstruct_encounter(outdir)
                publish('waiting_for_encounter', detail=str(error))
            if not stopped():
                stop_event.wait(retry_seconds)
    except KeyboardInterrupt:
        pass
    except BaseException as error:
        publish('error', running=False, detail=str(error))
        raise
    finally:
        try:
            index = reconstruct_encounter(outdir)
            if status['state'] != 'error':
                publish('stopped', running=False, takes=len(index['segments']), detail='Recording stopped; evidence retained')
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            lock.close()
    return status


def sampled_time(event):
    # Extract an observation's time in seconds when it is a usable sample.
    # Only supported numeric, finite, nonnegative timestamps can define annotation bounds.
    # Missing or malformed times remain absent rather than creating an invented recording interval.
    if isinstance(event, dict) and isinstance(event.get('kind'), str):
        value = event.get('t')
        if type(value) in (int, float) and 0 <= value < float('inf'):
            return value
    return None


def latest_sample_time(path):
    # Find the latest usable time in a saved take, including its ending record.
    # Scan only the final 64 KiB, dropping a partial first line and unfinished/invalid records.
    # This is the sampled recording boundary, not proof of the exact animation frame.
    with path.open('rb') as stream:
        stream.seek(0,2)
        start = max(0,stream.tell()-65536)
        stream.seek(start)
        if start: stream.readline()
        lines = stream.read().split(b'\n')
    times = []
    for line in lines:
        try:
            value = sampled_time(json.loads(line))
            if value is not None:
                times.append(value)
        except (ValueError, AttributeError):
            continue
    if not times:
        raise ValueError('No complete sampled timestamp is available yet')
    return max(times)


def parse_annotations(text):
    # Recover the latest saved description revision for each label.
    # Read the append-only history and preserve explicit interval, marker and revision information.
    # Malformed history is rejected instead of silently losing a contributor's correction.
    labels = {}
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        label = json.loads(line)
        if not isinstance(label, dict) or not isinstance(label.get('label'), str):
            raise ValueError(f'Invalid annotation on line {number}')
        label.setdefault('label_id', f'legacy-{number}')
        label.setdefault('revision', 1)
        label.setdefault('start_t', label.get('last_recorded_t'))
        label.setdefault('end_t', label.get('last_recorded_t'))
        label.setdefault('markers', [])
        if not isinstance(label['label_id'], str) or not label['label_id'] or type(label['revision']) is not int:
            raise ValueError(f'Invalid annotation revision on line {number}')
        previous = labels.get(label['label_id'])
        if label['revision'] != (previous['revision'] + 1 if previous else 1):
            raise ValueError(f'Invalid annotation revision on line {number}')
        labels[label['label_id']] = label
    return list(labels.values())


def load_annotations(folder):
    # Load the saved descriptions belonging to a session folder.
    # An absent labels file means no saved descriptions; existing content goes through revision parsing.
    # Draft text is stored separately and is not promoted into a completed annotation here.
    path = Path(folder)/'labels.jsonl'
    return parse_annotations(path.read_text(encoding='utf8')) if path.exists() else []


def validate_annotation(label, takes):
    # Check that a description names a real take and stays within its sampled duration.
    # Validate interval ordering, allowed markers and field types before any intake or revision write.
    # Reject path-shaped take names so an annotation cannot point outside the session.
    take = label.get('take')
    if not isinstance(take, str) or not re.fullmatch(r'take-[0-9]+', take) or take not in takes:
        raise ValueError('Choose an existing recorded take')
    start, end = label.get('start_t'), label.get('end_t')
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in (start, end)) or not 0 <= start <= end <= takes[take]:
        raise ValueError('Boundaries must satisfy 0 <= start <= end <= the take duration')
    markers = label.get('markers', [])
    if not isinstance(markers, (list, tuple)) or any(marker not in ('repeat', 'unsure', 'interrupted') for marker in markers):
        raise ValueError('Markers must be repeat, unsure or interrupted')


def save_annotation(folder, description, take, start_t, end_t, markers=(), label_id=None):
    # Save a new description or append a correction while retaining earlier revisions.
    # Validate against the take's sampled duration, then flush a new history file and atomically replace the old one.
    # Raw event files stay untouched, and an interrupted write cannot publish a half-written history.
    folder = Path(folder)
    manifest = json.loads((folder/'encounter.json').read_text(encoding='utf8'))
    if not isinstance(description, str) or not description.strip():
        raise ValueError('A description is required')
    labels = {label['label_id']: label for label in load_annotations(folder)}
    if label_id is not None and label_id not in labels:
        raise ValueError('Annotation to edit was not found')
    label = dict(kind='user_label', boss_id=manifest['boss_id'], take=take,
                 label_id=label_id or uuid.uuid4().hex, revision=labels[label_id]['revision'] + 1 if label_id else 1,
                 label=description.strip(), start_t=start_t, end_t=end_t, markers=list(markers),
                 last_recorded_t=end_t, noted_wall_time=time.time(),
                 basis='User-selected sampled interval; exact animation boundaries unverified')
    # Validate the name before using it as a path component.
    validate_annotation(label, {path.parent.name: float('inf') for path in folder.glob('take-*/events.jsonl')})
    validate_annotation(label, {take: latest_sample_time(folder/take/'events.jsonl')})
    path = folder/'labels.jsonl'
    history = path.read_text(encoding='utf8') if path.exists() else ''
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('x', encoding='utf8') as stream:
            stream.write(history + ('\n' if history and not history.endswith('\n') else '') + json.dumps(label, ensure_ascii=True)+'\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return label


def annotate_recent(folder, description):
    # Attach a description at the latest sampled instant of the newest take.
    # Reject sessions without recorded samples instead of creating an ungrounded label.
    # The zero-length interval is a contributor note, not an inferred start/end boundary for a move.
    takes = sorted(Path(folder).glob('take-*/events.jsonl'))
    if not takes:
        raise ValueError('A recorded take and a description are required')
    sampled = latest_sample_time(takes[-1])
    return save_annotation(folder, description, takes[-1].parent.name, sampled, sampled)


def main(argv=None):
    # Select either offline reconstruction or an explicit encounter recording.
    # Read optional source fingerprints from configuration.
    # Keep replaying saved evidence independent of game attachment.
    parser = argparse.ArgumentParser(description='Record boss encounters and reconstruct sampled action strings.')
    parser.add_argument('--boss-id', required=True)
    parser.add_argument('--outdir', type=Path, required=True)
    parser.add_argument('--stop-file', type=Path)
    parser.add_argument('--signature', type=Path, help='JSON array of stable action_id/motion_id pairs')
    parser.add_argument('--reconstruct', type=Path, help='Offline events.jsonl to reconstruct instead of recording')
    args = parser.parse_args(argv)
    if args.reconstruct:
        args.outdir.mkdir(parents=True, exist_ok=True)
        result = reconstruct_capture(args.reconstruct, args.boss_id, args.outdir / 'reconstruction.json')
        print(json.dumps({'actions': len(result['actions']), 'complete': result['complete']}))
    else:
        signature = json.loads(args.signature.read_text(encoding='utf8')) if args.signature else None
        record_encounter(args.boss_id, args.outdir, args.stop_file, signature)


if __name__ == '__main__':
    main()
