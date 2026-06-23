"""CV & Job tools — get CV, tailor it, write cover letters, generate PDFs.

Uses structured CV data from friday.data.cv and WeasyPrint for PDF generation.
Dark sidebar design with lime accent — distinctive, not generic.
"""

import asyncio
import json
import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from jinja2 import Template

from friday.core.types import ToolResult
from friday.core.config import DATA_DIR
from friday.data.cv import CV


# Output directory for generated files
CV_OUTPUT_DIR = DATA_DIR / "cv_output"
CV_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Cache for CV tailoring — set by tailor_cv(), used by generate_pdf()
_tailoring_context = {}


async def get_cv(section: str = "all") -> ToolResult:
    """Return CV data — full or a specific section.

    Args:
        section: "all", "experience", "education", "skills", "projects", "summary", "contact"
    """
    if section == "all":
        return ToolResult(success=True, data=CV)

    if section in CV:
        return ToolResult(success=True, data={section: CV[section]})

    return ToolResult(
        success=False,
        data=f"Unknown section: {section}. Valid: {', '.join(CV.keys())}",
    )


async def tailor_cv(
    job_title: str,
    company: str,
    job_description: str,
    new_summary: str,
    lead_with: list[str],
    bullet_additions: dict[str, list[str]] | None = None,
    skills_priority: list[str] | None = None,
    emphasis: list[str] | None = None,
) -> ToolResult:
    """Build a tailored CV deterministically from small LLM deltas.

    The LLM only needs to emit ~5 small fields — a summary string, a list
    of company names to lead with, optional bullet additions, optional
    skill category order. The TOOL does the structural work (reorder,
    merge, etc.) and stages the result so generate_pdf() picks it up
    automatically (no args needed).

    This is way more reliable than asking the model to emit a full 5 KB
    CV dict as a tool argument — it avoids the "let me write Python in
    chat output" failure mode.

    Args:
        job_title: The role being applied for.
        company: Company name.
        job_description: Full or summarised JD (truncated internally).
        new_summary: The full new profile summary, written in the user's
            voice. ~3-6 sentences. NOT a template — concrete proof of fit.
        lead_with: Company names from base_cv.experience that should
            appear FIRST, in priority order. Anything not listed keeps
            its original order at the bottom. Use exact company strings
            from the base CV.
        bullet_additions: Optional. Map of company name → list of extra
            bullets to APPEND (not replace) to that entry's highlights.
            Use sparingly, only for the 1-2 lead entries.
        skills_priority: Optional. Skill category names (e.g. "ai_ml",
            "backend") in priority order. Unlisted categories follow.
        emphasis: Optional. Skills/themes to highlight (informational).
    """
    cv_data = deepcopy(CV)

    # 1. Replace summary
    cv_data["summary"] = new_summary

    # 2. Reorder experience: lead_with first (in given order), rest after
    base_exp = list(cv_data.get("experience") or [])
    lead_lower = [c.strip().lower() for c in lead_with]
    leads_with_idx: list[tuple[int, dict]] = []
    rest: list[dict] = []
    seen_lead_keys: set[str] = set()
    for entry in base_exp:
        key = (entry.get("company") or "").strip().lower()
        if key in lead_lower and key not in seen_lead_keys:
            leads_with_idx.append((lead_lower.index(key), entry))
            seen_lead_keys.add(key)
        else:
            rest.append(entry)
    leads_with_idx.sort(key=lambda x: x[0])
    cv_data["experience"] = [e for _, e in leads_with_idx] + rest

    # 3. Append bullet_additions to matching entries
    if bullet_additions:
        for company_key, extra_bullets in bullet_additions.items():
            target = company_key.strip().lower()
            for entry in cv_data["experience"]:
                if (entry.get("company") or "").strip().lower() == target:
                    existing = list(entry.get("highlights") or [])
                    entry["highlights"] = existing + list(extra_bullets)
                    break

    # 4. Reorder skills if priority supplied
    if skills_priority:
        skills = cv_data.get("skills") or {}
        if isinstance(skills, dict):
            ordered: dict = {}
            for cat in skills_priority:
                if cat in skills:
                    ordered[cat] = skills[cat]
            for cat, vals in skills.items():
                if cat not in ordered:
                    ordered[cat] = vals
            cv_data["skills"] = ordered

    # 5. Empty projects (they live in experience now)
    cv_data["projects"] = []

    # Stage everything so generate_pdf() (no args) can pick it up
    _tailoring_context.update({
        "job_title": job_title,
        "company": company,
        "job_description": job_description[:1500],
        "emphasis": emphasis or [],
        "built_cv": cv_data,
    })

    return ToolResult(
        success=True,
        data={
            "tailored": True,
            "target_role": f"{job_title} at {company}",
            "lead_entries": [e.get("role") for _, e in leads_with_idx],
            "experience_count": len(cv_data["experience"]),
            "note": (
                "CV built and staged. Now call generate_pdf() with NO args "
                "(or only filename) — the tool will use the staged tailored "
                "CV automatically. Then proceed to PHASE 3 (fill form)."
            ),
        },
    )


