import type { Health } from './types';

export function workerHealth(message: Health, stopping: boolean): Health {
  // A synced checkpoint does not mean the worker has finished closing the take.
  // Keep Stop visible until process exit; preserve an explicit storage failure.
  // This pure transition is shared by the live UI and focused workflow checks.
  return stopping && message.state !== 'error'
    ? { ...message, state: 'stopping', detail: 'Finishing the journal and syncing your action IDs…' }
    : message;
}

export function finishedHealth(health: Health, code: number | null, terminal: Health | null, error: string): Health {
  // Only a clean exit plus the final synced message confirms a saved take.
  // Retain earlier counts after interruption and distinguish empty recordings.
  // Quality warnings describe observation gaps, even when disk persistence succeeded.
  if (code !== 0 || terminal?.state !== 'stopped') return { ...health, state: 'error',
    detail: `Capture incomplete. ${health.actions ? 'Earlier synced IDs remain. ' : ''}${error || terminal?.detail || 'The worker did not confirm the final journal save.'}` };
  if (!terminal.actions) return { ...terminal, state: 'error', detail: 'No action IDs captured. Your descriptions are retained; start another take.' };
  const q = terminal.quality;
  return q && (q.counter_gaps || q.snapshot_races || q.dropped_events || q.metadata_failures || !q.discovery_complete)
    ? { ...terminal, detail: 'Partial evidence saved. Review the coverage counts; your descriptions are retained.' } : terminal;
}

export function coverage(health: Health): string {
  // Show measured sampling limits alongside the number of saved observations.
  // Recovered previous pointers are candidates, not directly witnessed executions.
  // Never translate these counters into a claim that every move was captured.
  const q = health.quality;
  if (!q) return '';
  return `${q.counter_gaps} missed increments · ${q.recovered_previous} recovered · ${q.snapshot_races} snapshot races · ${q.actor_changes} actor changes · ${q.dropped_events} optional records dropped · ${q.metadata_failures ?? 0} metadata failures · longest sample ${q.longest_sample_ms.toFixed(1)} ms · discovery ${q.discovery_complete ? 'complete' : 'incomplete'}`;
}
