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

# CV tools — needed when form filling requires CV upload
try:
    from friday.tools.cv_tools import TOOL_SCHEMAS as CV_TOOLS
    _HAS_CV = True
except Exception:
    CV_TOOLS = {}
    _HAS_CV = False

# PDF tools
from friday.tools.pdf_tools import TOOL_SCHEMAS as PDF_TOOLS

# Screen tools (OCR + vision)
from friday.tools.screen_tools import TOOL_SCHEMAS as SCREEN_TOOLS


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
- Screen vision: OCR (read all text on screen), ask about screen (vision model identifies apps, code, errors, UI)
- Full page capture: scroll through entire page, OCR each viewport, concatenate all text
- Solve screen questions: capture full page, identify all questions/problems, solve them, save answers to .docx

PATTERNS:
- "open Cursor" → open_application(app="Cursor")
- "what's running" → run_command(command="ps aux | head -20")
- "take a screenshot" → take_screenshot()
- "go to github.com" → browser_navigate(url="https://github.com")
- "dark mode" → toggle_dark_mode()
- "system info" → get_system_info()
- "find all python files" → search_files(directory=".", query="*.py", search_type="name")
- "read this PDF" → pdf_read(file_path="...")
- "what's on my screen" → ask_about_screen(query="describe what's on screen")
- "read the text on screen" → ocr_screen()
- "solve the questions on my screen" → solve_screen_questions()
- "read the full page" → capture_full_page()

FORM FILLING (when Travis says "fill the form", "fill in the form for me", etc.):

STEP 1 — DISCOVER:
browser_discover_form() — returns ALL fields with EXACT selectors, types, labels, values, required status.

STEP 2 — FILL TEXT FIELDS:
browser_fill_form with EXACT selectors from step 1. Example:
  browser_fill_form(fields={"#first_name": "Angelo", "input[name='email']": "angeloasante958@gmail.com"})
Travis's details:
  First Name: Angelo | Last Name: Asante | Email: angeloasante958@gmail.com
  Phone: +447555834656 | LinkedIn: https://linkedin.com/in/angeloasante
  GitHub: https://github.com/angeloasante | Website: https://diasporaai.com
  Location: Plymouth, United Kingdom | Pronouns: He/Him
  Work authorization: Yes (UK) | Visa sponsorship: No
  How did you hear: Company website | Start date: Immediately

STEP 3 — FILL CHECKBOXES, DROPDOWNS, RADIO BUTTONS, YES/NO:
These are often missed. Go through EVERY field from discover_form:
  - Checkboxes: browser_fill_form(fields={"#agree": "true"}) — value "true" checks it
  - Dropdowns/selects: browser_fill_form(fields={"#country": "United Kingdom"}) — use option text
  - Radio buttons: browser_fill_form(fields={"input[name='auth'][value='yes']": "true"})
  - Yes/No buttons: browser_click on the appropriate button selector
Do NOT skip any field. If a field has options listed, pick the best match from Travis's details.

STEP 4 — UPLOAD:
browser_upload for any file input (if CV needed, generate_pdf first).

STEP 5 — FINAL VERIFICATION (MANDATORY — never skip this):
browser_discover_form() again. Look at EVERY field:
  - Any unfilled checkboxes? Fill them.
  - Any unfilled dropdowns still on default/placeholder? Fill them.
  - Any unfilled required fields? Fill them.
  - unfilled_required_count must be 0.
  - Check non-required fields too — fill what you can.

BAIL-OUT RULE: If after 2 verify+fill cycles the SAME fields are still unfilled, STOP. Some fields are custom components that can't be filled via JS. Report what you filled and what you couldn't — don't loop forever.

