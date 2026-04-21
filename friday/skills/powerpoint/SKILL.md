---
name: powerpoint
description: Create and edit PowerPoint/PPTX presentations. Use when Travis needs slides, pitch decks, or presentations.
agents: [system_agent, job_agent, code_agent]
---

# PowerPoint / PPTX

Create professional presentations using python-pptx.

## Install (if needed)

```bash
pip install python-pptx
```

## Create a Presentation

```python
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN

prs = Presentation()

# Title slide
slide = prs.slides.add_slide(prs.slide_layouts[0])
slide.shapes.title.text = "Presentation Title"
slide.placeholders[1].text = "Subtitle or author"

# Content slide with bullet points
slide = prs.slides.add_slide(prs.slide_layouts[1])
slide.shapes.title.text = "Key Points"
body = slide.placeholders[1]
tf = body.text_frame
tf.text = "First point"
for point in ["Second point", "Third point", "Fourth point"]:
    p = tf.add_paragraph()
    p.text = point
    p.level = 0

# Blank slide with custom text
slide = prs.slides.add_slide(prs.slide_layouts[6])
txBox = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(8), Inches(5))
tf = txBox.text_frame
tf.word_wrap = True
p = tf.paragraphs[0]
p.text = "Custom content here"
p.font.size = Pt(18)

prs.save("presentation.pptx")
```

## Common Slide Layouts

| Index | Layout Name | Use For |
|-------|-------------|---------|
| 0 | Title Slide | First slide, title + subtitle |
| 1 | Title and Content | Section with bullet points |
| 2 | Section Header | Section divider |
| 5 | Title Only | Custom layouts |
| 6 | Blank | Full custom content |

## Add Image to Slide

```python
slide = prs.slides.add_slide(prs.slide_layouts[6])
slide.shapes.add_picture("image.png", Inches(1), Inches(1), Inches(6))
```

## Add Table

```python
slide = prs.slides.add_slide(prs.slide_layouts[6])
rows, cols = 4, 3
table_shape = slide.shapes.add_table(rows, cols, Inches(1), Inches(1.5), Inches(8), Inches(3))
table = table_shape.table
table.cell(0, 0).text = "Header 1"
table.cell(0, 1).text = "Header 2"
table.cell(1, 0).text = "Data"
```

## Pitch Deck Structure

When Travis says "create a pitch deck":

1. **Title** — Company name, tagline, your name
2. **Problem** — What problem you're solving (1 slide, clear pain point)
3. **Solution** — Your product/approach (1 slide, with screenshot if possible)
4. **Market** — TAM/SAM/SOM or target audience
5. **Traction** — Users, revenue, growth metrics
6. **Business Model** — How you make money
7. **Team** — Who's building it
8. **Ask** — What you need (funding, partnerships, etc.)

Keep it to 8-12 slides. No walls of text. One point per slide.

## Where to Save

Save to `~/Documents/friday_files/` unless specified.
Name files descriptively: `diaspora_ai_pitch_deck.pptx`, `project_overview.pptx`
