import { useState } from 'react'
import { ApiError, type WatchCommandResult } from '../api'
import { newCommand, useWriteCommand, type WriteCommand } from '../review/commands'
import { t } from '../i18n'

export function useFollowUpCommand(identity: string, request: (command: WriteCommand) => Promise<WatchCommandResult>, reload: () => Promise<void>, success?: () => void) {
  const [error, setError] = useState('')
  const write = useWriteCommand(identity, request, async () => { setError(''); await reload(); success?.() }, async (cause: ApiError) => {
    setError(cause.code ? cause.message : cause.message === 'legacy_research_read_only' ? t('This research used an earlier search method. Start a new research to search again.') : cause.message)
    await reload()
  })
  return { ...write, error, locked: write.busy || Boolean(write.pending), start: (body: unknown) => { setError(''); void write.send(newCommand(body)) } }
}
