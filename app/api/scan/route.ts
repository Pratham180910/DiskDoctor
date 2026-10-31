import { NextRequest, NextResponse } from 'next/server'
import fs from 'node:fs/promises'
import path from 'node:path'

type FileRecord = { name: string; path: string; size: number; type: string; modified: string }

function extension(file: string) {
  const ext = path.extname(file).replace('.', '').toLowerCase()
  return ext || 'none'
}

function formatDate(value: Date) {
  return value.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
}

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({})) as { target?: string; mode?: 'quick' | 'full' }
  const target = body.target || process.env.SystemDrive || 'C:\\'
  const mode = body.mode === 'full' ? 'full' : 'quick'
  const files: FileRecord[] = []
  const categories = new Map<string, { bytes: number; count: number }>()
  let folders = 0
  let bytes = 0
  let errors = 0
  const started = Date.now()
  const stack = [path.resolve(target)]

  while (stack.length) {
    const current = stack.pop()!
    let entries
    try { entries = await fs.readdir(current, { withFileTypes: true }) } catch { errors++; continue }
    folders++
    for (const entry of entries) {
      if (entry.isSymbolicLink()) continue
      const full = path.join(current, entry.name)
      if (entry.isDirectory()) { stack.push(full); continue }
      if (!entry.isFile()) continue
      try {
        const stat = await fs.stat(full)
        const record = { name: entry.name, path: full, size: stat.size, type: extension(entry.name), modified: formatDate(stat.mtime) }
        files.push(record)
        bytes += stat.size
        const key = record.type.toUpperCase()
        const item = categories.get(key) || { bytes: 0, count: 0 }
        item.bytes += stat.size; item.count++; categories.set(key, item)
      } catch { errors++ }
      if (mode === 'quick' && files.length >= 100000) break
    }
    if (mode === 'quick' && files.length >= 100000) break
  }

  files.sort((a, b) => b.size - a.size)
  const topTypes = [...categories.entries()].sort((a, b) => b[1].bytes - a[1].bytes).slice(0, 8)
  return NextResponse.json({
    target, mode, files: files.length, folders, bytes, errors, durationMs: Date.now() - started,
    largestFiles: files.slice(0, 12),
    topTypes: topTypes.map(([name, value]) => ({ name, ...value })),
  })
}
