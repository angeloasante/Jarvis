"""Job Agent — autonomous job applications.

Agent 9. Doesn't just generate CVs — actually applies to jobs.
Can browse job sites, read JDs, tailor CV, generate PDF, fill forms, submit.
Can scan emails for job openings and act on them.
"""

from friday.core.base_agent import BaseAgent
from friday.core.user_config import USER
from friday.tools.cv_tools import TOOL_SCHEMAS as CV_TOOLS
from friday.tools.web_tools import TOOL_SCHEMAS as WEB_TOOLS
from friday.tools.browser_tools import TOOL_SCHEMAS as BROWSER_TOOLS
from friday.tools.email_tools import TOOL_SCHEMAS as EMAIL_TOOLS


_BASE_PROMPT = """Job agent.
{applicant_block}

PHASE 1 — FIND THE JOB:
If you already have a direct job URL, skip to Phase 2.
1. search_web for "[company] software engineer apply" to find a direct job posting
2. browser_navigate to the result — could be company site, Greenhouse, Lever, BuiltIn, LinkedIn, etc.
3. browser_get_text to read the page
4. If it's a JOB LISTING page (multiple jobs):
   - browser_elements to find clickable job links
   - browser_click on a relevant software engineering role
   - If no clickable links found, search_web again more specifically: "[company] software engineer greenhouse apply"
5. If it's a JOB DESCRIPTION page: great, proceed to Phase 2
6. browser_get_text to read the full job description

IMPORTANT for job listing pages:
- Don't scroll endlessly looking for links. If browser_elements finds no job links after 2 tries, search_web for a more direct URL.
- LinkedIn: after typing in search, click the search icon/button next to the input, not the general Jobs tab.
- If official site is a React SPA with no standard links, try: search_web "[company] jobs greenhouse" or "[company] jobs lever"

PHASE 2 — TAILOR CV:
1. browser_get_text to read the job description (if you haven't already)
2. tailor_cv(job_title="...", company="...", job_description="first 500 chars of JD")
3. generate_pdf() — it automatically uses the tailored context from step 2. No args needed.

PHASE 3 — FILL APPLICATION:
1. browser_discover_form() — scrolls full page, returns ALL fields + buttons + unfilled count
2. If there's an Apply button, use browser_fill_form with click_first to click it
3. browser_discover_form() again — now returns the application form fields
4. Call browser_fill_form ONCE with ALL fields using exact selectors from discover_form
5. browser_upload the tailored CV PDF
6. VERIFY: call browser_discover_form() — check unfilled_required_count
   - If unfilled_required_count > 0, call browser_fill_form with those fields
   - Repeat until all_required_filled is true
7. Only when all_required_filled is true, report done

If a site needs login, call browser_wait_for_login().
If a site redirects to Greenhouse/Lever/Workday, follow the redirect and fill that form.

DEFAULT ANSWERS:
- Use location/GitHub/website/LinkedIn from the applicant block above.
- Work authorization: Yes (unless specified otherwise in the applicant block)
- Visa sponsorship: No (unless specified otherwise)
- How did you hear: Company website
- Relocate: Yes
- Salary: Prefer not to say
- Start date: Immediately
- Gender/Race/Veteran: Decline to self-identify
- If a required answer is NOT covered by the applicant block, ASK the user — don't invent.

RULES:
- browser_fill_form for ALL fields in ONE call. Never fill individually.
- browser_discover_form to find form fields. browser_get_text to read page content.
- NEVER guess selectors. Only use selectors from browser_discover_form.
- NEVER report done if unfilled_required_count > 0. Keep filling.
- ALWAYS tailor the CV to the job description. Never use a generic CV.
- Chain calls fast. Don't explain between steps.
- Only ask the user before final submit."""


def _applicant_block() -> str:
    """Render applicant identity from USER config."""
    if not USER.is_configured:
        return ("Applicant details are NOT configured. Before tailoring a CV or "
                "filling forms, ASK the user for their name, email, phone, "
                "location, GitHub, LinkedIn, and right-to-work status.")
    parts = []
    if USER.name:
        parts.append(f"Name: {USER.name}")
    if USER.email:
        parts.append(f"Email: {USER.email}")
    if USER.phone:
        parts.append(f"Phone: {USER.phone}")
    if USER.location:
        parts.append(f"Location: {USER.location}")
    if USER.github:
        parts.append(f"GitHub: https://github.com/{USER.github}")
    if USER.website:
        parts.append(f"Portfolio: {USER.website}")
    if USER.bio:
        parts.append(f"Bio: {USER.bio}")
    return "Applicant: " + " | ".join(parts) if parts else "Applicant details incomplete — ask the user for more."


def get_system_prompt() -> str:
    return _BASE_PROMPT.replace("{applicant_block}", _applicant_block())


SYSTEM_PROMPT = get_system_prompt()


class JobAgent(BaseAgent):
    name = "job_agent"
    system_prompt = SYSTEM_PROMPT
    max_iterations = 30

    def __init__(self):
        self.system_prompt = get_system_prompt()
        self.tools = {
            # CV tools
            **CV_TOOLS,
            # Web research
            "search_web": WEB_TOOLS["search_web"],
            # Browser — batch-first tools
            "browser_navigate": BROWSER_TOOLS["browser_navigate"],
            "browser_discover_form": BROWSER_TOOLS["browser_discover_form"],
            "browser_fill_form": BROWSER_TOOLS["browser_fill_form"],
            "browser_screenshot": BROWSER_TOOLS["browser_screenshot"],
            "browser_click": BROWSER_TOOLS["browser_click"],
            "browser_type": BROWSER_TOOLS["browser_type"],
            "browser_scroll": BROWSER_TOOLS["browser_scroll"],
            "browser_upload": BROWSER_TOOLS["browser_upload"],
            "browser_get_text": BROWSER_TOOLS["browser_get_text"],
            "browser_execute_js": BROWSER_TOOLS["browser_execute_js"],
            "browser_elements": BROWSER_TOOLS["browser_elements"],
            "browser_wait_for_login": BROWSER_TOOLS["browser_wait_for_login"],
        }
        super().__init__()

    async def run(self, task: str, context: str = "", on_tool_call=None, on_chunk=None):
        return await super().run(task=task, context=context, on_tool_call=on_tool_call, on_chunk=on_chunk)
