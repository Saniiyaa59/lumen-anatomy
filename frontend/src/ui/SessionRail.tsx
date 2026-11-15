import { historyStore, useHistory } from "../session/history.ts";
import { playerStore, usePlayer } from "../session/player.ts";

const DAY = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
const TIME = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });

/** "2:40 PM" for today, "Nov 14" for earlier days. */
function when(startedAt: number): string {
  const date = new Date(startedAt);
  return date.toDateString() === new Date().toDateString() ? TIME.format(date) : DAY.format(date);
}

interface SessionRailProps {
  collapsed: boolean;
  onToggle: () => void;
}

/**
 * The strip on the left: start a new session, and reopen past ones.
 *
 * The history is kept in this browser only (see session/history.ts).
 */
export default function SessionRail({ collapsed, onToggle }: SessionRailProps) {
  const entries = useHistory();
  const { runId } = usePlayer();
  // A new session begins at the start screen, where the student says what they need.
  const newSession = () => playerStore.close();

  return (
    <nav className="rail" data-collapsed={collapsed} aria-label="Sessions">
      <div className="rail-top">
        <button
          type="button"
          className="rail-icon"
          aria-label={collapsed ? "Open the sessions list" : "Close the sessions list"}
          aria-expanded={!collapsed}
          title={collapsed ? "Open the sessions list" : "Close the sessions list"}
          onClick={onToggle}
        >
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <rect x="3.5" y="4.5" width="17" height="15" rx="2.5" />
            <path d="M9.5 4.5v15" />
          </svg>
        </button>
        {!collapsed && <span className="rail-brand">Lumen</span>}
      </div>

      <button type="button" className="rail-new" title="New session" aria-label="New session" onClick={newSession}>
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
          <path d="M12 5v14M5 12h14" />
        </svg>
        {!collapsed && <span>New session</span>}
      </button>

      {!collapsed && (
        <>
          <h2>History</h2>
          {entries.length === 0 ? (
            <p className="rail-empty">Sessions you start will be listed here.</p>
          ) : (
            <ul className="rail-list">
              {entries.map((entry) => (
                <li key={entry.runId} data-current={entry.runId === runId}>
                  <button type="button" className="rail-entry" aria-current={entry.runId === runId ? "page" : undefined} onClick={() => historyStore.open(entry.runId)}>
                    <span className="rail-entry-title">{entry.request}</span>
                    <span className="rail-entry-when">{when(entry.startedAt)}</span>
                  </button>
                  <button type="button" className="rail-remove" aria-label={`Remove ${entry.request} from the history`} title="Remove" onClick={() => historyStore.remove(entry.runId)}>
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="rail-note">Kept in this browser only.</p>
        </>
      )}
    </nav>
  );
}
