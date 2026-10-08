"""On-demand summaries of stored versions/results. No model calls or new facts."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, KeepTogether

ROOT = Path(__file__).resolve().parents[2]


def render_pdf(title, subtitle, sections, *, status, reference):
    font = ROOT / 'scribe/assets/fonts/DejaVuSans.ttf'
    if 'MedflowSans' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('MedflowSans', str(font)))
    styles = getSampleStyleSheet()
    body = ParagraphStyle('MFBody', fontName='MedflowSans', fontSize=10, leading=17,
                          textColor=colors.HexColor('#303b38'), spaceAfter=10, splitLongWords=True)
    heading = ParagraphStyle('MFHeading', parent=body, fontSize=11, leading=16,
                             textColor=colors.HexColor('#15584a'), spaceBefore=14, spaceAfter=8)
    urdu = ParagraphStyle('MFUrdu', parent=body, alignment=TA_RIGHT, leading=20)

    def paragraph(text, style=body):
        text = str(text or 'Not documented.')
        if re.search('[\u0600-\u06ff]', text):
            import arabic_reshaper
            from bidi.algorithm import get_display
            text = get_display(arabic_reshaper.reshape(text))
            style = urdu
        return Paragraph(escape(text).replace('\n','<br/>'), style)

    stream = BytesIO()
    document = SimpleDocTemplate(stream, pagesize=A4, rightMargin=20*mm, leftMargin=20*mm,
        topMargin=19*mm, bottomMargin=22*mm, title=title, author='Medflow Clinical Studio')
    title_style = ParagraphStyle('MFTitle', parent=styles['Title'], fontName='MedflowSans',
                                fontSize=28, leading=32, alignment=0, spaceAfter=12)
    content = [paragraph('MEDFLOW  /  CLINICAL STUDIO', heading), paragraph(title, title_style),
               paragraph(subtitle), paragraph(status, heading),
               HRFlowable(width='100%', color=colors.HexColor('#d5dfdb')), Spacer(1, 8)]
    for label, lines in sections:
        content.append(KeepTogether([paragraph(label,heading), paragraph(lines[0] if lines else 'Not documented.')]))
        content.extend(paragraph(line) for line in lines[1:])

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor('#d5dfdb'))
        canvas.line(20*mm,17*mm,A4[0]-20*mm,17*mm)
        canvas.setFont('MedflowSans',7)
        canvas.setFillColor(colors.HexColor('#52655e'))
        canvas.drawString(20*mm,12*mm,reference[:100])
        canvas.drawRightString(A4[0]-20*mm,12*mm,f'Page {doc.page}')
        canvas.restoreState()

    document.build(content,onFirstPage=footer,onLaterPages=footer)
    return stream.getvalue()


def visit_pdf(payload, patient, doctor, *, technical=False):
    approved = payload['state'] == 'APPROVED_BY_DOCTOR'
    soap = payload['soap']
    sections = [('Patient & visit', [f"{patient.name} | Age: {patient.age_text or 'Not documented'}",
                    f"Doctor: {doctor} | Encounter: {payload['encounter_id']}"])]
    sections.extend((label,[soap.get(key,'')]) for key,label in [
        ('subjective','History'),('objective','Documented findings'),
        ('assessment','Assessment'),('plan','Plan & follow-up')])
    cards = soap.get('medicine_evidence',{}).get('items',[])
    if approved and not technical:
        instructions = list(dict.fromkeys(link['text'] for card in cards
                          for link in card['soap_links'] if link['section']=='plan'))
        if instructions:
            sections.append(('Medication instructions - as documented', instructions + [
                'Only the instructions stated in the approved Plan are reproduced. '
                'No dose, frequency, duration or replacement medicine has been added.']))
    if technical:
        sections.append(('Evidence scope',[soap.get('medicine_evidence',{}).get('scope','')]))
        for card in cards:
            catalogue = card.get('catalogue') or {}
            sections.append((f"Medicine: {card['final_name']} | Source {card['utterance_id']}",[
                card['original'], f"English: {card['translation']}",
                f"Proposed: {card['proposed_name']} | Confirmed: {card.get('confirmed_name') or 'No explicit spelling confirmation'}",
                f"Catalogue: {catalogue.get('name','No exact match')} | Reference: {catalogue.get('source_filename') or catalogue.get('source_url') or 'None'}",
                f"Doctor wording review: {'Recorded' if card['doctor_reviewed'] else 'Not recorded'} | SOAP sections: {', '.join(link['section'] for link in card['soap_links']) or 'Missing'}",
            ]))
        sections.append(('Recorded limitations', soap.get('structured_soap',{}).get('warnings',[]) or ['Source linkage does not establish clinical correctness.']))
    return render_pdf('Technical Evidence Report' if technical else 'Visit Summary',
        f"Visit {payload['created_at'][:10]} | Note version {payload['version']}", sections,
        status=('Doctor approved' if approved else 'DRAFT - not approved for patient use') + ' | FYP synthetic-data demonstration',
        reference=f"{payload['note_id']} / v{payload['version']} - Synthetic demo; not a clinical prescription")


def testing_pdf(report):
    sections = [('Measured summary',[
        ' | '.join(f'{key}: {value}' for key,value in report['totals'].items()),
        f"Elapsed: {report.get('duration_ms')} ms | {report['timing_scope']}",
        f"Run: {report['run_id']} | Pack: {report['pack_version']}",
        f"Source SHA256: {report.get('environment',{}).get('source_sha256','Not recorded')}"])]
    for case in report['cases']:
        lines=[f"Input: {case['input']}",f"Expected: {case['expected']}",f"Scope: {case['scope']}"]
        if case.get('duration_ms') is not None:
            lines.append(f"Measured duration: {case['duration_ms']} ms")
        for check in case.get('checks',[]):
            lines.append(f"{check['status']} - {check['label']} | Expected: {check['expected']} | Actual: {check['actual']}")
        if case.get('error'):lines.append(case['error']['message'])
        if not case.get('checks'):lines.append('No completed assertions; not counted as a pass.')
        sections.append((case['title']+' - '+case['status'],lines))
    sections.append(('Evaluation limits',['Synthetic results check software behavior, not microphone recognition or clinical accuracy. '
        'Live text results use provider requests but do not measure audio or validated medical correctness.']))
    return render_pdf('Demo Testing Report',report['started_at'],sections,status=report['status'],reference=report['run_id'])