async def write_cover_letter(
    job_title: str,
    company: str,
    job_description: str,
    tone: str = "confident",
    max_words: int = 300,
) -> ToolResult:
    """Return context for the agent to write a cover letter.

    Args:
        job_title: Role being applied for
        company: Company name
        job_description: Full or summarised JD
        tone: "confident", "formal", "casual" — default confident
        max_words: Target length, default 300
    """
    return ToolResult(
        success=True,
        data={
            "cv": CV,
            "target": {
                "job_title": job_title,
                "company": company,
                "job_description": job_description,
            },
            "instructions": (
                f"Write a cover letter for {CV['name']} applying to {job_title} at {company}. "
                f"Tone: {tone}. Max {max_words} words. "
                f"Use contact details: {CV['contact']['email']}, {CV['contact']['phone']}. "
                "Lead with what makes Angelo uniquely qualified — not generic openers. "
                "Reference specific achievements from the CV that map to the JD. "
                "End with a confident close, not 'I look forward to hearing from you.' "
                "No corporate fluff. This is a builder talking to builders."
            ),
        },
    )


async def generate_pdf(
    content_type: str = "cv",
    tailored_cv: dict | None = None,
    cover_letter_text: str | None = None,
    filename: str | None = None,
) -> ToolResult:
    """Generate a PDF from CV data or cover letter text using WeasyPrint.

    Args:
        content_type: "cv" or "cover_letter"
        tailored_cv: Optional tailored CV dict (same structure as CV). Uses base CV if not provided.
        cover_letter_text: Cover letter text (required if content_type is "cover_letter")
        filename: Optional filename. Auto-generated if not provided.
    """
    # Mandatory tailoring guard — for a CV, the agent MUST have called
    # tailor_cv (which stages a built_cv on _tailoring_context) OR pass
    # tailored_cv explicitly. Otherwise we'd ship a generic untailored CV
    # to a job application.
    if content_type == "cv" and tailored_cv is None and not _tailoring_context.get("built_cv"):
        return ToolResult(
            success=False,
            data=(
                "Refused: tailor_cv() must be called first. Call tailor_cv("
                "job_title, company, job_description, new_summary, "
                "lead_with=[...]) — the tool builds the CV for you. Then "
                "call generate_pdf() (no args needed)."
            ),
        )

    # If tailor_cv staged a built_cv, use it as the tailored_cv automatically
    # (so the agent doesn't need to re-emit a giant dict as a tool arg).
    if tailored_cv is None and _tailoring_context.get("built_cv"):
        tailored_cv = _tailoring_context["built_cv"]
        # The tool already merged with base + applied transforms, so skip
        # the post-merge safety net by signalling strict.
        tailored_cv = {**tailored_cv, "_strict": True}

    # WeasyPrint needs Homebrew libs on macOS
    import platform
    if platform.system() == "Darwin":
        brew_lib = "/opt/homebrew/lib"
        current = os.environ.get("DYLD_LIBRARY_PATH", "")
        if brew_lib not in current:
            os.environ["DYLD_LIBRARY_PATH"] = f"{brew_lib}:{current}" if current else brew_lib

    from weasyprint import HTML

    if tailored_cv:
        # Merge partial tailored CV onto the base so missing keys (contact,
        # education, certifications) still render. The agent only needs to
        # send fields it actually customised — usually summary, experience,
        # projects, skills.
        cv_data = deepcopy(CV)
        # _strict signals "I know exactly which entries I want; don't
        # backfill from base." Used when intentionally narrowing a CV
        # to a different domain (e.g. cleaning role uses only day-job
        # entries, AI role uses only AI/founder entries).
        strict = bool(tailored_cv.get("_strict"))
        cv_data.update({k: v for k, v in tailored_cv.items() if v is not None and not k.startswith("_")})

        if not strict:
            # Safety net: a tailored CV must NOT be a thinner CV. If the
            # agent dropped experiences, append the missing ones from
            # base so the user's history is preserved. Match by company.
            base_exp = CV.get("experience", []) or []
            tailored_exp = cv_data.get("experience", []) or []
            seen_companies = {e.get("company", "").strip().lower() for e in tailored_exp}
            for base_entry in base_exp:
                key = base_entry.get("company", "").strip().lower()
                if key and key not in seen_companies:
                    tailored_exp.append(deepcopy(base_entry))
            cv_data["experience"] = tailored_exp

            # Project safety: if projects were emptied (folded into
            # experience), leave them empty. If non-empty but base had
            # more, backfill — the user wants every project visible.
            base_projects = CV.get("projects", []) or []
            tailored_projects = cv_data.get("projects", [])
            if tailored_projects:
                seen_projects = {p.get("name", "").strip().lower() for p in tailored_projects}
                for base_proj in base_projects:
                    key = base_proj.get("name", "").strip().lower()
                    if key and key not in seen_projects:
                        tailored_projects.append(deepcopy(base_proj))
                cv_data["projects"] = tailored_projects
    else:
        cv_data = deepcopy(CV)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if content_type == "cover_letter":
        if not cover_letter_text:
            return ToolResult(success=False, data="cover_letter_text required for cover_letter type")

        fname = filename or f"cover_letter_{timestamp}.pdf"
        html_content = _render_cover_letter_html(cover_letter_text, cv_data)
    else:
        fname = filename or f"cv_{timestamp}.pdf"
        html_content = _render_cv_html(cv_data)

    # Lock output directory — only basename is honoured. Prevents agents
    # from writing CVs to /tmp (where they get garbage-collected) or other
    # arbitrary locations. All generated PDFs land in data/cv_output/.
    fname = Path(fname).name
    if not fname.lower().endswith(".pdf"):
        fname = f"{fname}.pdf"
    output_path = CV_OUTPUT_DIR / fname

    try:
        await asyncio.to_thread(
            lambda: HTML(string=html_content).write_pdf(str(output_path))
        )
        return ToolResult(
            success=True,
            data={
                "path": str(output_path),
                "filename": fname,
                "type": content_type,
            },
        )
    except Exception as e:
        return ToolResult(success=False, data=f"PDF generation failed: {e}")


