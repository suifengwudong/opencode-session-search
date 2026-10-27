import { execFile } from "node:child_process"
import { existsSync, readFileSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"
import { promisify } from "node:util"

const run = promisify(execFile)
const here = dirname(fileURLToPath(import.meta.url))
const repo = "https://github.com/suifengwudong/opencode-session-search"

function resolveBin() {
  let bin = "ses"
  const configPath = join(here, "config.json")
  if (existsSync(configPath)) {
    const config = JSON.parse(readFileSync(configPath, "utf8"))
    if (config.bin) bin = config.bin
  }
  return process.env.SES_BIN || bin
}

function normalizeLimit(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return 10
  return Math.min(50, Math.max(1, Math.trunc(number)))
}

function buildArgs(input) {
  const args = []
  const query = (input.query || "").trim()
  if (query) args.push(...query.split(/\s+/))
  args.push("--json", "-n", String(normalizeLimit(input.limit)))
  if (input.directory) args.push("-d", input.directory)
  if (input.since) args.push("--since", input.since)
  if (input.until) args.push("--until", input.until)
  if (input.assistant) args.push("-a")
  if (input.include_children) args.push("--all")
  if (input.include_current) args.push("--include-current")
  return args
}

function format(items) {
  if (!Array.isArray(items) || items.length === 0) return "No sessions found."
  const blocks = items.map((item, index) => {
    const meta = [item.directory, item.id, item.last_match].filter(Boolean).join(" · ")
    const details = []
    if (item.matches > 1) details.push(`${item.matches} matches`)
    if (item.title_match && item.matches === 0) details.push("title match")
    const suffix = details.length ? ` · ${details.join(" · ")}` : ""
    const snippet = item.snippet ? `\n   ${item.snippet}` : ""
    return `${index + 1}. ${item.title || "(untitled)"}\n   ${meta}${suffix}${snippet}`
  })
  return `${blocks.join("\n\n")}\n\nResume with: opencode -s <id>`
}

export const sessionSearchTool = {
  name: "session_search",
  description:
    "Search the user's OpenCode session history across every project. Use this when the user refers to a past conversation, asks what was discussed before, or cannot find an old session. It matches session titles and user prompts; set assistant=true to also search assistant replies (slower). Returns session ids, directories, timestamps, snippets, and the command to resume. An empty query lists the most recent sessions.",
  input: {
    type: "object",
    properties: {
      query: {
        type: "string",
        description: "Keywords separated by spaces. All must match. Empty lists recent sessions.",
      },
      directory: {
        type: "string",
        description: "Only sessions whose directory contains this text.",
      },
      since: {
        type: "string",
        description: "Start time: 30d, 12h, 2w, 2026-09-01, or an ISO timestamp.",
      },
      until: {
        type: "string",
        description: "End time, same formats as since.",
      },
      assistant: {
        type: "boolean",
        default: false,
        description: "Also search assistant replies. Slower.",
      },
      limit: {
        type: "number",
        default: 10,
        description: "Maximum results, 1-50.",
      },
      include_children: {
        type: "boolean",
        default: false,
        description: "Show subagent sessions individually.",
      },
      include_current: {
        type: "boolean",
        default: false,
        description: "Include the session running this tool.",
      },
    },
    required: [],
    additionalProperties: false,
  },
  async execute(input, context) {
    const env = { ...process.env, PYTHONIOENCODING: "utf-8" }
    if (context?.sessionID) env.OPENCODE_SESSION_ID = context.sessionID

    try {
      const { stdout } = await run(resolveBin(), buildArgs(input), {
        encoding: "utf8",
        env,
        signal: context?.signal,
        maxBuffer: 10 * 1024 * 1024,
        windowsHide: true,
      })
      return { content: format(JSON.parse(stdout)) }
    } catch (error) {
      if (error.code === 1 && error.stdout) {
        return { content: format(JSON.parse(error.stdout)) }
      }
      if (error.code === "ENOENT") {
        return { content: `ses CLI not found. Install it with: uv tool install git+${repo}` }
      }
      return { content: `ses failed: ${String(error.stderr || error.message).trim()}` }
    }
  },
}

export default {
  id: "opencode-session-search",
  async setup(ctx) {
    await ctx.tool.transform((editor) => {
      editor.add(sessionSearchTool)
    })
  },
}
