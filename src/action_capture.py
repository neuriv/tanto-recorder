"""Action-first journal worker. Read-only memory; no UI, controller, injection or boss gate."""
import argparse
from collections import deque
import json
import hashlib
import marshal
import msvcrt
import os
from pathlib import Path
import queue
import struct
import sys
import threading
import time


class JournalError(OSError):
    """A disk failure is fatal to capture, unlike a temporary failed game-memory read."""


class Journal:
    def __init__(self, path, take):
        # Keep every Start in the same append-only session journal, distinguished by take ID.
        # Lock its first byte so a second application cannot become another writer.
        # Preserve a crash-truncated final row, separating it from subsequent valid JSONL.
        self.file = Path(path).open('a+b')
        self.file.seek(0)
        try:
            msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.file.close()
            raise OSError('This session is already being recorded by another application') from None
        self.file.seek(0, 2)
        if self.file.tell():
            self.file.seek(-1, 2)
            if self.file.read(1) != b'\n':
                self.file.write(b'\n')
        self.take, self.started = take, time.monotonic()
        self.actions = self.bytes = 0
        self.tail = deque(maxlen=12)
        self.last_t = 0.0
        self.quality = dict(counter_gaps=0, recovered_previous=0, snapshot_races=0,
                            actor_changes=0, longest_sample_ms=0, dropped_events=0, metadata_failures=0, discovery_complete=False)

    def emit(self, kind, **fields):
        # Save the full action ID before optional metadata can fail or become stale.
        # Each row owns its take ID and elapsed clock, so retries never silently join sequences.
        # Only the last twelve observations enter UI memory; the full stream stays on disk.
        self.last_t = round(time.monotonic() - self.started, 6)
        row = dict(t=self.last_t, take=self.take, kind=kind, **fields)
        data = (json.dumps(row, separators=(',', ':'), allow_nan=False) + '\n').encode('utf8')
        try:
            self.file.write(data)
        except OSError as error:
            raise JournalError(f'Cannot save action IDs: {error}') from error
        self.bytes += len(data)
        if kind == 'action_state' and fields.get('descriptor'):
            self.actions += 1
            self.tail.append(dict(t=self.last_t, actor=fields['object'],
                                 id=fields['descriptor']['action_key_hex']))

    def sync(self):
        # A reported saved count means these bytes passed through flush and OS fsync.
        # One-second checkpoints bound ordinary crash loss without syncing every sample.
        # Disk-full and permission failures propagate; they must never become a success message.
        try:
            self.file.flush()
            os.fsync(self.file.fileno())
        except OSError as error:
            raise JournalError(f'Cannot sync action IDs to disk: {error}') from error

    def close(self):
        # Finish disk writes before releasing the session's exclusive writer lock.
        # Closing happens even after sync fails, allowing later recovery of earlier checkpoints.
        # Never truncate or rewrite the collected action evidence.
        try:
            self.sync()
        finally:
            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            self.file.close()


def publish(journal, state, detail, **fields):
    # Send compact health messages to Electron, rather than copying the action stream over IPC.
    # Flush first so the UI's saved count reflects durable evidence, not attempted reads.
    # JSON lines avoid shell parsing and remain independent of the renderer's lifetime.
    journal.sync()
    print(json.dumps(dict(state=state, detail=detail, actions=journal.actions,
                          bytes=journal.bytes, last_t=journal.last_t,
                          tail=list(journal.tail), quality=dict(journal.quality), **fields)), flush=True)


def coherent(state):
    # Only owner, current descriptor and counter define the primary observation.
    # Transient pending/transition fields must not discard a stable full action ID.
    # Descriptor bytes are checked separately before writing the observation.
    return tuple(state.get(key) for key in ('owner_like', 'current', 'counter'))


