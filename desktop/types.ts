// Boss names describe the encounter; no field here certifies an actor's identity.
// Take IDs join description boundaries to rows in the append-only action journal.
// The renderer receives data and a fixed command vocabulary, never filesystem/process APIs.
export interface Note { id: string; text: string; take: string; end_t: number; updated_at: number }
export interface Take { id: string; started_at: number; ended_at?: number; actions: number; last_t: number; state: string }
export interface Session {
  schema_version: number; recording_id: string; boss_id: string; boss_name: string; created_at: number;
  draft: { text: string; editing_id?: string }; annotations: Note[]; takes: Take[];
}
export interface Health {
  state: string; detail: string; actions: number; bytes: number; last_t: number;
  quality?: { counter_gaps: number; recovered_previous: number; snapshot_races: number; actor_changes: number; longest_sample_ms: number; dropped_events: number; metadata_failures?: number; discovery_complete: boolean };
  actors?: number; sample_age?: number; tail: { t: number; actor: string; id: string }[];
}
export interface Settings {
  recordings_directory: string; cue_volume: number; hotkey: string;
  last_session?: string; tutorial_version: number; changelog_seen?: string; motion: boolean;
  boss_draft?: string;
}
export interface View {
  version: string; settings: Settings; folder: string | null; session: Session | null;
  health: Health; running: boolean; exporting: boolean; bosses: string[]; changelog: string;
}
export interface RecorderAPI {
  call(command: string, value?: unknown): Promise<View>;
  onState(listener: (view: View) => void): void;
  onCue(listener: (name: 'start' | 'stop') => void): void;
}
declare global { interface Window { recorder: RecorderAPI; flushRecorderDraft: () => Promise<void> } }
