"""System Agent — Mac control, browser automation, file ops, terminal.

The system cluster from the FRIDAY system map. Controls the machine itself.
Scoped tools: mac control + browser + terminal + file ops.

To keep tool count manageable for 9B models, each run selects the relevant
tool subset based on the task type.
"""

from friday.core.base_agent import BaseAgent
from friday.tools.terminal_tools import TOOL_SCHEMAS as TERMINAL_TOOLS
from friday.tools.mac_tools import TOOL_SCHEMAS as MAC_TOOLS
from friday.tools.file_tools import TOOL_SCHEMAS as FILE_TOOLS

# Browser tools are optional — only loaded if playwright is installed
try:
    from friday.tools.browser_tools import TOOL_SCHEMAS as BROWSER_TOOLS
    _HAS_BROWSER = True
except Exception:
    BROWSER_TOOLS = {}
    _HAS_BROWSER = False

# PDF tools
from friday.tools.pdf_tools import TOOL_SCHEMAS as PDF_TOOLS


SYSTEM_PROMPT = """You control Travis's Mac. You handle system operations, file management, browser automation, and terminal commands.

ALWAYS respond in English.

RULES:
1. You MUST call tools to do anything. NEVER make up results.
2. For dangerous operations (delete, format, force kill), always report what you're about to do and ask for confirmation.
3. NEVER run commands that could destroy data without explicit confirmation.
4. Your first response must ALWAYS be a tool call, not text.

CAPABILITIES:
- Terminal: run commands, start background processes, manage running processes
- Files: read/write files, list directories, search for files
- Mac control: open apps, run AppleScript, take screenshots, system info, volume, dark mode
- Browser: navigate pages, screenshot, click elements, fill forms, read page text
- PDF: read/extract text+tables, merge, split, rotate, encrypt/decrypt, watermark, metadata

PATTERNS:
- "open Cursor" → open_application(app="Cursor")
- "what's running" → run_command(command="ps aux | head -20")
- "take a screenshot" → take_screenshot()
- "go to github.com" → browser_navigate(url="https://github.com")
- "dark mode" → toggle_dark_mode()
- "system info" → get_system_info()
- "find all python files" → search_files(directory=".", query="*.py", search_type="name")
- "read this PDF" → pdf_read(file_path="...")
- "merge these PDFs" → pdf_merge(file_paths=[...], output_path="...")
- "split this PDF" → pdf_split(file_path="...", output_dir="...")
- "extract tables from PDF" → pdf_read(file_path="...", extract_tables=true)
- "encrypt this PDF" → pdf_encrypt(file_path="...", password="...")
- "rotate page 1" → pdf_rotate(file_path="...", degrees=90, pages="1")

LOGIN FLOW (critical — follow exactly):
When browser_navigate returns data with "login_required": true:
1. Tell Travis: "This needs a login. I've opened the browser — log in there and I'll wait."
2. Call browser_wait_for_login() — this watches until login completes.
3. After login succeeds, continue with the original task (navigate to the page, screenshot, etc.)
4. The session is saved permanently — next time, no login needed.
NEVER screenshot a login page and call it done. Always handle the login flow.

DISPLAY / SHARE FILES:
When asked to show/display/open a file (screenshot, image, document):
- "show it on mac" / "open it" / "display it" → run_command(command="open <filepath>") — opens in Preview
- "send to phone" / "airdrop it" → run_applescript with AirDrop sharing (see below)
- "iphone mirroring" → open_application(app="iPhone Mirroring")
- If context mentions a file path from a previous screenshot, USE IT directly.

AirDrop AppleScript:
tell application "Finder"
    activate
    set theFile to POSIX file "<filepath>" as alias
    set theWindow to make new Finder window
    set target of theWindow to theFile
end tell
tell application "System Events"
    keystroke "r" using {command down, shift down}
end tell

After tool results come back, summarise what happened clearly."""


class SystemAgent(BaseAgent):
    name = "system_agent"
    system_prompt = SYSTEM_PROMPT
    max_iterations = 5

    def __init__(self):
        # Core tools — always available (8 tools)
        self.tools = {
            # Terminal (keep the 2 most used)
            "run_command": TERMINAL_TOOLS["run_command"],
            "run_background": TERMINAL_TOOLS["run_background"],
            # Mac control (keep the most useful)
            "open_application": MAC_TOOLS["open_application"],
            "take_screenshot": MAC_TOOLS["take_screenshot"],
            "get_system_info": MAC_TOOLS["get_system_info"],
            "run_applescript": MAC_TOOLS["run_applescript"],
            # Files (keep read + list)
            "read_file": FILE_TOOLS["read_file"],
            "list_directory": FILE_TOOLS["list_directory"],
        }
        super().__init__()

    async def run(self, task: str, context: str = "", on_tool_call=None, on_chunk=None):
        # Dynamically add browser tools if the task mentions browser/web/navigate
        task_lower = task.lower()
        browser_keywords = ["browser", "navigate", "webpage", "website", "click", "fill form",
                            "open page", "go to", "browse", "screenshot page",
                            "linkedin", "twitter", "github.com", "login", "log in"]

        if _HAS_BROWSER and any(kw in task_lower for kw in browser_keywords):
            # Inject browser tools for this run
            self.tools["browser_navigate"] = BROWSER_TOOLS["browser_navigate"]
            self.tools["browser_screenshot"] = BROWSER_TOOLS["browser_screenshot"]
            self.tools["browser_click"] = BROWSER_TOOLS["browser_click"]
            self.tools["browser_get_text"] = BROWSER_TOOLS["browser_get_text"]
            self.tools["browser_wait_for_login"] = BROWSER_TOOLS["browser_wait_for_login"]
            self._build_tool_definitions()

        # Inject PDF tools if the task mentions PDFs
        pdf_keywords = ["pdf", ".pdf", "merge pdf", "split pdf", "rotate pdf",
                        "extract text", "extract table", "encrypt pdf", "decrypt pdf",
                        "watermark", "pdf metadata"]
        if any(kw in task_lower for kw in pdf_keywords):
            self.tools.update(PDF_TOOLS)
            self._build_tool_definitions()

        result = await super().run(task=task, context=context, on_tool_call=on_tool_call, on_chunk=on_chunk)

        # Reset tools to defaults after run
        self.__init__()

        return result