class MetadataReader:
    """Optional bounded work on a separate read-only process handle; never writes the journal."""
    def __init__(self, factory, identity):
        # Bound queued requests and results independently of the journal size.
        # The optional reader owns its process handle and never writes capture rows.
        # Only the sampler drains results into the durable journal.
        self.tasks, self.results = queue.Queue(64), queue.Queue(64)
        self.closed = threading.Event()
        self.dropped = 0
        self.thread = threading.Thread(target=self.run, args=(factory, identity), daemon=True)
        self.thread.start()

    def run(self, factory, identity):
        # Reject a reader opened against another process lifetime.
        # Check actor ownership and descriptor bytes around optional reads.
        # Return failures as data so the sampler can permit a later execution to retry.
        from boss_probe import metadata, actor_metadata
        try:
            with factory() as reader:
                if reader.identity != identity:
                    raise OSError('Game process changed during metadata capture')
                while not self.closed.is_set():
                    try:
                        task = self.tasks.get(timeout=.05)
                    except queue.Empty:
                        continue
                    try:
                        if hasattr(reader, 'begin_sample'):
                            reader.begin_sample()
                        _, before = reader.snapshot(task['actor'])
                        if before['owner_like'] != task['owner'] or before['counter'] < task['counter']:
                            raise ValueError('Actor lifetime changed before metadata capture')
                        if hex(task['descriptor']) not in (before.get('current'), before.get('previous')):
                            raise ValueError('Descriptor no longer belongs to current/previous state')
                        detail = metadata(reader, task['descriptor'], 128)
                        raw = bytes.fromhex(detail['descriptor_bytes'])
                        if raw[:0x28] != task['prefix'] or detail.get('payload_stable') is False:
                            raise ValueError('Descriptor identity changed before metadata capture')
                        detail['actor_context'] = actor_metadata(reader, task['actor'], task['owner'], detail)
                        _, after = reader.snapshot(task['actor'])
                        if after['owner_like'] != task['owner'] or after['counter'] < before['counter'] or reader.bytes(task['descriptor'], len(raw)) != raw:
                            raise ValueError('Actor or descriptor changed during metadata capture')
                        self.results.put_nowait((task, detail, None))
                    except queue.Full:
                        self.dropped += 1
                    except (OSError, ValueError, struct.error) as error:
                        try:
                            self.results.put_nowait((task, None, str(error)))
                        except queue.Full:
                            self.dropped += 1
        except Exception as error:
            try:
                self.results.put_nowait((None, None, str(error)))
            except queue.Full:
                self.dropped += 1

    def close(self):
        # Stop accepting optional work without delaying primary capture shutdown.
        # The daemon can finish its bounded read but cannot write the journal.
        # Count queued or unfinished requests as dropped optional evidence.
        self.closed.set()
        self.thread.join(.1)
        self.dropped += self.tasks.qsize() + int(self.thread.is_alive())