_SKILL_LABELS = {
    "languages": "Languages",
    "frontend": "Frontend",
    "backend": "Backend",
    "ai_ml": "AI / ML",
    "payments": "Payments",
    "tools": "Tools",
    "cloud_infra": "Cloud & Infra",
}


def _skill_label(cat: str) -> str:
    return _SKILL_LABELS.get(cat, cat.replace("_", " ").title())


def _render_cv_html(cv: dict) -> str:
    """Render CV data to dark sidebar HTML for PDF generation."""
    template = Template(CV_HTML_TEMPLATE)
    template.globals["skill_label"] = _skill_label
    return template.render(cv=cv)


def _render_cover_letter_html(text: str, cv: dict) -> str:
    """Render cover letter text to HTML for PDF generation."""
    template = Template(COVER_LETTER_HTML_TEMPLATE)
    return template.render(text=text, cv=cv)


# ── HTML Templates ──────────────────────────────────────────────────────────

CV_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  @page {
    margin: 0;
    size: 210mm 297mm;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 10px;
    color: #1a1a1a;
    background: #fff;
  }

  /* ── TWO COLUMN via fixed sidebar + margin ── */
  /* WeasyPrint: position:fixed repeats on every page */
  .sidebar {
    position: fixed;
    top: 0;
    left: 0;
    width: 72mm;
    height: 100%;
    background: #0f0f0f;
    color: #e8e8e8;
    padding: 36px 22px 36px 26px;
  }

  .sidebar-inner > * + * { margin-top: 22px; }

  .name-block .first {
    font-size: 28px;
    font-weight: bold;
    color: #fff;
    line-height: 1;
    letter-spacing: -0.5px;
    display: block;
  }
  .name-block .last {
    font-size: 28px;
    font-weight: bold;
    color: #c8f04a;
    line-height: 1;
    letter-spacing: -0.5px;
    display: block;
  }
  .name-block .title-text {
    margin-top: 10px;
    font-size: 7.5px;
    font-weight: 600;
    color: #666;
    letter-spacing: 2px;
    text-transform: uppercase;
  }

  .sidebar-section h3 {
    font-size: 6.5px;
    font-weight: 600;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #c8f04a;
    margin-bottom: 10px;
    padding-bottom: 5px;
    border-bottom: 1px solid #1e1e1e;
  }

  .contact-item {
    font-size: 8px;
    color: #aaa;
    margin-bottom: 7px;
  }
  .contact-item .label {
    font-size: 6.5px;
    color: #444;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 1px;
  }
  .contact-item .value { color: #ddd; display: block; }

  .skill-group { margin-bottom: 10px; }
  .skill-group .group-label {
    font-size: 6.5px;
    color: #444;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    margin-bottom: 5px;
  }
  .skill-tags { }
  .skill-tag {
    background: #181818;
    color: #bbb;
    font-size: 7px;
    padding: 2px 5px;
    border: 1px solid #252525;
    display: inline-block;
    margin: 0 2px 3px 0;
  }
  .skill-tag.highlight {
    background: #192200;
    color: #c8f04a;
    border-color: #304400;
  }

  .sidebar-note {
    font-size: 7.5px;
    color: #444;
    line-height: 1.6;
    padding-top: 14px;
    border-top: 1px solid #1a1a1a;
    margin-top: 16px;
  }
  .sidebar-note strong { color: #777; }

  /* ── MAIN CONTENT ── */
  .main {
    margin-left: 72mm;
    padding: 36px 32px 36px 26px;
  }

  .section { margin-bottom: 22px; }

  .section-header {
    margin-bottom: 14px;
    border-bottom: 1px solid #ededed;
    padding-bottom: 5px;
  }
  .section-header h2 {
    font-size: 7px;
    font-weight: 600;
    letter-spacing: 2.5px;
    text-transform: uppercase;
    color: #aaa;
  }

  .summary-text {
    font-size: 9px;
    color: #444;
    line-height: 1.7;
  }

  .exp-item {
    margin-bottom: 16px;
    padding-bottom: 16px;
    border-bottom: 1px solid #f5f5f5;
    page-break-inside: avoid;
  }
  .exp-item:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }

  .exp-top {
    overflow: hidden;
    margin-bottom: 5px;
  }
  .exp-title { font-size: 10px; font-weight: 600; color: #0f0f0f; }
  .exp-company { font-size: 8.5px; color: #999; margin-top: 1px; }
  .exp-date { font-size: 7.5px; color: #ccc; float: right; padding-top: 2px; }

  .exp-bullets { margin-top: 6px; list-style: none; padding: 0; }
  .exp-bullets li {
    font-size: 8.5px;
    color: #555;
    line-height: 1.55;
    padding-left: 14px;
    position: relative;
    margin-bottom: 3px;
  }
  .exp-bullets li::before {
    content: '\2014';
    position: absolute;
    left: 0;
    color: #c8f04a;
    font-size: 8px;
  }

  .project-item {
    padding: 10px 12px;
    background: #fafafa;
    border: 1px solid #f0f0f0;
    border-left: 3px solid #c8f04a;
    margin-bottom: 8px;
    page-break-inside: avoid;
  }
  .project-item:last-child { margin-bottom: 0; }

  .project-top { overflow: hidden; margin-bottom: 3px; }
  .project-name { font-size: 9.5px; font-weight: 600; color: #0f0f0f; }
  .project-stat {
    font-size: 6.5px;
    color: #c8f04a;
    font-weight: 600;
    background: #0f0f0f;
    padding: 2px 6px;
    letter-spacing: 0.5px;
    float: right;
  }
  .project-desc { font-size: 8px; color: #666; line-height: 1.5; margin-bottom: 5px; }
  .tech-tag {
    font-size: 6.5px;
    color: #999;
    background: #fff;
    border: 1px solid #e8e8e8;
    padding: 1px 5px;
    display: inline-block;
    margin: 0 2px 2px 0;
  }

  .edu-item {
    overflow: hidden;
    margin-bottom: 10px;
  }
  .edu-name { font-size: 9.5px; font-weight: 600; color: #0f0f0f; }
  .edu-detail { font-size: 8px; color: #999; margin-top: 1px; }
  .edu-note { font-size: 7.5px; color: #bbb; font-style: italic; margin-top: 2px; }
  .edu-year { font-size: 7.5px; color: #ccc; float: right; }

  .cert-item {
    margin-bottom: 5px;
    overflow: hidden;
  }
  .cert-dot {
    width: 5px;
    height: 5px;
    background: #c8f04a;
    border-radius: 50%;
    display: inline-block;
    margin-right: 6px;
    vertical-align: middle;
  }
  .cert-name { font-size: 8.5px; font-weight: 500; color: #333; }
  .cert-issuer { font-size: 7px; color: #bbb; float: right; }
</style>
</head>
<body>

  <div class="sidebar">
    <div class="sidebar-inner">
    <div class="name-block">
      <span class="first">{{ cv.get('first_name', cv.name.split()[0]) }}</span>
      <span class="last">{{ cv.get('last_name', cv.name.split()[-1]) }}</span>
      <div class="title-text">{{ cv.title }}</div>
    </div>

    <div class="sidebar-section">
      <h3>Contact</h3>
      <div class="contact-item">
        <span class="label">Email</span>
        <span class="value">{{ cv.contact.email }}</span>
      </div>
      <div class="contact-item">
        <span class="label">Location</span>
        <span class="value">{{ cv.contact.location }}</span>
      </div>
      {% if cv.contact.get('github') %}
      <div class="contact-item">
        <span class="label">GitHub</span>
        <span class="value">{{ cv.contact.github }}</span>
      </div>
      {% endif %}
      {% if cv.contact.get('linkedin') %}
      <div class="contact-item">
        <span class="label">LinkedIn</span>
        <span class="value">{{ cv.contact.linkedin }}</span>
      </div>
      {% endif %}
      {% if cv.contact.get('portfolio') %}
      <div class="contact-item">
        <span class="label">Portfolio</span>
        <span class="value">{{ cv.contact.portfolio }}</span>
      </div>
      {% endif %}
    </div>

    <div class="sidebar-section">
      <h3>Core Skills</h3>
      {% for cat, skill_data in cv.skills.items() %}
      <div class="skill-group">
        <div class="group-label">{{ skill_label(cat) }}</div>
        <div class="skill-tags">
          {% if skill_data is mapping and skill_data.get('items') %}
            {% set highlights = skill_data.get('highlight', []) %}
            {% for s in skill_data['items'] %}
            <span class="skill-tag{% if s in highlights %} highlight{% endif %}">{{ s }}</span>
            {% endfor %}
          {% elif skill_data is iterable and skill_data is not mapping %}
            {% for s in skill_data %}
            <span class="skill-tag">{{ s }}</span>
            {% endfor %}
          {% endif %}
        </div>
      </div>
      {% endfor %}
    </div>

    {% if cv.get('status') %}
    <div class="sidebar-section">
      <h3>Status</h3>
      {% if cv.status.get('right_to_work') %}
      <div class="contact-item">
        <span class="label">Right to Work</span>
        <span class="value">{{ cv.status.right_to_work }}</span>
      </div>
      {% endif %}
      {% if cv.status.get('availability') %}
      <div class="contact-item">
        <span class="label">Availability</span>
        <span class="value">{{ cv.status.availability }}</span>
      </div>
      {% endif %}
      {% if cv.status.get('work_preference') %}
      <div class="contact-item">
        <span class="label">Work Preference</span>
        <span class="value">{{ cv.status.work_preference }}</span>
      </div>
      {% endif %}
    </div>
    {% endif %}

    {% if cv.get('sidebar_note') %}
    <div class="sidebar-note">
      <strong>Self-taught.</strong> {{ cv.sidebar_note[12:] if cv.sidebar_note.startswith('Self-taught.') else cv.sidebar_note }}
    </div>
    {% endif %}
    </div>
  </div>

  <div class="main">

    <div class="section">
      <div class="section-header"><h2>Profile</h2></div>
      <p class="summary-text">{{ cv.summary }}</p>
    </div>

    <div class="section">
      <div class="section-header"><h2>Experience</h2></div>
      {% for job in cv.experience %}
      <div class="exp-item">
        <div class="exp-top">
          <span class="exp-date">{{ job.period }}</span>
          <div class="exp-title">{{ job.role }}</div>
          <div class="exp-company">{{ job.company }}{% if job.get('location') %} — {{ job.location }}{% endif %}</div>
        </div>
        {% if job.highlights %}
        <ul class="exp-bullets">
          {% for h in job.highlights %}
          <li>{{ h }}</li>
          {% endfor %}
        </ul>
        {% endif %}
      </div>
      {% endfor %}
    </div>

    {% if cv.get('projects') %}
    <div class="section">
      <div class="section-header"><h2>Selected Projects</h2></div>
      {% for proj in cv.projects %}
      <div class="project-item">
        <div class="project-top">
          {% if proj.get('stat') %}
          <span class="project-stat">{{ proj.stat }}</span>
          {% endif %}
          <span class="project-name">{{ proj.name }}</span>
        </div>
        <div class="project-desc">{{ proj.description }}</div>
        <div class="project-tech">
          {% for t in proj.tech %}
          <span class="tech-tag">{{ t }}</span>
          {% endfor %}
        </div>
      </div>
      {% endfor %}
    </div>
    {% endif %}

    <div class="section">
      <div class="section-header"><h2>Education &amp; Certifications</h2></div>
      {% for edu in cv.education %}
      <div class="edu-item">
        <span class="edu-year">{{ edu.period }}</span>
        <div class="edu-name">{{ edu.institution }}</div>
        <div class="edu-detail">{{ edu.qualification }}{% if edu.get('location') %} — {{ edu.location }}{% endif %}</div>
        {% if edu.get('note') %}
        <div class="edu-note">{{ edu.note }}</div>
        {% endif %}
      </div>
      {% endfor %}
      {% if cv.get('certifications') %}
      <div style="margin-top: 8px;">
        {% for cert in cv.certifications %}
        <div class="cert-item">
          <span class="cert-issuer">{{ cert.issuer }} — {{ cert.year }}</span>
          <span class="cert-dot"></span><span class="cert-name">{{ cert.name }}</span>
        </div>
        {% endfor %}
      </div>
      {% endif %}
    </div>

  </div>

</body>
</html>"""

COVER_LETTER_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<style>
    @page { margin: 0; size: A4; }
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
        font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        font-size: 11pt;
        line-height: 1.6;
        color: #1a1a1a;
    }
    .page {
        width: 210mm;
        min-height: 297mm;
        padding: 50px 60px;
    }
    .header {
        margin-bottom: 30px;
        padding-bottom: 20px;
        border-bottom: 2px solid #0f0f0f;
    }
    .header .name {
        font-size: 24pt;
        font-weight: bold;
        color: #0f0f0f;
        margin-bottom: 4px;
    }
    .header .title {
        font-size: 9pt;
        font-weight: 600;
        color: #666;
        letter-spacing: 2px;
        text-transform: uppercase;
        margin-bottom: 12px;
    }
    .contact {
        font-size: 9pt;
        color: #555;
    }
    .body-text {
        font-size: 10.5pt;
        line-height: 1.75;
        color: #333;
        white-space: pre-wrap;
        margin-top: 30px;
    }
</style>
</head>
<body>
<div class="page">
    <div class="header">
        <div class="name">{{ cv.get('first_name', cv.name.split()[0]) }} {{ cv.get('last_name', cv.name.split()[-1]) }}</div>
        <div class="title">{{ cv.title }}</div>
        <p class="contact">
            {{ cv.contact.email }} | {{ cv.contact.get('phone', '') }} | {{ cv.contact.location }}
        </p>
    </div>
    <div class="body-text">{{ text }}</div>
</div>
</body>
</html>"""


# ── Tool schemas for agent registration ─────────────────────────────────────

TOOL_SCHEMAS = {
    "get_cv": {
        "fn": get_cv,
        "schema": {
            "type": "function",
            "function": {
                "name": "get_cv",
                "description": "Get CV data — full or a specific section (experience, skills, projects, etc.)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "section": {
                            "type": "string",
                            "enum": ["all", "experience", "education", "skills", "projects", "summary", "contact"],
                            "description": "Which section to return. Default: all",
                        },
                    },
                },
            },
        },
    },
    "tailor_cv": {
        "fn": tailor_cv,
        "schema": {
            "type": "function",
            "function": {
                "name": "tailor_cv",
                "description": (
                    "Build a tailored CV from small deltas (no need to "
                    "emit a full CV dict). The tool reorders, replaces "
                    "summary, appends bullets, and stages the result. "
                    "After this, call generate_pdf() with NO args."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "job_title": {"type": "string", "description": "Role being applied for"},
                        "company": {"type": "string", "description": "Company name"},
                        "job_description": {"type": "string", "description": "Full or summarised JD (will be truncated)"},
                        "new_summary": {
                            "type": "string",
                            "description": (
                                "The new profile summary, ~3-6 sentences, "
                                "in the user's voice. Lead with concrete "
                                "proof of fit. NOT a template — name "
                                "specific shipped projects that match the "
                                "JD's top requirements."
                            ),
                        },
                        "lead_with": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Company names from the base CV that "
                                "should appear FIRST in priority order "
                                "(e.g. ['Diaspora AI Ltd', 'Self-directed', "
                                "'Diaspora AI Product Suite']). The tool "
                                "reorders for you. Anything not listed "
                                "keeps its original order at the bottom. "
                                "Use exact company strings from base CV."
                            ),
                        },
                        "bullet_additions": {
                            "type": "object",
                            "description": (
                                "Optional. Map of company name → list of "
                                "extra bullet strings to APPEND to that "
                                "entry. Use sparingly, only for the 1-2 "
                                "lead entries to add JD-matching depth."
                            ),
                        },
                        "skills_priority": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Optional. Skill category names (e.g. "
                                "['ai_ml', 'backend', 'languages']) in "
                                "priority order. Unlisted categories follow."
                            ),
                        },
                        "emphasis": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional. Themes/skills to highlight",
                        },
                    },
                    "required": ["job_title", "company", "job_description", "new_summary", "lead_with"],
                },
            },
        },
    },
    "write_cover_letter": {
        "fn": write_cover_letter,
        "schema": {
            "type": "function",
            "function": {
                "name": "write_cover_letter",
                "description": "Get CV + job context for writing a cover letter. Returns data and instructions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "job_title": {"type": "string", "description": "Role being applied for"},
                        "company": {"type": "string", "description": "Company name"},
                        "job_description": {"type": "string", "description": "Job description"},
                        "tone": {
                            "type": "string",
                            "enum": ["confident", "formal", "casual"],
                            "description": "Tone of the letter. Default: confident",
                        },
                        "max_words": {
                            "type": "integer",
                            "description": "Target word count. Default: 300",
                        },
                    },
                    "required": ["job_title", "company", "job_description"],
                },
            },
        },
    },
    "generate_pdf": {
        "fn": generate_pdf,
        "schema": {
            "type": "function",
            "function": {
                "name": "generate_pdf",
                "description": "Generate a PDF of the CV or a cover letter. Returns the file path.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content_type": {
                            "type": "string",
                            "enum": ["cv", "cover_letter"],
                            "description": "What to generate. Default: cv",
                        },
                        "tailored_cv": {
                            "type": "object",
                            "description": "Optional tailored CV data (same structure as base CV). Uses base CV if not provided.",
                        },
                        "cover_letter_text": {
                            "type": "string",
                            "description": "Cover letter text. Required if content_type is cover_letter.",
                        },
                        "filename": {
                            "type": "string",
                            "description": "Optional filename for the PDF.",
                        },
                    },
                },
            },
        },
    },
}
