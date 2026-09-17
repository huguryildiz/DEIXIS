import { ConnectionIcon } from './connectionIcons'
import { connectionName } from './labels'

// A model as the interface names it: its connection's icon, then its display name, kept on one line.
export function ModelName({ connection, text }: { connection: string; text: string }) {
  return <span className="model-name"><ConnectionIcon id={connection} /><span><span className="sr-only">{connectionName(connection)} · </span>{text}</span></span>
}