def sample(game, journal, stop, discover_factory=None, initial=None, notify=publish, cache_path=None, metadata_factory=None):
    # Observe every valid action node, without requiring a player or boss fingerprint.
    # Discover on a separate read-only handle while existing candidates continue sampling.
    # Candidate loss is a per-actor gap; optional metadata cannot discard the primary action ID.
    candidates, last, known, generations = {}, {}, set(), {}
    quality = journal.quality
    quality['discovery_complete'] = False
    optional = MetadataReader(metadata_factory or discover_factory, game.identity) if metadata_factory or discover_factory else None
    metadata_drops = 0

    def generation(address, reason):
        # Separate reused actor addresses from their previous lifetime.
        # Invalidate cached metadata and ordering before accepting new observations.
        # The cause remains unknown; owner changes and resets are not death detection.
        generations[address] = generations.get(address, 0) + 1
        quality['actor_changes'] += 1
        last.pop(address, None)
        known.difference_update(key for key in tuple(known) if key[0] == address)
        journal.emit('actor_generation', object=hex(address), generation=generations[address], reason=reason, cause='unknown')

    def drain_metadata(limit=2):
        # Limit optional journal work per sample so current IDs stay first.
        # Failed requests become retryable only when a later execution is observed.
        # Count missing metadata separately from persisted action observations.
        nonlocal metadata_drops
        if optional is None:
            return
        quality['dropped_events'] += optional.dropped - metadata_drops
        metadata_drops = optional.dropped
        for _ in range(limit):
            try:
                task, detail, error = optional.results.get_nowait()
            except queue.Empty:
                break
            if task is None:
                quality['metadata_failures'] += 1
                journal.emit('diagnostic', code='metadata_reader', detail=error)
                continue
            address = task['actor']
            matches = generations.get(address) == task['generation'] and candidates.get(address) == task['owner']
            if error or not matches:
                known.discard((task['actor'], task['generation'], task['descriptor'], task['prefix']))
                quality['metadata_failures'] += 1
                journal.emit('metadata_unreadable', object=hex(address), generation=task['generation'], detail=error or 'Actor lifetime retired')
            else:
                journal.emit('metadata', object=hex(address), role='unassigned', generation=task['generation'],
                             observation_t=task['observation_t'], observation_counter=task['counter'],
                             observation_signature=task['prefix'].hex(), matches_preceding_state=True,
                             consistency='Separate read handle; lifetime and descriptor rechecked; not atomic', **detail)
    results = queue.Queue(maxsize=1)
    scanner = None
    next_scan = last_report = time.monotonic()
    last_tick = last_valid = last_activity = time.monotonic()
    silence_reported = False
    problem = 'Looking for action nodes; no action IDs saved yet.'
    cached_actors = None

    def offer(result):
        # Keep only the newest cumulative discovery snapshot instead of blocking a scanner on Stop.
        # Actor candidates are cumulative within each scan, so replacing progress loses no candidate.
        # The main sampling thread remains the sole journal writer.
        try:
            results.put_nowait(result)
        except queue.Full:
            try:
                results.get_nowait()
            except queue.Empty:
                pass
            results.put_nowait(result)

    def scan():
        # Use a separate process handle so heap scanning cannot stall the sampler's reads.
        # Discovery remains bound to this exact process lifetime and supported executable.
        # A bounded mailbox holds one result; stopping cancels discovery without extra files.
        from boss_probe import discover
        try:
            with discover_factory() as reader:
                if reader.identity != game.identity:
                    raise OSError('Game process changed during discovery')
                anchors = {}
                refreshed = time.monotonic()

                def progress(result):
                    # Death/retry can rebuild actors while the full scan is still far from their pool.
                    # Recheck known 64-KiB neighborhoods once a second on this separate read handle.
                    # Merge fresh owners before delivery; the sampler still verifies every live snapshot.
                    nonlocal anchors, refreshed
                    anchors.update((row['object'], row) for row in result['candidates'])
                    if anchors and time.monotonic() - refreshed >= 1:
                        try:
                            nearby = discover(reader, dict(**reader.identity, candidates=list(anchors.values())),
                                              stop_requested=stop.is_set)
                            anchors = {row['object']: row for row in nearby['candidates']}
                        except ValueError:
                            pass  # A temporarily empty pool must not cancel the wider search during loading.
                        refreshed = time.monotonic()
                    offer(dict(result, candidates=list(anchors.values())))

                if cache_path and Path(cache_path).is_file():
                    try:
                        seed = discover(reader, Path(cache_path), stop_requested=stop.is_set)
                        progress(dict(seed, scan_complete=False, cached=True))
                    except (OSError, ValueError):
                        pass  # A different process or retired actor needs a new scan, never trusted old pointers.
                if not stop.is_set():
                    progress(dict(discover(reader, stop_requested=stop.is_set, on_progress=progress), scan_complete=True))
        except Exception as error:
            offer(error)

    if initial is not None:
        results.put(initial)
    try:
        while not stop.is_set() and game.alive():
            tick = time.monotonic()
            quality['longest_sample_ms'] = max(quality['longest_sample_ms'], round((tick - last_tick) * 1000, 2))
            if tick - last_tick > .05:
                journal.emit('sampling_gap', duration_ms=round((tick - last_tick) * 1000, 2))
            last_tick = tick
            # The scanner may replace a queued snapshot between this thread's reads.
            # Take it atomically; an empty mailbox simply means sampling can continue.
            # Never let an ordinary progress-update race terminate a recording.
            try:
                result = results.get_nowait()
            except queue.Empty:
                result = None
            if result is not None:
                if isinstance(result, Exception):
                    problem = f'{type(result).__name__}: {result}'
                    journal.emit('diagnostic', code='discovery', detail=problem)
                    next_scan = tick + 2
                else:
                    for row in result['candidates']:
                        address = int(row['object'], 0)
                        if candidates.get(address) != row['owner_like']:
                            generation(address, 'discovered' if address not in generations else 'reacquired_or_owner_changed')
                        candidates[address] = row['owner_like']
                    complete = result.get('scan_complete', True)
                    quality['discovery_complete'] = complete
                    journal.emit('discovery' if complete or result.get('cached') else 'discovery_progress',
                                 objects=len(candidates), bytes_scanned=result.get('bytes_scanned', 0),
                                 scan_complete=complete, cached=result.get('cached', False), **game.identity)
                    problem = f"Searching for action nodes: {result.get('bytes_scanned', 0) // 1048576:,} MiB checked."
                    if complete:
                        next_scan = tick + (15 if candidates else 2)
                    actors = tuple(sorted(candidates.items()))
                    if cache_path and actors and actors != cached_actors:
                        # Cache is a startup hint bound to process birth/build, never a permanent actor identity.
                        # Store only addresses/owners; the next take validates their current snapshots and nearby pool.
                        # A cache write failure cannot discard action evidence or block the active sampler.
                        cache = Path(cache_path)
                        temporary = cache.with_suffix('.tmp')
                        try:
                            cache.parent.mkdir(parents=True, exist_ok=True)
                            temporary.write_text(json.dumps(dict(**game.identity, candidates=[
                                dict(object=hex(address), owner_like=owner) for address, owner in actors])), encoding='utf8')
                            os.replace(temporary, cache)
                            cached_actors = actors
                        except OSError as error:
                            journal.emit('diagnostic', code='discovery_cache', detail=str(error))
                            cache_path = None
            if discover_factory and tick >= next_scan and (scanner is None or not scanner.is_alive()):
                scanner = threading.Thread(target=scan, daemon=True)
                scanner.start()
                next_scan = float('inf')
            if hasattr(game, 'begin_sample'):
                game.begin_sample()
            valid = 0
            pending = []
            for address, owner in tuple(candidates.items()):
                readable_actor = False
                try:
                    _, state = game.snapshot(address)
                    if state['owner_like'] != owner:
                        raise OSError('Action-node owner changed')
                    current = int(state['current'], 0)
                    valid += 1
                    readable_actor = True
                    previous = last.get(address)
                    if not current or previous and coherent(previous) == coherent(state):
                        continue
                    raw = game.bytes(current, 0x28)[:0x28]
                    key = struct.unpack_from('<I', raw)[0]
                    descriptor = dict(action_key_u32=key, action_key_hex=f'0x{key:08X}',
                                      word0_u16=key & 0xFFFF, payload=hex(struct.unpack_from('<Q', raw, 0x20)[0]))
                    _, after = game.snapshot(address)
                    if coherent(after) != coherent(state) or game.bytes(current, 0x28)[:0x28] != raw:
                        quality['snapshot_races'] += 1
                        journal.emit('snapshot_race', object=hex(address), generation=generations[address])
                        continue
                    if previous and state['counter'] < previous['counter']:
                        journal.emit('actor_reset', object=hex(address), previous_counter=previous['counter'], counter=state['counter'], cause='unverified')
                        generation(address, 'counter_reset')
                        previous = None
                    gap = max(0, state['counter'] - previous['counter'] - 1) if previous else 0
                    if gap:
                        quality['counter_gaps'] += gap
                        journal.emit('counter_gap', object=hex(address), generation=generations[address],
                                     previous_counter=previous['counter'], counter=state['counter'], unobserved_increments=gap)
                    journal.emit('action_state', object=hex(address), role='unassigned', generation=generations[address],
                                 provenance='observed_current', owner_matches_discovery=True, descriptor=descriptor, descriptor_prefix=raw.hex(), **state)
                    observation_t = journal.last_t
                    last_activity, silence_reported = tick, False
                    last[address] = state
                    pending.append(dict(actor=address, owner=owner, generation=generations[address], descriptor=current,
                                        counter=state['counter'], prefix=raw, observation_t=observation_t))
                    # A previous pointer supports only an inferred predecessor, not its execution time.
                    prior = int(state.get('previous', '0x0'), 0)
                    if prior and prior != current:
                        try:
                            prior_raw = game.bytes(prior, 0x28)[:0x28]
                            _, final = game.snapshot(address)
                            if coherent(final) != coherent(state) or final.get('previous') != state.get('previous'):
                                raise ValueError('Previous action changed while reading')
                            prior_key = struct.unpack_from('<I', prior_raw)[0]
                            journal.emit('previous_action', object=hex(address), generation=generations[address], address=hex(prior),
                                         provenance='inferred_previous_pointer', observed_at=observation_t,
                                         descriptor=dict(action_key_u32=prior_key, action_key_hex=f'0x{prior_key:08X}'))
                            if gap and prior != int(previous.get('current', '0x0'), 0):
                                quality['recovered_previous'] += 1
                        except (OSError, ValueError, struct.error) as error:
                            journal.emit('previous_unreadable', object=hex(address), detail=str(error))
                except JournalError:
                    raise
                except (OSError, ValueError, struct.error) as error:
                    valid -= int(readable_actor)
                    generation(address, 'unreadable')
                    candidates.pop(address, None)
                    journal.emit('object_unreadable', object=hex(address), generation=generations[address], detail=str(error))
                    next_scan = min(next_scan, tick + 1)
            # All primary actor reads precede optional work submission and result processing.
            if optional:
                for task in pending:
                    key = (task['actor'], task['generation'], task['descriptor'], task['prefix'])
                    if key in known:
                        continue
                    if len(known) >= 8192:
                        quality['dropped_events'] += 1
                        continue
                    try:
                        optional.tasks.put_nowait(task)
                        known.add(key)
                    except queue.Full:
                        quality['dropped_events'] += 1
            drain_metadata()
            quality['longest_sample_ms'] = max(quality['longest_sample_ms'], round((time.monotonic() - tick) * 1000, 2))
            if valid:
                last_valid = tick
            if tick - last_activity >= 2 and not silence_reported:
                journal.emit('activity_silence', duration_s=round(tick - last_activity, 3), cause='unknown', readable_actors=valid)
                silence_reported = True
            if tick - last_report >= 1:
                healthy = bool(valid and journal.actions)
                notify(journal, 'recording' if healthy else 'waiting',
                       f'{valid} action nodes readable. Boss name is your encounter label.' if healthy else problem,
                       actors=valid, sample_age=round(tick - last_valid, 2))
                last_report = tick
            stop.wait(max(0, .01 - (time.monotonic() - tick)))
    finally:
        if optional:
            optional.close()
            drain_metadata(64)
    journal.emit('gap', reason='stop_requested' if stop.is_set() else 'process_exit')


