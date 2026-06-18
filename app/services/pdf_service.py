from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import getSampleStyleSheet
import tempfile


def generate_mom_pdf(meeting, tasks):

    file_path = tempfile.NamedTemporaryFile(
        delete=False,
        suffix=".pdf"
    ).name

    doc = SimpleDocTemplate(file_path)

    styles = getSampleStyleSheet()
    content = []

    content.append(
        Paragraph(f"Meeting: {meeting['title']}", styles["Title"])
    )

    content.append(
        Paragraph(f"Summary: {meeting['summary']}", styles["BodyText"])
    )

    content.append(
        Paragraph("Tasks:", styles["Heading2"])
    )

    for task in tasks:
        text = f"""
• {task['title']}  
Priority: {task['priority']}  
Deadline: {task['deadline']}
"""
        content.append(Paragraph(text, styles["BodyText"]))

    doc.build(content)

    return file_path
