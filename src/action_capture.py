"""Action-first journal worker. Read-only memory; no UI, controller, injection or boss gate."""
import argparse
from collections import deque
import json
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
                          tail=list(journal.tail), **fields)), flush=True)


def sample(game, journal, stop, discover_factory=None, initial=None, notify=publish):
    # Observe every valid action node, without requiring a player or boss fingerprint.
    # Discover on a separate read-only handle while existing candidates continue sampling.
    # Candidate loss is a per-actor gap; optional metadata cannot discard the primary action ID.
    from boss_probe import descriptor_fields, metadata
    candidates, last, known = {}, {}, set()
    results = queue.Queue(maxsize=1)
    scanner = None
    next_scan = last_report = time.monotonic()
    last_tick = last_valid = time.monotonic()
    problem = 'Looking for action nodes; no action IDs saved yet.'

    def scan():
        # Use a separate process handle so heap scanning cannot stall the sampler's reads.
        # Discovery remains bound to this exact process lifetime and supported executable.
        # A bounded mailbox holds one result; stopping cancels discovery without extra files.
        from boss_probe import discover
        try:
            with discover_factory() as reader:
                if reader.identity != game.identity:
                    raise OSError('Game process changed during discovery')
                results.put(discover(reader, stop_requested=stop.is_set))
        except (OSError, ValueError, InterruptedError) as error:
            results.put(error)

    if initial is not None:
        results.put(initial)
    while not stop.is_set() and game.alive():
        tick = time.monotonic()
        if tick - last_tick > .05:
            journal.emit('sampling_gap', duration_ms=round((tick - last_tick) * 1000, 2))
        last_tick = tick
        if not results.empty():
            result = results.get_nowait()
            if isinstance(result, Exception):
                problem = str(result)
                journal.emit('diagnostic', code='discovery', detail=problem)
            else:
                for row in result['candidates']:
                    address = int(row['object'], 0)
                    if candidates.get(address) != row['owner_like']:
                        last.pop(address, None)
                    candidates[address] = row['owner_like']
                journal.emit('discovery', objects=len(candidates), **game.identity)
            next_scan = tick + (15 if candidates else 2)
        if discover_factory and tick >= next_scan and (scanner is None or not scanner.is_alive()):
            scanner = threading.Thread(target=scan, daemon=True)
            scanner.start()
            next_scan = float('inf')
        if hasattr(game, 'begin_sample'):
            game.begin_sample()
        valid = 0
        for address, owner in tuple(candidates.items()):
            try:
                _, state = game.snapshot(address)
                if state['owner_like'] != owner:
                    raise OSError('Action-node owner changed')
                current = int(state['current'], 0)
                valid += 1
                if not current or last.get(address) == state:
                    continue
                raw = game.bytes(current, 0xD0)
                descriptor = descriptor_fields(raw)
                _, after = game.snapshot(address)
                if after != state:
                    journal.emit('snapshot_race', object=hex(address))
                    continue
                journal.emit('action_state', object=hex(address), role='unassigned',
                             owner_matches_discovery=True, descriptor=descriptor, **state)
                last[address] = state
                key = (address, owner, current, raw)
                if key not in known:
                    try:
                        detail = metadata(game, current, 128)
                        _, after = game.snapshot(address)
                        detail['matches_preceding_state'] = after == state and detail['descriptor_bytes'] == raw.hex()
                        journal.emit('metadata', object=hex(address), role='unassigned', **detail)
                        if detail['matches_preceding_state']:
                            if len(known) >= 8192:
                                known.clear()
                            known.add(key)
                    except (OSError, ValueError, struct.error) as error:
                        journal.emit('metadata_unreadable', object=hex(address), detail=str(error))
            except (OSError, ValueError, struct.error) as error:
                candidates.pop(address, None)
                last.pop(address, None)
                journal.emit('object_unreadable', object=hex(address), detail=str(error))
                next_scan = min(next_scan, tick + 1)
        if valid:
            last_valid = tick
        if tick - last_report >= 1:
            healthy = bool(valid and journal.actions)
            notify(journal, 'recording' if healthy else 'waiting',
                   f'{valid} action nodes readable. Boss name is your encounter label.' if healthy else problem,
                   actors=valid, sample_age=round(tick - last_valid, 2))
            last_report = tick
        stop.wait(max(0, .01 - (time.monotonic() - tick)))
    journal.emit('gap', reason='stop_requested' if stop.is_set() else 'process_exit')


def main():
    # The UI supplies an existing session journal and one unique take ID.
    # EOF or an explicit stop command shuts down cooperatively and fsyncs the final rows.
    # Capture retries game absence; write failures terminate with a visible nonzero exit.
    parser = argparse.ArgumentParser()
    parser.add_argument('--journal', type=Path, required=True)
    parser.add_argument('--take', required=True)
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
        journal.emit('session', wall_time=time.time(), mode='external_read_only',
                     identity_basis='all actors; boss name is encounter context', interval_ms=10)
        publish(journal, 'waiting', 'Waiting for Nioh and readable action IDs; nothing captured yet.')
        from boss_probe import LiveGame
        from nioh_memory import current_pid
        while not stop.is_set():
            try:
                with LiveGame(current_pid()) as game:
                    sample(game, journal, stop, discover_factory=lambda: LiveGame(game.pid))
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
        journal.emit('end', actions=journal.actions)
        publish(journal, 'stopped', f'{journal.actions:,} action observations saved.' if journal.actions else
                'No action IDs were captured. Your description is saved; this take needs recording again.')
        return 0
    finally:
        journal.close()


if __name__ == '__main__':
    raise SystemExit(main())