def source_stamp():
    # Record the protocol and Python runtime beside capture evidence.
    # Hash source when available and function bytecode in frozen workers too.
    # Fingerprints identify the reader implementation without claiming gameplay coverage.
    import boss_probe
    files = (Path(__file__), Path(boss_probe.__file__))
    return dict(protocol=2, python=sys.version.split()[0],
                runtime_sha256={function.__qualname__: hashlib.sha256(marshal.dumps(function.__code__)).hexdigest()
                                for function in (sample, coherent, MetadataReader.run, Journal.emit, Journal.sync,
                                                 boss_probe.metadata, boss_probe.actor_metadata, boss_probe.resource_match)},
                sources={file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in files if file.is_file()},
                supported_build=boss_probe.BUILD_SHA256)


def main():
    # The UI supplies an existing session journal and one unique take ID.
    # EOF or an explicit stop command shuts down cooperatively and fsyncs the final rows.
    # Capture retries game absence; write failures terminate with a visible nonzero exit.
    parser = argparse.ArgumentParser()
    parser.add_argument('--journal', type=Path, required=True)
    parser.add_argument('--take', required=True)
    parser.add_argument('--discovery-cache', type=Path)
    args = parser.parse_args()
    stop = threading.Event()

    def commands():
        # Treat UI shutdown like Stop so a disappeared parent cannot leave an orphan capture.
        # Only one text command exists; no arbitrary worker operations are exposed.
        # The sampling thread checks this event between bounded reads.
        for line in sys.stdin:
            if line.strip() == 'stop':
                break
        stop.set()

    threading.Thread(target=commands, daemon=True).start()
    journal = Journal(args.journal, args.take)
    try:
        journal.emit('session', wall_time=time.time(), mode='external_read_only', source=source_stamp(),
                     identity_basis='all actors; boss name is encounter context', interval_ms=10,
                     observability='External polling: death, pause and exact execution times are not inferred from silence or counter resets.',
                     death_detection='unavailable: no verified HP/death marker', pause_detection='unavailable: no verified pause marker')
        publish(journal, 'waiting', 'Waiting for Nioh and readable action IDs; nothing captured yet.')
        from boss_probe import LiveGame
        from nioh_memory import current_pid
        while not stop.is_set():
            try:
                with LiveGame(current_pid()) as game:
                    sample(game, journal, stop, discover_factory=lambda: LiveGame(game.pid), cache_path=args.discovery_cache)
            except JournalError:
                raise
            except (OSError, ValueError) as error:
                # Retry read/discovery failures, but stop on unknown memory layouts.
                # Journal errors are not swallowed: publish's fsync fails again and escapes.
                # Persist the diagnostic that the old status file used to overwrite.
                detail = str(error)
                journal.emit('diagnostic', code='attachment', detail=detail)
                fatal = any(word in detail for word in ('Unrecognized', 'does not match', 'RTTI'))
                publish(journal, 'error' if fatal else 'waiting', detail)
                if fatal:
                    return 2
            stop.wait(2)
        journal.emit('end', actions=journal.actions, quality=dict(journal.quality))
        publish(journal, 'stopped', f'{journal.actions:,} action observations saved.' if journal.actions else
                'No action IDs were captured. Your description is saved; this take needs recording again.')
        return 0
    finally:
        journal.close()


if __name__ == '__main__':
    raise SystemExit(main())
