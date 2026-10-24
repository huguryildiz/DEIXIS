import { useState } from 'react'
import { ApiError, type WatchCommandResult } from '../api'
import { newCommand, useWriteCommand, type WriteCommand } from '../review/commands'

export function useFollowUpCommand(identity: string, request: (command: WriteCommand) => Promise<WatchCommandResult>, reload: () => Promise<void>, success?: () => void) {
  const [error, setError] = useState('')
  const write = useWriteCommand(identity, request, async () => { setError(''); await reload(); success?.() }, async (cause: ApiError) => {
    setError(cause.message)
    await reload()
  })
  return { ...write, error, locked: write.busy || Boolean(write.pending), start: (body: unknown) => { setError(''); void write.send(newCommand(body)) } }
}