NEVER ask Travis for his details — you already know them. Just fill and verify.
NEVER guess selectors — only use what browser_discover_form returns.
NEVER stop after text fields — checkboxes and dropdowns are just as important.

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
        # Check both task AND context (context has recent conversation for follow-ups like "yes")
        search_text = (task + " " + context).lower()
        task_lower = task.lower()
        browser_keywords = ["browser", "navigate", "webpage", "website", "click",
                            "open page", "go to", "browse", "screenshot page",
                            "linkedin", "twitter", "github.com", "login", "log in"]

        # Form-filling keywords — triggers batch browser tools + higher iteration limit
        form_keywords = ["fill form", "fill the form", "fill in the form", "fill in form",
                         "fill this form", "fill that form", "fill it in", "fill the fields",
                         "fill out", "complete the form", "complete this form",
                         "submit the form", "submit this form",
                         "browser_fill_form", "browser_discover_form"]
        is_form_task = any(kw in search_text for kw in form_keywords)

        if _HAS_BROWSER and (any(kw in task_lower for kw in browser_keywords) or is_form_task):
            # Inject browser tools — include batch form tools for form tasks
            self.tools.update({
                "browser_navigate": BROWSER_TOOLS["browser_navigate"],
                "browser_screenshot": BROWSER_TOOLS["browser_screenshot"],
                "browser_click": BROWSER_TOOLS["browser_click"],
                "browser_fill": BROWSER_TOOLS["browser_fill"],
                "browser_type": BROWSER_TOOLS["browser_type"],
                "browser_check": BROWSER_TOOLS["browser_check"],
                "browser_select": BROWSER_TOOLS["browser_select"],
                "browser_scroll": BROWSER_TOOLS["browser_scroll"],
                "browser_elements": BROWSER_TOOLS["browser_elements"],
                "browser_upload": BROWSER_TOOLS["browser_upload"],
                "browser_get_text": BROWSER_TOOLS["browser_get_text"],
                "browser_execute_js": BROWSER_TOOLS["browser_execute_js"],
                "browser_back": BROWSER_TOOLS["browser_back"],
                "browser_wait_for_login": BROWSER_TOOLS["browser_wait_for_login"],
                "browser_close": BROWSER_TOOLS["browser_close"],
            })
            # Batch form tools — discover all fields + fill all at once
            if "browser_discover_form" in BROWSER_TOOLS:
                self.tools["browser_discover_form"] = BROWSER_TOOLS["browser_discover_form"]
            if "browser_fill_form" in BROWSER_TOOLS:
                self.tools["browser_fill_form"] = BROWSER_TOOLS["browser_fill_form"]
            self._build_tool_definitions()

        # For form tasks: inject CV tools (for upload) and increase iterations
        if is_form_task:
            if _HAS_CV:
                self.tools.update({
                    "generate_pdf": CV_TOOLS["generate_pdf"],
                    "tailor_cv": CV_TOOLS["tailor_cv"],
                })
                self._build_tool_definitions()
            # Forms need discover → fill → verify loops, 5 iterations isn't enough
            self.max_iterations = 10

        # Inject PDF tools if the task mentions PDFs
        pdf_keywords = ["pdf", ".pdf", "merge pdf", "split pdf", "rotate pdf",
                        "extract text", "extract table", "encrypt pdf", "decrypt pdf",
                        "watermark", "pdf metadata"]
        if any(kw in task_lower for kw in pdf_keywords):
            self.tools.update(PDF_TOOLS)
            self._build_tool_definitions()

        # Inject screen tools if the task mentions screen/vision/OCR
        screen_keywords = ["screen", "see what", "look at", "what am i",
                           "what do you see", "ocr", "read the text",
                           "what error", "what code", "what app",
                           "what language", "what's on", "what is on",
                           "can you see", "look right", "look here",
                           "explain this", "explain what",
                           "solve", "answer the", "full page",
                           "question", "quiz", "exam", "worksheet"]
        if any(kw in task_lower for kw in screen_keywords):
            self.tools.update(SCREEN_TOOLS)
            self._build_tool_definitions()

        result = await super().run(task=task, context=context, on_tool_call=on_tool_call, on_chunk=on_chunk)

        # Reset tools and max_iterations to defaults after run
        self.max_iterations = 5
        self.__init__()

        return result
